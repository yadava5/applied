"""Agreeing with the classifier is not correcting it.

Why this file exists
--------------------

``POST /applications/review/{message_id}/classify`` wrote::

    email.classified_as = category
    email.is_reviewed = True
    email.user_corrected = True

unconditionally. A reader who AGREES with the machine's verdict and a reader who
OVERRULES it produced byte-identical rows — and the first of those three lines
had already overwritten the machine's verdict, so nothing on the row could tell
them apart afterwards either.

Every "the classifier was wrong N times" figure built on that flag is inflated
by an unknown amount, in the direction that makes the classifier look worse than
it is. It reached a reader: an audit read production, saw ``user_corrected`` on
every REJECTION row, and reported that the classifier had never once
auto-detected a rejection. Replayed through the real classifier the owner's
Palantir message returns ``rejection`` at 0.75 — the correct category, held
under the 0.85 gate for a human who agreed with it. The two
``Crusoe | Application Received`` rows at 0.95 carry the same flag, and nobody
corrects an acknowledgement the machine already had at 0.95.

The distinction now lives in ``emails.review_disposition``
(:class:`~jobtracker.database.models.ReviewDisposition`). ``user_corrected`` is
NOT redefined — it still means "a human settled this row", which four monitoring
and labeling queries depend on.

Every assertion here was checked by breaking the thing it covers; the mutation
and its result are recorded on each test.
"""

from __future__ import annotations

import importlib
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parent.parent

JWT_SECRET = "review-disposition-test-jwt-secret-at-least-32-bytes-hs256"
OWNER = "aaaaaaaa-1111-2222-3333-555555555555"

# The owner's Palantir rejection (email 114), which the classifier read
# CORRECTLY at 0.75 and could not act on. It is parked: ``classified_as`` is the
# typed null and the real proposal rides in ``suggested_category``.
PALANTIR_SUBJECT = (
    "Thank you from Palantir Technologies - Ayush Yadav - Software Engineer, New Grad"
)
PALANTIR_SENDER = "no-reply@hire.lever.co"
PALANTIR_SNIPPET = (
    "Dear Ayush, Thank you for your interest in Palantir. After careful "
    "consideration, we regret to inform you that we will not be proceeding "
    "with your candidacy for this role at this time. Please note that"
)


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB (see test_mail_listing)."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    # REBIND, never ``importlib.reload``. That module does ``from
    # jobtracker.config import settings``, so it holds the singleton the reload
    # above has just replaced and it does need putting right — but reloading it
    # also rebuilds ``AuthError``, and ``tests/test_auth_supabase_jwt.py``
    # imported that class at collection time. Its twelve
    # ``pytest.raises(AuthError)`` blocks then stop catching the exception the
    # dependency raises, and eleven of them fail on class identity in any
    # session where this file ran first — which alphabetically is every one.
    # Measured both ways; see the teardown for the other half.
    auth_module.settings = config_module.settings

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None
    monkeypatch.undo()
    importlib.reload(config_module)
    # AND point the auth module at the settings object that reload just made.
    #
    # ``jobtracker.auth.supabase_jwt`` does ``from jobtracker.config import
    # settings``, binding the SINGLETON rather than the module. The reload above
    # constructs a NEW singleton, so without this line ``supabase_jwt.settings``
    # is left holding the discarded one — and
    # ``tests/test_auth_supabase_jwt.py``'s ``configured_secret`` fixture, which
    # patches ``config_module.settings.supabase_jwt_secret`` and says in its own
    # comment that "no reload required", then patches an object nothing reads.
    # All 12 of its tests fail with "401: Invalid signature", in the same
    # session, only after this file — which alphabetically is always.
    #
    # Rebound rather than reloaded, for the reason given at the setup site.
    auth_module.settings = config_module.settings


async def _seed(
    *,
    message_id: str,
    classified_as,
    suggested_category=None,
    confidence: float | None = 0.75,
) -> None:
    """Store one row exactly as a sync would have left it."""

    from datetime import datetime

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import ClassificationMethod, Email, EmailSource

    async with get_session() as session:
        session.add(
            Email(
                user_id=uuid.UUID(OWNER),
                source_account=EmailSource.GMAIL,
                message_id=message_id,
                subject=PALANTIR_SUBJECT,
                sender_email=PALANTIR_SENDER,
                sender_name="Palantir Technologies",
                body_snippet=PALANTIR_SNIPPET,
                received_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
                classified_as=classified_as,
                suggested_category=suggested_category,
                classification_confidence=confidence,
                classification_method=ClassificationMethod.RULES,
                user_corrected=False,
                is_reviewed=False,
            )
        )
        await session.commit()


