"""A human decision carries no machine confidence.

Why this file exists
--------------------

``POST /applications/review/{message_id}/classify`` wrote ``classified_as``,
``is_reviewed`` and ``user_corrected`` and left ``classification_confidence``
and ``classification_method`` exactly as the classifier had set them. So a row
the reader relabelled kept the confidence of the verdict it had just replaced,
and the Inbox drew the two side by side:

    rejection · 75% · corrected by you

That is the owner's real email 114 (Palantir). The 75% was the classifier's
certainty, and every reader that draws it — ``GateMeter``, the percentage
column, the review queue — presents a confidence figure as a claim about the
verdict standing next to it. Standing next to the human's verdict, it asserts a
probability nobody computed about a decision nobody scored. Same family as
``classified_as`` being a commitment: a stored value that forges a decision
which was never made.

The fix is NULL, not 1.0. 1.0 is the same forgery at a different number — a
claim of total certainty on the classifier's own 0-1 scale, drawn by the
classifier's own meter. NULL is what is true, and every reader already treats
the column as optional.

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

JWT_SECRET = "corrected-confidence-test-jwt-secret-at-least-32-bytes-hs256"
OWNER = "aaaaaaaa-1111-2222-3333-444444444444"

# Email 114 on the owner's account, byte for byte, as the classifier left it
# BEFORE the correction: Lever's Palantir rejection, verdict ``applied``, and
# the 0.75 the Inbox then showed underneath the word "rejection".
#
# The stored verdict is deliberately the WRONG one here. What this file is about
# is that a corrected row must not carry the number belonging to the verdict it
# replaced, and that is only visible when the two disagree.
PALANTIR_MESSAGE_ID = "corrected-msg-palantir"
PALANTIR_THREAD_ID = "corrected-thread-palantir"
PALANTIR_SUBJECT = (
    "Thank you from Palantir Technologies - Ayush Yadav - Software Engineer, New Grad"
)
PALANTIR_SENDER = "no-reply@hire.lever.co"
PALANTIR_SNIPPET = (
    "Dear Ayush, Thank you for your interest in Palantir. After careful "
    "consideration, we regret to inform you that we will not be proceeding "
    "with your candidacy for this role at this time. Please note that"
)
MACHINE_CONFIDENCE = 0.75


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


async def _seed_machine_verdict(*, message_id: str, thread_id: str | None) -> None:
    """Store the row as a SYNC would have: a machine verdict, uncorrected."""

    from datetime import datetime, timezone

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import (
        ClassificationMethod,
        Email,
        EmailCategory,
        EmailSource,
    )

    async with get_session() as session:
        session.add(
            Email(
                user_id=uuid.UUID(OWNER),
                source_account=EmailSource.GMAIL,
                message_id=message_id,
                thread_id=thread_id,
                subject=PALANTIR_SUBJECT,
                sender_email=PALANTIR_SENDER,
                sender_name="Palantir Technologies",
                body_snippet=PALANTIR_SNIPPET,
                received_at=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
                classified_as=EmailCategory.APPLIED,
                classification_confidence=MACHINE_CONFIDENCE,
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


async def _classify(cloud_app, message_id: str, category: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        return await client.post(
            f"/applications/review/{message_id}/classify",
            json={"category": category, "company": "Palantir"},
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )


# =============================================================================
# The premise: the seeded row really does carry the machine's number
# =============================================================================


async def test_the_seeded_row_carries_the_machines_number(cloud_app):
    """Guards the fixture, not the code.

    Every other test here asserts a number is ABSENT. That assertion passes
    trivially against a row that never had one, which would make this whole file
    green while proving nothing. So: prove the number is there first.
    """

    await _seed_machine_verdict(message_id=PALANTIR_MESSAGE_ID, thread_id=None)

    stored = await _stored(PALANTIR_MESSAGE_ID)
    assert stored is not None
    assert stored.classification_confidence == pytest.approx(MACHINE_CONFIDENCE)
    assert stored.classification_method == "rules"
    assert stored.user_corrected is False


# =============================================================================
# The fix
# =============================================================================


async def test_a_correction_clears_the_machines_confidence(cloud_app):
    """The row the owner saw as "rejection · 75% · corrected by you".

    Mutation: removing the two new lines from the endpoint (i.e. restoring the
    old behaviour) → fails, ``classification_confidence`` is still 0.75.
    """

    await _seed_machine_verdict(message_id=PALANTIR_MESSAGE_ID, thread_id=None)

    res = await _classify(cloud_app, PALANTIR_MESSAGE_ID, "rejection")
    assert res.status_code == 200, res.text

    stored = await _stored(PALANTIR_MESSAGE_ID)
    assert stored.classified_as.value == "rejection"
    assert stored.user_corrected is True
    # The point of the file.
    assert stored.classification_confidence is None
    assert stored.classification_method == "user"


async def test_the_correction_does_not_write_1_0_instead(cloud_app):
    """NULL, not "certain".

    Writing 1.0 would satisfy "the 75% is gone" while re-asserting the same kind
    of claim — total certainty, on the classifier's scale, drawn by the
    classifier's meter — behind a label that was never scored at all. This test
    is what stops the fix drifting there, and it is a separate test from the one
    above because the two failures are different mistakes.

    Mutation: ``email.classification_confidence = 1.0`` → fails.
    """

    await _seed_machine_verdict(message_id=PALANTIR_MESSAGE_ID, thread_id=None)
    await _classify(cloud_app, PALANTIR_MESSAGE_ID, "rejection")

    stored = await _stored(PALANTIR_MESSAGE_ID)
    assert stored.classification_confidence is None, (
        "a human decision carries no probability — not 1.0, not 0.0, none"
    )


async def test_the_mail_listing_reports_no_confidence_for_a_corrected_row(cloud_app):
    """The API surface the Inbox and the filed ledger both read.

    Fixing the column and leaving the response to substitute a number would move
    the forgery one layer out, which is exactly how this defect family survives.

    Mutation: ``confidence=e.classification_confidence or 0.0`` at the
    ``MailMessageResponse`` site → fails (0.0, which renders as a confident 0%).
    """

    await _seed_machine_verdict(message_id=PALANTIR_MESSAGE_ID, thread_id=None)
    await _classify(cloud_app, PALANTIR_MESSAGE_ID, "rejection")

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get(
            "/applications/mail",
            params={"page_size": 50},
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )

    assert res.status_code == 200, res.text
    listed = {m["message_id"]: m for m in res.json()["messages"]}
    row = listed[PALANTIR_MESSAGE_ID]
    assert row["category"] == "rejection"
    assert row["user_corrected"] is True
    assert row["confidence"] is None
    assert row["method"] == "user"


# =============================================================================
# The thread siblings, which inherit the label without being read
# =============================================================================


async def test_a_settled_thread_sibling_KEEPS_the_machines_number_for_now(cloud_app):
    """Pins a defect this PR deliberately does NOT fix, and why.

    ``_settle_thread_siblings`` writes the human's category onto the other
    messages of the thread, so a sibling ends up holding the human's category
    with the classifier's confidence in the verdict that category replaced —
    the same forgery as the corrected row, one step removed.

    Nulling it here was written, measured, and REVERTED. A sibling keeps
    ``user_corrected = False`` by design (the flag records whether a human read
    THAT message, and nobody did), and that flag is exactly what makes the null
    safe on the corrected row. Both
    ``generate_ml_monitoring_report._count_needs_review`` and
    ``weekly_labeling_workflow`` select
    ``user_corrected.is_(False) AND (confidence IS NULL OR < threshold)`` and
    NEITHER filters ``is_reviewed`` — so a nulled sibling is counted as needing
    review, and the labeling query's ``case(confidence.is_(None), -1.0)``
    ordering puts it at the FRONT of the candidate list. A message whose label
    the human already settled would lead the weekly queue.

    Verified against a migrated database, not reasoned about: seeding one
    sibling in each state and running the monitoring predicate returned only
    the nulled one.

    Fixing it properly means teaching those two queries about ``is_reviewed``,
    which changes what the monitoring numbers mean and needs its own before/after
    counts. This test exists so the current state is a recorded decision rather
    than an oversight, and so that whoever does fix it sees this note first.
    """

    await _seed_machine_verdict(
        message_id=PALANTIR_MESSAGE_ID, thread_id=PALANTIR_THREAD_ID
    )
    await _seed_machine_verdict(
        message_id="corrected-msg-palantir-sibling", thread_id=PALANTIR_THREAD_ID
    )

    res = await _classify(cloud_app, PALANTIR_MESSAGE_ID, "rejection")
    assert res.status_code == 200, res.text

    sibling = await _stored("corrected-msg-palantir-sibling")
    assert sibling.is_reviewed is True
    assert sibling.classified_as.value == "rejection"
    # Not the human's own decision — they read one message, not this one.
    assert sibling.user_corrected is False
    # The known-imperfect part, pinned so a change to it is deliberate.
    assert sibling.classification_confidence == pytest.approx(MACHINE_CONFIDENCE)
    assert sibling.classification_method == "rules"


# =============================================================================
# What the change must NOT do
# =============================================================================


async def test_an_uncorrected_row_keeps_its_confidence(cloud_app):
    """The classifier's own verdicts are untouched.

    A change that nulled the column more broadly would empty the meters across
    the whole ledger and silently drain the review queue, which selects on
    ``classification_confidence < AUTO_FILE_GATE``.

    Mutation: nulling the column unconditionally at the persist site → fails.
    """

    await _seed_machine_verdict(message_id="corrected-msg-untouched", thread_id=None)

    async with AsyncClient(
        transport=ASGITransport(app=cloud_app), base_url="http://test"
    ) as client:
        res = await client.get(
            "/applications/mail",
            params={"page_size": 50},
            headers={"Authorization": f"Bearer {_token_for(OWNER)}"},
        )

    listed = {m["message_id"]: m for m in res.json()["messages"]}
    row = listed["corrected-msg-untouched"]
    assert row["confidence"] == pytest.approx(MACHINE_CONFIDENCE)
    assert row["method"] == "rules"
