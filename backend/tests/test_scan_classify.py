"""Correcting a verdict the LIVE SCAN showed — mail this database never stored.

Why this file exists
--------------------

``/inbox?view=scan`` reads Gmail directly and persists nothing. Its rows are
verdicts about messages that have no ``emails`` row, so
``POST /applications/review/{message_id}/classify`` — which selects on
``(user_id, message_id)`` — answered **404** for every one of them. The view was
read-only in the strongest sense: the product could show you a verdict it had
no way to accept a correction for.

"File it first, then correct it" is not a workaround. ``collect_review_items``
keeps only ``needs_review`` mail and lifecycle mail at or above the 0.70 review
floor, so the owner's case — an assessment email the classifier called ``other``
at 0.0 confidence — is dropped by ``POST /gmail/sync`` and never becomes a row.
That message was uncorrectable by construction.

So the classify endpoint now accepts the message's own metadata
(``ScannedMessageIn``) and stores it before applying the correction. The tests
below drive the real endpoint over a real (in-memory) database.

The ORDERING test is the one to keep. The ``needs_employer`` branch commits and
returns without filing anything, and the whole point of it is that the caller
re-sends the same classification with a company. If the message were minted
*after* that early return, the first half of the round trip would accept the
request and the second half would 404 — a dead end reachable in one click, since
``assessment`` maps to ``INTERVIEWING`` and therefore always needs an employer.

Every assertion here was checked by breaking the thing it covers; the mutation
and its result are recorded on each test.
"""

from __future__ import annotations

import importlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "scan-classify-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "aaaaaaaa-1111-2222-3333-444444444444"
STRANGER = "bbbbbbbb-1111-2222-3333-444444444444"

# The message in the owner's screenshot: plainly an assessment, classified
# ``other``, and not even confidently. Below the review floor, so no sync would
# ever have stored it.
SCAN_MESSAGE_ID = "scan-msg-assessment"
SCAN_MESSAGE = {
    "sender_email": "no-reply@harboranalytics.test",
    "received_at": "2026-08-11T09:30:00Z",
    "subject": "Your HackerRank assessment for Software Engineer II",
    "sender_name": "Harbor Analytics",
    "category": "other",
    "confidence": 0.0,
    "method": "rules",
}