async def _stored(message_id: str):
    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        return (
            await session.exec(
                select(Email).where(
                    Email.user_id == uuid.UUID(OWNER), Email.message_id == message_id
                )
            )
        ).first()


async def _classify(cloud_app, message_id: str, category: str, **extra) -> Any:
    body: dict[str, Any] = {"category": category, "company": "Palantir"}
    body.update(extra)
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        return await client.post(
            f"/applications/review/{message_id}/classify",
            json=body,
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )


# =============================================================================
# The premise. Every test below asserts a disposition; these prove the seeded
# rows do not already carry one, so a green file cannot be a green fixture.
# =============================================================================


async def test_a_synced_row_carries_no_disposition(cloud_app):
    """Nobody has decided anything about a freshly synced row.

    NULL here is a state and not a placeholder: it means no human decision is
    recorded, which is different from every value the enum can hold.
    """

    from jobtracker.database.models import EmailCategory

    await _seed(
        message_id="premise",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )

    stored = await _stored("premise")
    assert stored is not None
    assert stored.review_disposition is None
    assert stored.user_corrected is False
    assert stored.suggested_category is EmailCategory.REJECTION


# =============================================================================
# The fix: the two acts are now different rows
# =============================================================================


async def test_agreeing_with_a_parked_proposal_records_confirmation(cloud_app):
    """The Palantir row. The classifier was RIGHT and was overruled by nobody.

    This is the row that made an audit report the classifier had never
    auto-detected a rejection. Before the fix it was byte-identical to the
    override below.

    Mutation: writing ``ReviewDisposition.OVERRIDDEN`` unconditionally at the
    endpoint → fails here, disposition is ``overridden``.
    """

    from jobtracker.database.models import EmailCategory, ReviewDisposition

    await _seed(
        message_id="agree",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )

    res = await _classify(cloud_app, "agree", "rejection")
    assert res.status_code == 200, res.text

    stored = await _stored("agree")
    assert stored.review_disposition is ReviewDisposition.CONFIRMED
    # Deliberately unchanged. ``user_corrected`` means "a human settled this
    # row", and an agreement settles it. Narrowing this flag would push every
    # confirmed row back into the weekly labeling queue and the needs-review
    # count, neither of which filters ``is_reviewed``.
    assert stored.user_corrected is True
    assert stored.is_reviewed is True


async def test_overruling_a_parked_proposal_records_an_override(cloud_app):
    """The other act, from the same starting row.

    Mutation: writing ``ReviewDisposition.CONFIRMED`` unconditionally → fails
    here, disposition is ``confirmed``.
    """

    from jobtracker.database.models import EmailCategory, ReviewDisposition

    await _seed(
        message_id="override",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )

    res = await _classify(cloud_app, "override", "applied")
    assert res.status_code == 200, res.text

    stored = await _stored("override")
    assert stored.review_disposition is ReviewDisposition.OVERRIDDEN
    assert stored.user_corrected is True


async def test_the_two_acts_no_longer_produce_the_same_row(cloud_app):
    """The defect, stated as one assertion.

    Before the fix every column these two rows differ in was equal: same
    ``user_corrected``, same ``is_reviewed``, same nulled confidence, same
    ``user`` method. Only ``classified_as`` differed, and that is the human's
    answer rather than a record of what they did to the machine's.
    """

    from jobtracker.database.models import EmailCategory

    await _seed(
        message_id="pair-agree",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )
    await _seed(
        message_id="pair-override",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )

    assert (await _classify(cloud_app, "pair-agree", "rejection")).status_code == 200
    assert (await _classify(cloud_app, "pair-override", "applied")).status_code == 200

    agreed = await _stored("pair-agree")
    overruled = await _stored("pair-override")

    assert agreed.user_corrected == overruled.user_corrected
    assert agreed.is_reviewed == overruled.is_reviewed
    assert agreed.review_disposition is not overruled.review_disposition


# =============================================================================
# A COMMITTED verdict is a verdict too — the Crusoe shape
# =============================================================================


