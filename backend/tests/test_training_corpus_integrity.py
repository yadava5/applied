"""The corpus may not contradict the mail it claims to have come from.

Why this file exists
--------------------

``training_data`` is what a SetFit retrain reads. Every row in it is supposed to
be a human saying "*this message* is a rejection / an interview / not job mail".
Two shapes in production say otherwise, and both were written by code that
looked reasonable:

- ``training_data`` id 2 labels a deleted email (``emails`` id 35) — an
  assessment-invite message — as ``rejection``. Nothing wrote that label about
  the message; a stage correction on the application it was linked to wrote it,
  reading the label off the new STAGE. The email row has since been deleted, so
  the label survives with no provenance at all and cannot be audited.
- ``training_data`` id 4 labels ``emails`` id 58 ``applied`` while that email is
  still stored ``needs_review`` — the corpus and the database disagree about the
  same message, and the card renders the stored side.

Both are silent. A model trained on the corpus inherits them, and no endpoint,
no log line and no test noticed. So the checks here are the invariant itself,
run over the real endpoints rather than over a fixture:

1. **No ghosts.** An example that names an email must name one that exists.
   ``training_data.email_id`` is a bare indexed integer — *not* a foreign key —
   so the database will not enforce this and cannot be made to without a
   migration.
2. **No contradiction.** Where the email exists and the user has settled it, the
   example's label is the email's stored classification. The one tolerated
   difference is the *pending* shape — an email still sitting in the review
   queue (``needs_review``, unlinked, un-reviewed) whose label was kept when the
   employer could not be named. That is an absence of a verdict, not a competing
   one. It is narrowed to genuinely-in-queue precisely so it cannot swallow
   email 58's shape, which is asserted as a positive control below.

Two things stop this from becoming a check that cannot fail. Every predicate has
a positive control that fabricates the violating row and asserts the checker
reports it (a checker nobody has seen go red is decoration). And the set of code
paths under test is DERIVED from the source by AST, not listed here: a new
function that writes a training example, or a new one that deletes ``Email``
rows, fails ``test_every_training_writer_is_exercised_here`` /
``test_every_email_deleter_is_exercised_here`` on the commit that introduces it.

Account deletion is deliberately not in that set: ``cloud/account.py`` purges
every tenant table including ``training_data``, which
``test_account_deletion_covers_every_table`` already derives from the schema.
"""

from __future__ import annotations

import ast
import importlib
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from jobtracker.database.models import (
    Email,
    EmailCategory,
    EmailSource,
    TrainingData,
)

JWT_SECRET = "corpus-integrity-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_A_UUID = uuid.UUID(USER_A)

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://api.example.test/auth/gmail/callback"
WEB_APP_URL = "https://web.example.test"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(USER_A)}"}


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Cloud app on the in-memory DB — the reload sequence the cloud tests use."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", WEB_APP_URL)

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
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


# =============================================================================
# The invariant
# =============================================================================


# A stored classification that asserts nothing about the message: no verdict has
# been recorded yet. Derived from the enum rather than spelled as a string, so
# renaming the member moves this with it.
_NO_VERDICT: frozenset[EmailCategory | None] = frozenset(
    {None, EmailCategory.NEEDS_REVIEW}
)


@dataclass(frozen=True)
class Violation:
    """One corpus row that disagrees with the database."""

    kind: str
    training_id: int | None
    email_id: int | None
    detail: str

    def __str__(self) -> str:  # pragma: no cover - only rendered on failure
        return (
            f"[{self.kind}] training_data id={self.training_id} "
            f"email_id={self.email_id}: {self.detail}"
        )


def _category_value(stored: object) -> str | None:
    """``classified_as`` as a plain string (the column round-trips as an enum)."""

    if stored is None:
        return None
    return stored.value if isinstance(stored, EmailCategory) else str(stored)