# Sent from a personal address: nothing in it names an employer, so the backend
# must answer ``needs_employer`` rather than inventing a company.
ANONYMOUS_MESSAGE_ID = "scan-msg-anonymous"
ANONYMOUS_MESSAGE = {
    "sender_email": "priya.recruiter@gmail.com",
    "received_at": "2026-08-11T11:00:00Z",
    "subject": "Next steps + take-home details",
    "sender_name": "Priya",
    "category": "needs_review",
    "confidence": 0.58,
    "method": "setfit",
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
    """The cloud app over the in-memory SQLite test DB (see test_mail_listing)."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

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


async def _classify(
    cloud_app,
    message_id: str,
    body: dict[str, Any],
    user: str = OWNER,
) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        return await client.post(
            f"/applications/review/{message_id}/classify",
            json=body,
            headers={"Authorization": f"Bearer {_token_for(user)}"},
        )


async def _mail(cloud_app, user: str = OWNER) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        return await client.get(
            "/applications/mail",
            params={"page_size": 50},
            headers={"Authorization": f"Bearer {_token_for(user)}"},
        )


async def _stored_email(message_id: str, user: str = OWNER):
    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Email

    async with get_session() as session:
        return (
            await session.exec(
                select(Email).where(
                    Email.user_id == uuid.UUID(user), Email.message_id == message_id
                )
            )
        ).first()


# =============================================================================
# The premise: without the new payload this is still a 404
# =============================================================================


async def test_an_unstored_message_is_still_a_404_without_its_metadata(cloud_app):
    """The old contract is unchanged for callers that send no ``message``.

    This is the state the whole scan view was in. It is asserted rather than
    assumed, because it is what makes the next test's 200 mean something.

    Mutation: making the mint unconditional → fails (200, not 404).
    """

    res = await _classify(cloud_app, SCAN_MESSAGE_ID, {"category": "assessment"})

    assert res.status_code == 404, res.text
    assert await _stored_email(SCAN_MESSAGE_ID) is None


# =============================================================================
# Persist-then-classify
# =============================================================================


async def test_a_scanned_message_is_stored_and_then_corrected(cloud_app):
    """The complaint, end to end: an assessment the classifier called ``other``.

    The message reaches the store, the user's category is the stored verdict,
    the row is marked as theirs, and an application is filed at the stage
    ``assessment`` maps to — which, since 2026-08-12, is ``assessment`` itself
    rather than ``interviewing`` (see CATEGORY_TO_STATUS). This assertion is the
    end-to-end proof of that change: correcting a mail to ``assessment`` now
    files a row that SAYS assessment.

    Mutation: dropping ``data.message`` in the endpoint → fails (404).
    """

    res = await _classify(
        cloud_app,
        SCAN_MESSAGE_ID,
        {"category": "assessment", "message": SCAN_MESSAGE},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["classified_as"] == "assessment"
    assert body["needs_employer"] is False
    assert isinstance(body["application_id"], int)

    stored = await _stored_email(SCAN_MESSAGE_ID)
    assert stored is not None, "the correction must have stored the message"
    assert stored.classified_as.value == "assessment"
    assert stored.is_reviewed is True
    assert stored.user_corrected is True
    assert stored.subject == SCAN_MESSAGE["subject"]
    assert stored.sender_email == SCAN_MESSAGE["sender_email"]
    assert stored.application_id == body["application_id"]

    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import Application, ApplicationStatus

    async with get_session() as session:
        app = (
            await session.exec(select(Application).where(Application.id == body["application_id"]))
        ).first()
    assert app is not None
    assert app.status == ApplicationStatus.ASSESSMENT
    assert app.user_id == uuid.UUID(OWNER)


async def test_the_stored_message_is_reachable_afterwards(cloud_app):
    """A corrected scan row joins the filed ledger, so it stays correctable.

    A correction that stored nothing reachable would be the same dead end in a
    different place: the filed view is the only surface that lists a verdict
    once it has been reviewed.

    Mutation: minting the row without committing → fails (0 messages).
    """

    await _classify(
        cloud_app, SCAN_MESSAGE_ID, {"category": "assessment", "message": SCAN_MESSAGE}
    )

    res = await _mail(cloud_app)
    assert res.status_code == 200, res.text
    body = res.json()
    listed = {m["message_id"]: m for m in body["messages"]}
    assert SCAN_MESSAGE_ID in listed
    assert listed[SCAN_MESSAGE_ID]["category"] == "assessment"
    assert listed[SCAN_MESSAGE_ID]["user_corrected"] is True
    assert body["category_counts"].get("assessment") == 1


async def test_a_second_correction_of_the_same_message_updates_in_place(cloud_app):
    """The stored row is corrected in place; the payload never re-mints.

    Otherwise the ``(user_id, message_id)`` unique index would make the second
    correction a 500, and the reader would have one chance to be right.

    Mutation: minting whenever ``scanned`` is present → fails (IntegrityError).
    """

    first = await _classify(
        cloud_app, SCAN_MESSAGE_ID, {"category": "assessment", "message": SCAN_MESSAGE}
    )
    assert first.status_code == 200, first.text

    second = await _classify(
        cloud_app, SCAN_MESSAGE_ID, {"category": "other", "message": SCAN_MESSAGE}
    )
    assert second.status_code == 200, second.text
    assert second.json()["classified_as"] == "other"

    res = await _mail(cloud_app)
    ids = [m["message_id"] for m in res.json()["messages"]]
    assert ids.count(SCAN_MESSAGE_ID) == 1, "one message, one row"
    stored = await _stored_email(SCAN_MESSAGE_ID)
    assert stored.classified_as.value == "other"


# =============================================================================
# The ordering that makes the round trip completable
# =============================================================================


async def test_needs_employer_still_stores_the_message_so_the_retry_can_file(cloud_app):
    """The ``needs_employer`` round trip must be completable from a scan row.

    First POST: a lifecycle category whose employer cannot be read from the mail
    (a personal address). The backend answers 200 with ``needs_employer: true``
    and files nothing — but it HAS stored the message, so the second POST, which
    names the company, finds it and files.

    Mutation: minting after the ``needs_employer`` early return → fails (the
    retry 404s, and the first response's promise is unkeepable).
    """

    first = await _classify(
        cloud_app,
        ANONYMOUS_MESSAGE_ID,
        {"category": "assessment", "message": ANONYMOUS_MESSAGE},
    )

    assert first.status_code == 200, first.text
    assert first.json()["needs_employer"] is True
    assert first.json()["application_id"] is None

    # Stored, and left honestly in the un-reviewed state the response describes:
    # the scan's own verdict, not the category the user asked for.
    held = await _stored_email(ANONYMOUS_MESSAGE_ID)
    assert held is not None, "the message must be on file before the retry"
    assert held.is_reviewed is False
    assert held.classified_as.value == "needs_review"

    second = await _classify(
        cloud_app,
        ANONYMOUS_MESSAGE_ID,
        {
            "category": "assessment",
            "company": "Cedar Labs",
            "message": ANONYMOUS_MESSAGE,
        },
    )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["needs_employer"] is False
    assert isinstance(body["application_id"], int)

    filed = await _stored_email(ANONYMOUS_MESSAGE_ID)
    assert filed.is_reviewed is True
    assert filed.classified_as.value == "assessment"
    assert filed.application_id == body["application_id"]


# =============================================================================
# Ownership and refusals
# =============================================================================


async def test_a_stored_message_is_scoped_to_the_caller(cloud_app):
    """A minted row belongs to the JWT's user and to nobody else.

    The message id comes from the client, so the only thing standing between
    this and cross-account writes is that ``user_id`` is taken from the token.

    Mutation: minting with a ``user_id`` from the request → fails (the stranger
    sees the owner's message).
    """

    await _classify(
        cloud_app, SCAN_MESSAGE_ID, {"category": "assessment", "message": SCAN_MESSAGE}
    )

    assert await _stored_email(SCAN_MESSAGE_ID, user=STRANGER) is None
    stranger_mail = await _mail(cloud_app, user=STRANGER)
    assert stranger_mail.status_code == 200, stranger_mail.text
    assert stranger_mail.json()["messages"] == []

    # And the same id classified by the stranger is THEIR row, not a collision.
    res = await _classify(
        cloud_app,
        SCAN_MESSAGE_ID,
        {"category": "assessment", "message": SCAN_MESSAGE},
        user=STRANGER,
    )
    assert res.status_code == 200, res.text
    mine = await _stored_email(SCAN_MESSAGE_ID, user=OWNER)
    theirs = await _stored_email(SCAN_MESSAGE_ID, user=STRANGER)
    assert mine.id != theirs.id


async def test_a_message_with_no_receive_time_is_refused(cloud_app):
    """``Email.received_at`` is NOT NULL and is never fabricated.

    The sync skips undated mail rather than inventing a receive time; this path
    must refuse it for the same reason, so the client can say honestly that the
    row cannot be corrected instead of the store quietly dating it "now".

    Mutation: defaulting ``received_at`` to ``utcnow()`` → fails (200, and a
    stored row claiming a receive time nobody read).
    """

    undated = {k: v for k, v in SCAN_MESSAGE.items() if k != "received_at"}
    res = await _classify(
        cloud_app, "scan-msg-undated", {"category": "assessment", "message": undated}
    )

    assert res.status_code == 422, res.text
    assert await _stored_email("scan-msg-undated") is None


async def test_not_job_related_stores_the_message_without_filing_a_row(cloud_app):
    """"Not job related" is a real answer: it stores + trains, and files nothing.

    The training example is the point — it is how the classifier learns that a
    message it called ``interview`` was noise. Storing the row is what makes the
    decision visible and reversible afterwards.

    Mutation: skipping the mint for non-lifecycle categories → fails (nothing
    stored, and the correction leaves no trace).
    """

    res = await _classify(
        cloud_app, "scan-msg-noise", {"category": "other", "message": SCAN_MESSAGE}
    )

    assert res.status_code == 200, res.text
    assert res.json()["application_id"] is None
    assert res.json()["needs_employer"] is False

    stored = await _stored_email("scan-msg-noise")
    assert stored is not None
    assert stored.classified_as.value == "other"
    assert stored.application_id is None

    from sqlmodel import select

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import TrainingData

    async with get_session() as session:
        examples = (
            await session.exec(
                select(TrainingData).where(TrainingData.user_id == uuid.UUID(OWNER))
            )
        ).all()
    assert [e.label for e in examples] == ["other"]