async def test_reclassifying_a_filed_row_to_its_own_category_is_a_confirmation(
    cloud_app,
):
    """``Crusoe | Application Received``, filed ``applied`` at 0.95.

    Both of the owner's Crusoe rows are flagged corrected. Nobody corrects an
    acknowledgement the machine already had at 0.95 — the reader opened the
    filed ledger, agreed, and the row recorded an override.

    A filed row has no ``suggested_category`` (the proposal was resolved into a
    commitment), so the machine's verdict has to be read off ``classified_as``
    BEFORE the endpoint overwrites it. That ordering is the whole fix.

    Mutation: moving the disposition block below ``email.classified_as =
    category`` → fails, every row reads ``confirmed`` because the comparison is
    against the value just written.
    """

    from jobtracker.database.models import EmailCategory, ReviewDisposition

    await _seed(
        message_id="crusoe",
        classified_as=EmailCategory.APPLIED,
        confidence=0.95,
    )

    res = await _classify(cloud_app, "crusoe", "applied")
    assert res.status_code == 200, res.text

    stored = await _stored("crusoe")
    assert stored.review_disposition is ReviewDisposition.CONFIRMED


async def test_reclassifying_a_filed_row_to_a_different_category_is_an_override(
    cloud_app,
):
    """The mirror of the test above, so "confirmed" cannot be a constant."""

    from jobtracker.database.models import EmailCategory, ReviewDisposition

    await _seed(
        message_id="crusoe-wrong",
        classified_as=EmailCategory.APPLIED,
        confidence=0.95,
    )

    res = await _classify(cloud_app, "crusoe-wrong", "rejection")
    assert res.status_code == 200, res.text

    stored = await _stored("crusoe-wrong")
    assert stored.review_disposition is ReviewDisposition.OVERRIDDEN


# =============================================================================
# What NEEDS_REVIEW is, and is not
# =============================================================================


async def test_needs_review_is_never_read_as_the_machines_verdict(cloud_app):
    """``NEEDS_REVIEW`` in ``classified_as`` is the typed null, not a category.

    A parked row with no ``suggested_category`` — every row synced before that
    column existed — carries no machine verdict at all. Comparing the human's
    choice against the literal ``needs_review`` would call every one of them an
    OVERRIDE, which is the same forgery this file removes: a stored value
    asserting a human act nobody performed. It is ``unattributed``, which says
    there was nothing to agree or disagree with.

    Mutation: dropping the ``is not EmailCategory.NEEDS_REVIEW`` guard → fails,
    disposition is ``overridden``.
    """

    from jobtracker.database.models import EmailCategory, ReviewDisposition

    await _seed(
        message_id="typed-null",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=None,
    )

    res = await _classify(cloud_app, "typed-null", "rejection")
    assert res.status_code == 200, res.text

    stored = await _stored("typed-null")
    assert stored.review_disposition is ReviewDisposition.UNATTRIBUTED


async def test_a_live_scan_row_with_no_verdict_is_unattributed(cloud_app):
    """The other way to have no machine verdict: ``ScannedMessageIn`` mints one.

    ``category`` on that model is optional, so a client can store a message the
    scan formed no opinion about. The human supplied the FIRST verdict rather
    than ruling on one.
    """

    from jobtracker.database.models import ReviewDisposition

    res = await _classify(
        cloud_app,
        "minted-no-verdict",
        "rejection",
        message={
            "sender_email": PALANTIR_SENDER,
            "received_at": "2026-08-11T09:00:00Z",
            "subject": PALANTIR_SUBJECT,
            "snippet": PALANTIR_SNIPPET,
        },
    )
    assert res.status_code == 200, res.text

    stored = await _stored("minted-no-verdict")
    assert stored.classified_as.value == "rejection"
    assert stored.review_disposition is ReviewDisposition.UNATTRIBUTED


# =============================================================================
# It has to reach a reader, or the fix is invisible
# =============================================================================