async def corpus_violations(session) -> list[Violation]:
    """Every way the corpus and the mail it came from can disagree.

    Deliberately reads whole tables: the invariant is about the corpus as a
    whole, and the whole corpus in a test is a handful of rows.
    """

    examples = list((await session.exec(select(TrainingData))).all())
    emails = {e.id: e for e in (await session.exec(select(Email))).all()}
    known_labels = {c.value for c in EmailCategory}

    violations: list[Violation] = []
    for row in examples:
        if row.label not in known_labels:
            violations.append(
                Violation(
                    "label-is-not-a-category",
                    row.id,
                    row.email_id,
                    f"label {row.label!r} is not one of {sorted(known_labels)}",
                )
            )

        if row.email_id is None:
            continue

        email = emails.get(row.email_id)
        if email is None:
            violations.append(
                Violation(
                    "ghost-email",
                    row.id,
                    row.email_id,
                    "names an email that does not exist — the label survives "
                    "with no provenance and cannot be audited",
                )
            )
            continue

        stored = _category_value(email.classified_as)
        if email.classified_as in _NO_VERDICT:
            still_in_the_queue = (
                email.application_id is None and not email.is_reviewed
            )
            if not still_in_the_queue:
                violations.append(
                    Violation(
                        "frozen-without-a-verdict",
                        row.id,
                        row.email_id,
                        f"labelled {row.label!r} but the email is stored "
                        f"{stored!r} while already settled "
                        f"(application_id={email.application_id}, "
                        f"is_reviewed={email.is_reviewed}) — the card will "
                        "render the stored side forever",
                    )
                )
        elif stored != row.label:
            violations.append(
                Violation(
                    "label-contradicts-the-email",
                    row.id,
                    row.email_id,
                    f"corpus says {row.label!r}, the email is stored {stored!r}",
                )
            )

    return violations


async def assert_corpus_is_coherent(session) -> list[TrainingData]:
    """Assert the invariant and return the corpus, so callers can prove it saw
    something. A green run over an empty corpus proves nothing."""

    violations = await corpus_violations(session)
    assert not violations, "the training corpus contradicts the mailbox:\n" + "\n".join(
        str(v) for v in violations
    )
    return list((await session.exec(select(TrainingData))).all())


# =============================================================================
# ... and it is a check that CAN fail (positive controls)
# =============================================================================


async def _fabricate_email(session, **overrides) -> Email:
    defaults = {
        "user_id": USER_A_UUID,
        "source_account": EmailSource.GMAIL,
        "message_id": f"fabricated-{time.time_ns()}",
        "received_at": datetime(2026, 6, 1, 12, 0),
        "subject": "Complete your assessment",
        "classified_as": EmailCategory.ASSESSMENT,
    }
    defaults.update(overrides)
    email = Email(**defaults)
    session.add(email)
    await session.commit()
    await session.refresh(email)
    return email


async def test_the_checker_catches_a_ghost_reference(client: AsyncClient) -> None:
    """``training_data`` id 2's shape: a label pointing at a deleted email."""

    from jobtracker.database import get_session

    async with get_session() as session:
        session.add(
            TrainingData(
                user_id=USER_A_UUID,
                email_id=987654,  # no such row
                label=EmailCategory.REJECTION.value,
                subject="Complete your assessment",
                source="user_correction",
            )
        )
        await session.commit()

        violations = await corpus_violations(session)
        assert [v.kind for v in violations] == ["ghost-email"]


async def test_the_checker_catches_a_label_that_contradicts_the_email(
    client: AsyncClient,
) -> None:
    """An assessment invite in the corpus as a rejection, with its email intact."""

    from jobtracker.database import get_session

    async with get_session() as session:
        email = await _fabricate_email(session)
        session.add(
            TrainingData(
                user_id=USER_A_UUID,
                email_id=email.id,
                label=EmailCategory.REJECTION.value,
                subject=email.subject,
                source="user_correction",
            )
        )
        await session.commit()

        violations = await corpus_violations(session)
        assert [v.kind for v in violations] == ["label-contradicts-the-email"]
        assert "rejection" in violations[0].detail
        assert "assessment" in violations[0].detail


