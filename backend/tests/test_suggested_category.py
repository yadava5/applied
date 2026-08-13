"""A parked verdict must survive as a PROPOSAL, and must never act as one.

Why this file exists
--------------------

Applied has recorded zero non-applied application statuses in production. The
mechanism is small and complete: a rejection that arrives through an ATS relay
cannot have its employer named, so it is parked in the review queue — and both
``_persist_review_items`` and ``_persist_review_items_additive`` hardcoded
``category="needs_review"`` on the way in, destroying the classifier's verdict
before it was ever written. The stored row read "needs_review at 0.92": the
strength of an opinion whose content had been deleted.

The obvious fix is wrong and was measured to be wrong. ``emails.classified_as``
does not mean "what the mail is"; it means the COMMITTED category, the one the
system may act on, and ``NEEDS_REVIEW`` is its typed null. Carrying the real
category into it turned 700 passing tests into 9 failing ones, and those 9 were
the design working — writing a verdict there for a parked row does not record a
verdict, it forges a commitment. So the verdict goes in its own nullable column,
``suggested_category``, and NO existing reader's predicate changes.

The corpus could not have caught this
-------------------------------------

Every pre-existing rejection fixture pins an Amazon sender AND an Amazon
subject — a corporate domain plus the employer anchor — so the whole corpus sat
at (rejection, resolvable), while production's dominant shape is (rejection,
UNRESOLVABLE). The fixture here is the production shape, and it pins its own
premise: if ``resolve_employer`` later improves, assertion (i) fails loudly at
the premise instead of silently migrating the test onto the hard-row path where
it would prove nothing.

What each test holds down
-------------------------

* :func:`test_a_parked_verdict_is_recorded_and_can_be_committed` — the
  end-to-end that would have caught the original bug. Mutation-proven: dropping
  ``suggested_category=item.category`` at the two persist sites turns it red.
* :func:`test_a_parked_row_gains_its_suggestion_on_the_next_sync` — the
  backfill is automatic, and it stops at a settled row.
* :func:`test_a_suggestion_never_acts` — the inversion canary, and the most
  important test here. Without the linker's guard a parked rejection could
  terminally reject a live application off an unconfirmed guess, attributed by
  recency, and freeze it against every later interview or offer.
"""

from __future__ import annotations

import importlib
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "suggested-category-test-jwt-secret-at-least-32-bytes-hs256"
# ``POST /gmail/sync`` reads the stored credential before it looks at the
# relayed items, so the cloud credential store has to be usable even though
# nothing here ever connects Gmail.
ENC_KEY = Fernet.generate_key().decode()
USER = "dddddddd-dddd-dddd-dddd-dddddddddddd"

# The production shape, verbatim: a Workday relay names no employer, and
# "Update on your application" carries no at/with/to connective, no display
# name, no pipe and no spaced dash — so every one of ``resolve_employer``'s four
# steps declines. This is the mail that files nothing.
RELAY_SENDER = "no-reply@myworkday.com"
RELAY_SUBJECT = "Update on your application"

# Derived by reading ``models.CATEGORY_TO_STATUS`` rather than guessed:
# ``assessment`` maps to itself as of revision b9e42f7c10ad, and guessing
# ``interviewing`` there would have failed for the wrong reason.
CATEGORY_TO_EXPECTED_STATUS = {
    "rejection": "rejected",
    "interview": "interviewing",
    "offer": "offered",
    "assessment": "assessment",
}


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB (see test_user_id_scoping)."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.cloud.gmail_oauth as gmail_module

    importlib.reload(gmail_module)

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