async def test_the_mail_listing_reports_the_disposition(cloud_app):
    """The filed ledger draws "corrected by you" off this, not off the flag.

    ``user_corrected`` is true on both rows below. A client with only that
    column tells the reader who AGREED that they overruled the classifier,
    which is the same false statement the audit made, rendered per row.
    """

    from jobtracker.database.models import EmailCategory

    await _seed(
        message_id="listed-agree",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )
    await _seed(
        message_id="listed-override",
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=EmailCategory.REJECTION,
    )
    assert (await _classify(cloud_app, "listed-agree", "rejection")).status_code == 200
    assert (await _classify(cloud_app, "listed-override", "applied")).status_code == 200

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get(
            "/applications/mail",
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )
    assert res.status_code == 200, res.text

    by_id = {m["message_id"]: m for m in res.json()["messages"]}
    assert by_id["listed-agree"]["user_corrected"] is True
    assert by_id["listed-override"]["user_corrected"] is True
    assert by_id["listed-agree"]["review_disposition"] == "confirmed"
    assert by_id["listed-override"]["review_disposition"] == "overridden"


# =============================================================================
# The rows that came before. Nothing is guessed about them.
# =============================================================================


DISPOSITION_REVISION = "b3e91c47da05"


def _revision_parent(revision: str) -> str:
    """The ``down_revision`` a revision module declares, read from its source.

    Parsed rather than imported: an Alembic revision module is not on the import
    path and importing it would pull ``alembic.op`` into a context with no
    migration running.
    """

    import ast

    path = next(
        (BACKEND_DIR / "alembic" / "versions").glob(f"{revision}_*.py")
    )
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "down_revision":
            parent = ast.literal_eval(node.value)
            assert isinstance(parent, str), f"{revision} has no single parent: {parent!r}"
            return parent
    raise AssertionError(f"{revision} declares no down_revision")


_DISPOSITION_PARENT = _revision_parent(DISPOSITION_REVISION)


def _run_alembic(args: list[str], database_url: str) -> subprocess.CompletedProcess:
    import os

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.pop("DIRECT_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_migration_calls_the_existing_rows_unknown_and_guesses_nothing(
    tmp_path: Path,
) -> None:
    """The historical rows cannot be disentangled, so they are not labelled.

    A ``user_corrected`` row written before ``b3e91c47da05`` may be an agreement
    or an override and the evidence is gone — the correction overwrote
    ``classified_as`` in place. Replaying today's classifier over them would
    reconstruct what today's classifier says, not what the reader was shown, so
    the backfill writes ``UNKNOWN``: a human decision is on record and which act
    it was is not recoverable.

    This walks the chain to the revision BEFORE the new one, inserts the shape
    production holds, and upgrades — so it measures the migration rather than
    the model.

    The step target is read from the revision's own ``down_revision`` rather
    than typed here. A literal would silently stop being "the revision before"
    the moment this one is re-parented onto a newer head, which it was once
    already while this branch was open.

    Mutation: backfilling ``'CONFIRMED'`` (or ``'OVERRIDDEN'``) instead → fails,
    and would have been a guessed label that reads as data.
    """

    db = tmp_path / "disposition_backfill.db"
    url = f"sqlite:///{db}"

    stepped = _run_alembic(["upgrade", _DISPOSITION_PARENT], url)
    assert stepped.returncode == 0, stepped.stderr

    conn = sqlite3.connect(db)
    try:
        assert "review_disposition" not in {
            row[1] for row in conn.execute("PRAGMA table_info(emails)")
        }, "the column must not exist yet, or this test proves nothing"
        conn.executemany(
            "INSERT INTO emails "
            "(user_id, source_account, message_id, received_at, classified_as, "
            " user_corrected, is_reviewed, created_at) "
            "VALUES (?, 'GMAIL', ?, '2026-08-11 09:00:00', ?, ?, ?, "
            " '2026-08-11 09:00:00')",
            [
                (OWNER, "legacy-corrected", "REJECTION", 1, 1),
                (OWNER, "legacy-untouched", "APPLIED", 0, 0),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    upgraded = _run_alembic(["upgrade", "head"], url)
    assert upgraded.returncode == 0, upgraded.stderr

    conn = sqlite3.connect(db)
    try:
        rows = dict(
            conn.execute(
                "SELECT message_id, review_disposition FROM emails ORDER BY message_id"
            )
        )
    finally:
        conn.close()

    # A human decided; which act it was is not knowable. Not "confirmed",
    # not "overridden", and not NULL — NULL already means something else.
    assert rows["legacy-corrected"] == "UNKNOWN"
    # And a row nobody touched keeps the state that says exactly that.
    assert rows["legacy-untouched"] is None
