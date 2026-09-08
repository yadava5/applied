"""The two arms of the settled test that nothing covered: reviewed, and whose.

A COMPANION TO ``test_settled_filter_drops_an_uncertain_update.py``, NOT A
SECOND COPY OF IT. That module already measures #630's class — an uncertain
update refused because its ``review_dedup_key`` matches a message filed on a
live card — along with the rebuild path's disagreement and the refusal log. It
does not touch either arm below, and both were asserted by nothing:

  * ``is_reviewed``. The settled query is
    ``or_(Email.is_reviewed == True, _filed_on_an_application_that_answers(...))``
    and every existing fixture settles rows through the second arm. Nothing on
    the sync path writes ``is_reviewed`` — only ``classify_review_item`` and
    ``_settle_thread_siblings`` do — so a harness that answers the queue once,
    after the last batch, leaves the first arm dead. It is also the ONLY arm
    where the #596 spelling and the current one disagree in a way this corpus
    can reach: ``purged`` is 0, so no row is ever linked to a resync-dismissed
    card.
  * WHOSE MAILBOX. The independent corpus generated a single user until #614,
    so every ``user_id`` clause in the settled test was satisfied by
    construction: removing one moved no number. Two mailboxes here share a
    thread id ON PURPOSE — give them separate ones and these tests pass whether
    or not the scoping exists, which is the blind control in a new costume.

Runs in under a second against in-memory SQLite, so a change that breaks either
arm fails here rather than two minutes into a corpus replay.

Nothing here is real mail: invented employers, invented threads, invented
requisition numbers. See ``docs/TEST_DATA_POLICY.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import (
    Application,
    Email,
    classify_review_item,
    employers_with_several_applications,
    sync_gmail_pipeline_additive,
    threads_naming_one_application,
)
from jobtracker.database.models import EmailCategory
from tests.corpus_independent.generate import ATS_SENDERS

USER = uuid.UUID("00000000-0000-0000-0000-00000000c0de")
OTHER = uuid.UUID("00000000-0000-0000-0000-0000000b0b0b")
EPOCH = datetime(2026, 1, 1, 9, 0)

DISPLAY = "Alderbourne Labs"
# THE SENDER IS IMPORTED, not written out here, and it has to be a REAL relay
# domain. The `ats_floor` route below exists only because `pipeline` recognises
# the sender as a known ATS (#166): measured, the same two messages off
# `no-reply@…greenhouse-mail.io` classify 0.95 / 0.50-into-the-queue and off a
# `.example` twin classify 0.90 / 0.50-and-filed, so a reserved domain does not
# merely publish less — it silently removes the mechanism this file tests.
#
# Taking it from the corpus keeps that address published in exactly one place
# (`scripts/check_test_data.py` counts literals, and this file adds none) and
# gives "a known ATS relay" one definition rather than two that can drift.
ATS = ATS_SENDERS[0]

#: An acknowledgement that names NO job. `applied` at 0.95, so it auto-files;
#: `role_from_message` finds nothing, so its dedup key is ``(thread, None)``.
ACK = (
    f"{DISPLAY} | Application Received",
    f"Hi Ayush, Thank you for applying to {DISPLAY}. We have received your "
    f"submission and our team will review it shortly.",
)
#: Uncertain, names no job. `other` at 0.50, floored into the queue by
#: `references_an_application` because a known ATS relayed it. Same key.
UPDATE = (
    f"Your {DISPLAY} application",
    "Hi Ayush, We have an update to share about your application. Please "
    "look out for a further message from the hiring team.",
)


def _item(mid: str, thread: str, subject: str, body: str, day: int):
    from jobtracker.classifier.rules import RulesClassifier
    from jobtracker.cloud.gmail_client import normalise_body_text

    delivered = normalise_body_text(body)
    # THE REAL CLASSIFIER, never a hand-set confidence. A fixture that dictates
    # its own category cannot say whether any TEXT reaches the filter, and the
    # first draft of this file did exactly that.
    verdict = RulesClassifier().classify(subject, delivered, ATS)
    return pipeline.PipelineItem(
        message_id=mid,
        thread_id=thread,
        subject=subject,
        sender_email=ATS,
        sender_name=f"{DISPLAY} Recruiting",
        received_at=EPOCH + timedelta(days=day),
        category=verdict.category.value,
        confidence=verdict.confidence,
        snippet=" ".join(body.split())[:200],
        identity_role=pipeline.role_from_message(subject, delivered) or "",
        identity_req_id=pipeline.extract_req_id(subject, delivered) or "",
    )


async def _sync(session, user, items):
    """One day-batch through the entrypoint routine and auto syncs take."""

    known_multi = await employers_with_several_applications(session, user)
    known_threads = await threads_naming_one_application(session, user)
    rolled = pipeline.roll_up_applications(items, known_multi, known_threads)
    fell_out: list = []
    review = pipeline.collect_review_items(items, fell_out, known_multi, known_threads)
    offered = {r.message_id for r in review}
    await sync_gmail_pipeline_additive(session, user, rolled, review)
    stored = set(
        (
            await session.exec(
                select(Email.message_id).where(
                    Email.user_id == user,
                    Email.message_id.in_(sorted(offered) or [""]),
                )
            )
        ).all()
    )
    return offered, offered - stored


@pytest.mark.asyncio
async def test_an_answered_row_settles_its_thread(test_session) -> None:
    """The ``is_reviewed`` arm — the one no corpus replay could reach.

    ``is_reviewed`` is written by ``classify_review_item`` and
    ``_settle_thread_siblings``, and by nothing on the sync path. A harness that
    answers the queue once, after the last batch, leaves this arm dead: zero
    rows carry the flag while any mail is still arriving. This is the arm the
    #596 spelling and the current one disagree about.
    """

    thread = "t-settled-3"
    offered, refused = await _sync(test_session, USER, [_item("p1", thread, *UPDATE, 0)])
    assert offered == {"p1"} and refused == set()

    # The user answers it with a category that files NOTHING: `is_reviewed`
    # set, `application_id` still NULL.
    await classify_review_item(test_session, USER, "p1", EmailCategory.OTHER, None)
    await test_session.flush()
    row = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.message_id == "p1")
        )
    ).first()
    assert row.is_reviewed is True and row.application_id is None, (
        "the fixture did not construct the state this test is about"
    )

    offered, refused = await _sync(test_session, USER, [_item("p2", thread, *UPDATE, 6)])
    assert offered == {"p2"}, "the second update never reached the filter"
    assert refused == {"p2"}, (
        "a conversation the user has already answered must not come back to "
        "the queue because a later message arrived on it"
    )


@pytest.mark.asyncio
async def test_another_mailboxs_filed_card_cannot_settle_mine(test_session) -> None:
    """A stranger's CARD on the same thread id must answer for nothing.

    The corpus generated ONE user until #614, so every ``user_id`` clause in the
    settled test was satisfied by construction and nothing asserted the scoping.
    Both mailboxes use the same thread id here deliberately: give them separate
    ones and the test passes whether or not the scoping exists.

    This arm is defended by ``Application.user_id == user_id`` inside
    :func:`_filed_on_an_application_that_answers`.
    """

    thread = "t-shared-filed"
    await _sync(test_session, OTHER, [_item("x1", thread, *ACK, 0)])
    assert (
        await test_session.exec(
            select(Application).where(Application.user_id == OTHER)
        )
    ).all(), "the other mailbox has no card, so there is nothing to leak"

    offered, refused = await _sync(test_session, USER, [_item("y1", thread, *UPDATE, 6)])
    assert offered == {"y1"}, "the owner's update never reached the filter"
    assert refused == set(), (
        "another mailbox's filed card answered for the owner's message — the "
        "settled test is not scoped to the user"
    )


@pytest.mark.asyncio
async def test_another_mailboxs_answered_row_cannot_settle_mine(test_session) -> None:
    """A stranger's ANSWERED row on the same thread id must answer for nothing.

    THE THINNER OF THE TWO ARMS, and the reason it gets its own test. The
    settled query's ``is_reviewed`` arm is a bare ``Email.is_reviewed == True``
    with no user predicate of its own — the ONLY thing keeping another
    mailbox's reviewed rows out of it is ``Email.user_id == user_id`` on the
    outer query. Measured: dropping that one clause suppresses this message and
    leaves the filed arm above untouched.
    """

    thread = "t-shared-answered"
    offered, _refused = await _sync(test_session, OTHER, [_item("x2", thread, *UPDATE, 0)])
    assert offered == {"x2"}, "the other mailbox's update never reached its queue"
    await classify_review_item(test_session, OTHER, "x2", EmailCategory.OTHER, None)
    await test_session.flush()
    row = (
        await test_session.exec(
            select(Email).where(Email.user_id == OTHER, Email.message_id == "x2")
        )
    ).first()
    assert row.is_reviewed is True and row.application_id is None, (
        "the fixture did not construct the state this test is about"
    )

    offered, refused = await _sync(test_session, USER, [_item("y2", thread, *UPDATE, 6)])
    assert offered == {"y2"}, "the owner's update never reached the filter"
    assert refused == set(), (
        "another mailbox's ANSWERED row settled the owner's conversation — the "
        "`is_reviewed` arm is not scoped to the user"
    )
    assert (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.message_id == "y2")
        )
    ).first() is not None, "the owner's update should have been stored and queued"