async def test_the_checker_catches_a_settled_email_frozen_at_needs_review(
    client: AsyncClient,
) -> None:
    """Email 58's exact live shape — the reason the pending exemption is narrow.

    Stored ``needs_review``, but already settled: reviewed and linked to an
    application. A label about it is not "pending", it is frozen.
    """

    from jobtracker.database import get_session

    async with get_session() as session:
        email = await _fabricate_email(
            session,
            classified_as=EmailCategory.NEEDS_REVIEW,
            is_reviewed=True,
            application_id=None,
        )
        session.add(
            TrainingData(
                user_id=USER_A_UUID,
                email_id=email.id,
                label=EmailCategory.APPLIED.value,
                subject=email.subject,
                source="user_correction",
            )
        )
        await session.commit()

        violations = await corpus_violations(session)
        assert [v.kind for v in violations] == ["frozen-without-a-verdict"]


async def test_the_checker_is_quiet_on_a_message_still_in_the_queue(
    client: AsyncClient,
) -> None:
    """The one tolerated shape: the user's label kept while the item waits.

    Guards the exemption from being wrong in the other direction — if this goes
    red, the checker has started reporting the legitimate pending state and the
    endpoint's "keep the label, keep the item" behaviour is unassertable.
    """

    from jobtracker.database import get_session

    async with get_session() as session:
        email = await _fabricate_email(
            session,
            classified_as=EmailCategory.NEEDS_REVIEW,
            is_reviewed=False,
            application_id=None,
        )
        session.add(
            TrainingData(
                user_id=USER_A_UUID,
                email_id=email.id,
                label=EmailCategory.OFFER.value,
                subject=email.subject,
                source="user_correction",
            )
        )
        await session.commit()

        assert await corpus_violations(session) == []


# =============================================================================
# The paths under test are read out of the source, not listed
# =============================================================================


def _applications_source() -> str:
    from jobtracker.cloud import applications as applications_module

    return Path(applications_module.__file__).read_text(encoding="utf-8")


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _functions_where(predicate) -> set[str]:
    """Names of the module's functions containing a call matching ``predicate``."""

    tree = ast.parse(_applications_source())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and predicate(child):
                found.add(node.name)
    return found


def _training_writers() -> set[str]:
    return _functions_where(
        lambda call: _called_name(call) == "_add_training_example"
    ) - {"_add_training_example"}


def _email_deleters() -> set[str]:
    def deletes_email(call: ast.Call) -> bool:
        if _called_name(call) != "sa_delete":
            return False
        return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[
            0
        ].id == "Email"

    return _functions_where(deletes_email)


# The paths this file drives end-to-end. Not a description of the source — the
# tests below actually exercise each one — and the two tests that follow assert
# the source contains no others.
_TRAINING_WRITERS_EXERCISED = {"classify_review_item"}
_EMAIL_DELETERS_EXERCISED = {"_reset_review_queue", "delete_application"}


def test_the_ast_reader_finds_anything_at_all() -> None:
    """Guards the two guards below: a parse that finds nothing passes them both."""

    assert _training_writers(), (
        "no function in cloud/applications.py appears to call "
        "_add_training_example — the AST reader has stopped working and the "
        "coverage assertions below are vacuous"
    )
    assert _email_deleters(), (
        "no function in cloud/applications.py appears to delete Email rows — "
        "the AST reader has stopped working"
    )


def test_every_training_writer_is_exercised_here() -> None:
    """A new way to write a training example must be checked against the mail."""

    assert _training_writers() == _TRAINING_WRITERS_EXERCISED, (
        "the set of functions that write to `training_data` has changed. Every "
        "one of them must be driven end-to-end in this file and its corpus "
        "checked with `assert_corpus_is_coherent`, because nothing else in the "
        "system will notice a label that contradicts the mail it names.\n"
        f"  in the source: {sorted(_training_writers())}\n"
        f"  exercised here: {sorted(_TRAINING_WRITERS_EXERCISED)}"
    )