@pytest.fixture
async def client(cloud_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(
        transport=transport, base_url="http://cloud-test", follow_redirects=False
    ) as c:
        yield c


def _relay_item(message_id: str, category: str) -> dict[str, Any]:
    """One confident verdict on mail whose employer cannot be named."""

    return {
        "message_id": message_id,
        "category": category,
        "confidence": 0.90,
        "sender_email": RELAY_SENDER,
        "sender_name": None,
        "subject": RELAY_SUBJECT,
        "received_at": "2026-08-01T12:00:00+00:00",
    }


async def _stored_email(message_id: str) -> Any:
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        return (
            await session.exec(sm_select(Email).where(Email.message_id == message_id))
        ).first()


@pytest.mark.parametrize("category", sorted(CATEGORY_TO_EXPECTED_STATUS))
async def test_a_parked_verdict_is_recorded_and_can_be_committed(
    client: AsyncClient, category: str
) -> None:
    """The production-shaped end-to-end: parked, but no longer silent.

    Three assertions, in the order the bug happens:

    (i)   the PREMISE — this mail's employer is genuinely unnameable, so the
          item really does take the review path and not the hard-row path;
    (ii)  it reaches the queue AND the stored row carries the verdict in
          ``suggested_category`` (it was ``needs_review at 0.90`` and nothing
          else before this change);
    (iii) committing it with an employer produces an application at the stage
          the verdict implied — which is the status production has never once
          recorded.
    """

    from jobtracker.cloud import pipeline

    # (i) Premise. If the resolver ever learns to name a Workday relay, this
    # fails here rather than quietly testing a different code path.
    assert pipeline.resolve_employer(RELAY_SENDER, RELAY_SUBJECT, None) is None

    headers = {"Authorization": f"Bearer {_token_for(USER)}"}
    message_id = f"relay-{category}"
    resp = await client.post(
        "/gmail/sync", json={"items": [_relay_item(message_id, category)]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 0  # nothing could be filed — that is the shape

    # (ii) In the queue, and the verdict survived the trip into storage.
    review = (await client.get("/applications/review", headers=headers)).json()
    entry = next(i for i in review["items"] if i["message_id"] == message_id)
    assert entry["suggested_category"] == category
    row = await _stored_email(message_id)
    assert row is not None
    from jobtracker.database.models import EmailCategory

    assert row.classified_as == EmailCategory.NEEDS_REVIEW  # commitment: still none
    assert row.suggested_category == EmailCategory(category)  # proposal: recorded

    # (iii) Committing it reaches the board at the right stage.
    resp2 = await client.post(
        f"/applications/review/{message_id}/classify",
        json={"category": category, "company": "Relay Employer"},
        headers=headers,
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["needs_employer"] is False
    assert resp2.json()["application_id"] is not None

    listing = (await client.get("/applications", headers=headers)).json()
    filed = next(a for a in listing["applications"] if a["company"] == "Relay Employer")
    assert filed["status"] == CATEGORY_TO_EXPECTED_STATUS[category]


async def test_a_parked_row_gains_its_suggestion_on_the_next_sync(
    client: AsyncClient,
) -> None:
    """Backfill is automatic for un-settled rows, and stops at settled ones.

    ``_persist_message_refs`` re-writes an existing un-settled row on every
    re-scan, so the rows already parked in production pick their suggestion up
    on the next sync that covers them — no data migration, no backfill script.
    That was an inference from the code until this test; it is now a fact.

    A settled row is protected twice over, and deliberately so: the additive
    path filters reviewed/linked messages out before it builds any refs, and
    ``_persist_message_refs`` re-checks ``user_corrected or is_reviewed`` before
    writing. Both are exercised here by re-syncing the same message.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory

    headers = {"Authorization": f"Bearer {_token_for(USER)}"}
    parked = _relay_item("relay-backfill", "rejection")
    settled = _relay_item("relay-settled", "rejection")
    await client.post("/gmail/sync", json={"items": [parked, settled]}, headers=headers)

    # Reproduce the production state exactly: rows written before the column
    # existed hold NULL. One stays parked; the other is settled by a human.
    async with get_session() as session:
        for message_id in ("relay-backfill", "relay-settled"):
            row = (
                await session.exec(
                    sm_select(Email).where(Email.message_id == message_id)
                )
            ).first()
            assert row is not None
            row.suggested_category = None
            if message_id == "relay-settled":
                row.is_reviewed = True
            session.add(row)
        await session.commit()

    # The next sync covers both messages again.
    resp = await client.post(
        "/gmail/sync", json={"items": [parked, settled]}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    backfilled = await _stored_email("relay-backfill")
    assert backfilled.suggested_category == EmailCategory.REJECTION

    untouched = await _stored_email("relay-settled")
    assert untouched.suggested_category is None
    assert untouched.is_reviewed is True


async def test_a_suggestion_never_acts(cloud_app: Any) -> None:
    """The inversion canary: a proposal must not move an application. Ever.

    ``tracking/linker.py`` reads ``classified_as == NEEDS_REVIEW`` as "no
    committed category, do nothing". This pins that reading against every future
    change, from the one direction that matters: a row whose ``classified_as``
    is the typed null but whose ``suggested_category`` is a confident REJECTION.

    The sender is a real corporate domain on purpose. Everything else about this
    email is actionable — the company extracts, the confidence is high — so the
    ONLY thing standing between the suggestion and a terminal status change is
    the guard. Point it at an unresolvable relay instead and the test would pass
    for the wrong reason, on an extraction that fails anyway.

    What it prevents is not hypothetical: rejection is terminal and wins by
    recency, so acting on an unconfirmed guess here would reject a live
    application and freeze it against every later interview or offer.
    """

    from sqlmodel import func
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import (
        Application,
        Email,
        EmailCategory,
        EmailSource,
    )
    from jobtracker.tracking.linker import ApplicationLinker

    owner = uuid.UUID(USER)
    async with get_session() as session:
        email = Email(
            user_id=owner,
            application_id=None,
            source_account=EmailSource.GMAIL,
            message_id="canary-inversion",
            received_at=datetime(2026, 8, 1, 12, 0, 0),
            subject="Update on your application",
            sender_email="careers@stripe.com",
            sender_name="Stripe Recruiting",
            body_text="We are moving forward with other candidates.",
            classified_as=EmailCategory.NEEDS_REVIEW,  # the typed null
            suggested_category=EmailCategory.REJECTION,  # a proposal, nothing more
            classification_confidence=0.97,
            classification_method="rules",
        )
        session.add(email)
        await session.commit()
        await session.refresh(email)

    linker = ApplicationLinker()
    assert await linker.process_email(email) is None

    async with get_session() as session:
        applications = (
            await session.exec(sm_select(func.count()).select_from(Application))
        ).one()
        stored = (
            await session.exec(
                sm_select(Email).where(Email.message_id == "canary-inversion")
            )
        ).first()
    assert applications == 0  # wrote nothing
    assert stored is not None
    assert stored.application_id is None  # linked nothing
    assert stored.classified_as == EmailCategory.NEEDS_REVIEW  # committed nothing