def test_every_email_deleter_is_exercised_here() -> None:
    """Deleting an email must not leave the corpus pointing at a ghost."""

    assert _email_deleters() == _EMAIL_DELETERS_EXERCISED, (
        "the set of functions that DELETE `emails` rows has changed. Each must "
        "be driven here, because `training_data.email_id` is not a foreign key "
        "and the database will not clean up after it.\n"
        f"  in the source: {sorted(_email_deleters())}\n"
        f"  exercised here: {sorted(_EMAIL_DELETERS_EXERCISED)}"
    )


def test_the_corpus_link_is_still_unenforced_by_the_schema() -> None:
    """Says out loud why an invariant needs a test instead of a constraint.

    If someone adds the foreign key (with a cascade or a SET NULL), this test
    fails and the ghost half of the invariant can move into the database, which
    is the better place for it.
    """

    from sqlmodel import SQLModel

    from jobtracker.database import models  # noqa: F401  (populates metadata)

    column = SQLModel.metadata.tables["training_data"].columns["email_id"]
    assert not column.foreign_keys, (
        "training_data.email_id now has a foreign key — the database can "
        "enforce the no-ghosts half of this invariant. Update this file and "
        "the migration together."
    )


# =============================================================================
# The flows
# =============================================================================


def _batch() -> list[dict]:
    """A scan shaped like the owner's: two real rows, two uncertain verdicts."""

    return [
        # REAL: a confirmation from Stripe → an `applied` row.
        {"message_id": "m-stripe", "category": "applied", "sender_email": "careers@stripe.com",
         "subject": "Thanks for applying to the Data Scientist role at Stripe",
         "sender_name": "Stripe", "confidence": 0.95, "thread_id": "th-stripe",
         "received_at": "2026-05-15T09:00:00+00:00"},
        # REAL: an interview relayed via Greenhouse naming Airbnb.
        {"message_id": "m-airbnb", "category": "interview",
         "sender_email": "no-reply@greenhouse-mail.io", "subject": "Interview with Airbnb",
         "sender_name": "Airbnb via Greenhouse", "confidence": 0.9, "thread_id": "th-airbnb",
         "received_at": "2026-05-20T09:00:00+00:00"},
        # A person on consumer webmail: confident, but no employer is nameable.
        {"message_id": "m-person", "category": "offer",
         "sender_email": "julee.johnson@gmail.com", "subject": "Re: our chat",
         "sender_name": "Julee Johnson", "confidence": 0.9,
         "received_at": "2026-06-04T10:00:00+00:00"},
    ]


async def _email(session, message_id: str) -> Email | None:
    return (
        await session.exec(select(Email).where(Email.message_id == message_id))
    ).first()


async def _sync(client: AsyncClient) -> dict[str, dict]:
    resp = await client.post("/gmail/sync", json={"items": _batch()}, headers=_headers())
    assert resp.status_code == 200, resp.text
    listing = (await client.get("/applications", headers=_headers())).json()
    return {a["company"]: a for a in listing["applications"]}


async def test_a_stage_correction_labels_no_message(client: AsyncClient) -> None:
    """The defect: the stage the user set became a label for every linked email.

    The user answered "what stage is this APPLICATION at?". That is not an
    answer to "what is this MESSAGE?", which is the only question a training
    example can record — so the correction settles the row and touches no mail.
    """

    from jobtracker.database import get_session

    board = await _sync(client)
    airbnb = board["Airbnb"]

    patch = await client.patch(
        f"/applications/{airbnb['id']}", json={"status": "rejected"}, headers=_headers()
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "rejected"
    assert patch.json()["source"] == "gmail_user"  # user-owned → still sticky

    async with get_session() as session:
        assert list((await session.exec(select(TrainingData))).all()) == [], (
            "a stage correction manufactured a per-message training label — "
            "this is how an assessment invite was taught to the classifier as "
            "a rejection (training_data id 2)"
        )
        email = await _email(session, "m-airbnb")
        assert email is not None
        # The message is still what the classifier said it was...
        assert email.classified_as == EmailCategory.INTERVIEW
        # ...and is NOT flagged as something a human judged, which would freeze
        # it against every future re-classification (`_persist_message_refs`).
        assert email.user_corrected is False
        assert email.is_reviewed is False
        assert await corpus_violations(session) == []

    # The half that must NOT regress: the stage stays the user's through a
    # re-sync whose mail still says `interviewing`.
    board_again = await _sync(client)
    assert board_again["Airbnb"]["status"] == "rejected"


async def test_marking_an_application_ghosted_does_not_teach_that_its_mail_is_noise(
    client: AsyncClient,
) -> None:
    """The most destructive case of the old mapping.

    ``WITHDRAWN``/``GHOSTED`` mapped to ``other`` — "not job mail" — so telling
    the board you never heard back taught the classifier that the genuine "we
    received your application" confirmation was noise.
    """

    from jobtracker.database import get_session

    board = await _sync(client)
    stripe = board["Stripe"]

    patch = await client.patch(
        f"/applications/{stripe['id']}", json={"status": "ghosted"}, headers=_headers()
    )
    assert patch.status_code == 200, patch.text

    async with get_session() as session:
        labels = [t.label for t in (await session.exec(select(TrainingData))).all()]
        assert "other" not in labels, (
            "a real application confirmation was taught to the classifier as "
            f"not-job-mail: {labels}"
        )
        email = await _email(session, "m-stripe")
        assert email is not None and email.classified_as == EmailCategory.APPLIED
        assert await corpus_violations(session) == []


async def test_dismissing_a_row_labels_no_message(client: AsyncClient) -> None:
    """Same rule, the other whole-row action.

    "This is not an application" is a statement about the ROW. Turning it into a
    per-message ``other`` label leaves the corpus saying one thing and the
    stored classification another — and the row is restorable, so freezing its
    mail to make them agree would be the worse of the two.
    """

    from jobtracker.database import get_session

    board = await _sync(client)
    stripe = board["Stripe"]

    resp = await client.post(
        f"/applications/{stripe['id']}/dismiss", headers=_headers()
    )
    assert resp.status_code == 200 and resp.json()["dismissed"] is True

    listing = (await client.get("/applications", headers=_headers())).json()
    assert "Stripe" not in {a["company"] for a in listing["applications"]}

    async with get_session() as session:
        assert list((await session.exec(select(TrainingData))).all()) == []
        email = await _email(session, "m-stripe")
        assert email is not None and email.classified_as == EmailCategory.APPLIED
        assert await corpus_violations(session) == []

    # Restorable and unchanged, which is why its mail was never relabelled.
    restored = await client.post(
        f"/applications/{stripe['id']}/restore", headers=_headers()
    )
    assert restored.status_code == 200
    async with get_session() as session:
        email = await _email(session, "m-stripe")
        assert email is not None and email.classified_as == EmailCategory.APPLIED
        assert await corpus_violations(session) == []


async def test_classifying_a_message_labels_that_message_and_agrees_with_it(
    client: AsyncClient,
) -> None:
    """The one path that may write a label — and the corpus it produces agrees.

    Also the vacuity guard for this file: it asserts the corpus under check is
    non-empty and that at least one example names a live, decided email.
    """

    from jobtracker.database import get_session

    await _sync(client)

    resp = await client.post(
        "/applications/review/m-person/classify",
        json={"category": "offer", "company": "Wayne Enterprises"},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] is not None

    async with get_session() as session:
        corpus = await assert_corpus_is_coherent(session)
        assert corpus, "nothing was written — the check below would be vacuous"

        email = await _email(session, "m-person")
        assert email is not None
        assert email.classified_as == EmailCategory.OFFER
        assert email.user_corrected is True

        named = [t for t in corpus if t.email_id == email.id]
        assert len(named) == 1
        assert named[0].label == EmailCategory.OFFER.value


async def test_a_label_kept_for_an_unfilable_message_stays_pending(
    client: AsyncClient,
) -> None:
    """The needs-employer branch keeps the label AND the queue item.

    The corpus row is legitimately ahead of the stored classification here,
    because there is no stored classification yet — the item is still waiting
    for the answer the endpoint asked for. Completing it settles both.
    """

    from jobtracker.database import get_session

    await _sync(client)

    resp = await client.post(
        "/applications/review/m-person/classify",
        json={"category": "offer"},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["needs_employer"] is True

    async with get_session() as session:
        corpus = await assert_corpus_is_coherent(session)
        assert [t.label for t in corpus] == [EmailCategory.OFFER.value]
        email = await _email(session, "m-person")
        assert email is not None
        assert email.classified_as == EmailCategory.NEEDS_REVIEW
        assert email.application_id is None and email.is_reviewed is False

    resp2 = await client.post(
        "/applications/review/m-person/classify",
        json={"category": "offer", "company": "Wayne Enterprises"},
        headers=_headers(),
    )
    assert resp2.status_code == 200, resp2.text

    async with get_session() as session:
        await assert_corpus_is_coherent(session)
        email = await _email(session, "m-person")
        assert email is not None and email.classified_as == EmailCategory.OFFER


async def test_deleting_an_application_leaves_no_example_pointing_at_a_ghost(
    client: AsyncClient,
) -> None:
    """``DELETE /applications/{id}`` hard-deletes the mail. The corpus outlives it.

    The example itself is kept — it carries the subject and body it was labelled
    from, and destroying a human's correction is not this endpoint's decision —
    but it must stop claiming a provenance it no longer has.
    """

    from jobtracker.database import get_session

    await _sync(client)
    classify = await client.post(
        "/applications/review/m-person/classify",
        json={"category": "offer", "company": "Wayne Enterprises"},
        headers=_headers(),
    )
    application_id = classify.json()["application_id"]

    async with get_session() as session:
        email = await _email(session, "m-person")
        assert email is not None
        corpus = list((await session.exec(select(TrainingData))).all())
        assert [t.email_id for t in corpus] == [email.id]

    deleted = await client.delete(
        f"/applications/{application_id}", headers=_headers()
    )
    assert deleted.status_code == 200, deleted.text

    async with get_session() as session:
        assert await _email(session, "m-person") is None
        corpus = await assert_corpus_is_coherent(session)
        assert len(corpus) == 1, "the user's label was destroyed with the row"
        assert corpus[0].email_id is None
        assert corpus[0].label == EmailCategory.OFFER.value
        assert corpus[0].subject  # the labelled text is still auditable


async def test_a_rebuild_clearing_the_review_queue_leaves_no_ghost(
    client: AsyncClient,
) -> None:
    """The second deleter: the re-sync's queue reset.

    A message whose label was kept pending is unlinked and un-reviewed — exactly
    the rows ``_reset_review_queue`` deletes when a rebuild re-reads them.
    """

    from jobtracker.cloud import applications as apps
    from jobtracker.cloud import pipeline
    from jobtracker.database import get_session

    await _sync(client)
    resp = await client.post(
        "/applications/review/m-person/classify",
        json={"category": "offer"},
        headers=_headers(),
    )
    assert resp.json()["needs_employer"] is True

    scanned = [
        pipeline.MessageRef(
            message_id="m-person",
            thread_id=None,
            subject="Re: our chat",
            sender_email="julee.johnson@gmail.com",
            sender_name="Julee Johnson",
            received_at=datetime(2026, 6, 4, 10, 0),
            category="other",
            confidence=0.9,
            snippet="",
        )
    ]
    coverage = apps.ScanCoverage.from_items(scanned)

    async with get_session() as session:
        await apps._reset_review_queue(session, USER_A_UUID, coverage)
        await session.commit()

        assert await _email(session, "m-person") is None
        corpus = await assert_corpus_is_coherent(session)
        assert len(corpus) == 1 and corpus[0].email_id is None
