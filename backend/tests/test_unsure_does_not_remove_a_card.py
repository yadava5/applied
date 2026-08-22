"""A CARD IS NOT REMOVED BECAUSE THE SCAN BECAME UNSURE ABOUT ITS MAIL.

FOUND ON PRODUCTION, 2026-08-22, driving the owner's real board through a
Re-sync after the identity fix shipped. Google split 1 → 3 and Supabase 1 → 2
as predicted, Amazon split 6 → 7 with three of the seven sharing one Gmail
thread — and Microsoft went 1 → 0.

Microsoft is the employer the whole identity fix started from: four
applications in one thread, reported by the owner as "I applied to 4 new
Microsoft and a Google application, but when I sync it in the app, I'm not
getting anything." The rebuild removed the one card he had. The message it was
filed from was sitting in the review queue at 80%, four points under the 0.85
auto-file gate, printing its own requisition number.

Nothing had disproved that application. The classifier had become less
certain, and ``purge_and_rebuild_gmail_pipeline`` read the resulting absence
from the rolled set as a correction.

THE SHAPE, because it is the second time: this is the archived-mail defect one
level up. On 2026-08-10 a rebuild read SILENCE as absence and destroyed two
real applications. ``_scan_contradicts`` was written to fix that, and it did —
what it could not see is that a scan has three answers and not two. It can say
"this is an application", "this is not", and "I do not know". Only the middle
one is a contradiction. The whole point of a review queue is that an uncertain
verdict costs the user a decision, not an application.

The removal is a dismissal with a restore link, so this was recoverable and it
was not silent, which is the only reason it is a defect and not a repeat.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    Application,
    ApplicationStatus,
    Email,
    EmailSource,
    ScanCoverage,
    employers_with_several_applications,
    purge_and_rebuild_gmail_pipeline,
    threads_naming_one_application,
)

USER = uuid.UUID("00000000-0000-0000-0000-0000000000ee")

MESSAGE = "1a0234892a06beef"

#: The real one, as Microsoft sends it. It names a requisition number, which is
#: what makes the removal so hard to defend: the message the scan could not
#: settle is more identifying than most mail the product files without asking.
SNIPPET = (
    "Hi Ayush, Thank you for taking the time to submit your application for "
    "Pre-Training (Job number: 200007619). We're glad you're interested in a "
    "career at Microsoft, and we're here to help"
)


async def _seed(session) -> int:
    row = Application(
        user_id=USER,
        company="Microsoft",
        position="Pre-Training",
        status=ApplicationStatus.APPLIED,
        applied_date=datetime.date(2026, 8, 21),
        source="gmail",
    )
    session.add(row)
    await session.flush()
    session.add(
        Email(
            user_id=USER,
            application_id=row.id,
            source_account=EmailSource.GMAIL,
            message_id=MESSAGE,
            subject="Thank you for your application!",
            sender_email="donotreply@email.careers.microsoft.com",
            received_at=datetime.datetime(2026, 8, 21, 7, 43),
            body_snippet=SNIPPET,
        )
    )
    await session.commit()
    return row.id


def _item(confidence: float) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=MESSAGE,
        thread_id="1a02341f84f11426",
        subject="Thank you for your application!",
        sender_email="donotreply@email.careers.microsoft.com",
        sender_name="Microsoft Careers",
        received_at=datetime.datetime(2026, 8, 21, 7, 43),
        category="applied",
        confidence=confidence,
        snippet=SNIPPET,
    )


async def _resync(session, confidence: float) -> None:
    items = [_item(confidence)]
    known_multi = await employers_with_several_applications(session, USER)
    known_threads = await threads_naming_one_application(session, USER)
    rolled = p.roll_up_applications(items, known_multi, known_threads)
    review = p.collect_review_items(items, None, known_multi, known_threads)
    await purge_and_rebuild_gmail_pipeline(
        session,
        USER,
        rolled,
        review,
        ScanCoverage.from_items(items),
    )
    await session.commit()


async def _live(session) -> list[Application]:
    rows = (
        await session.exec(select(Application).where(Application.user_id == USER))
    ).all()
    return [r for r in rows if r.dismissed_at is None]


@pytest.mark.asyncio
async def test_a_verdict_under_the_gate_does_not_remove_the_card_it_filed() -> None:
    """The floor under the whole thing, stated once."""

    assert p.REVIEW_FLOOR < 0.80 < p.AUTO_FILE_GATE, (
        "this file is written around a verdict that is uncertain but not "
        "dismissed. If the two thresholds move past 0.80 the scenario stops "
        "being the production one and these tests stop meaning what they say."
    )


@pytest.mark.asyncio
async def test_an_unsure_scan_leaves_the_application_alone(test_session) -> None:
    original = await _seed(test_session)

    # 0.80: over the review floor, under the auto-file gate. The pipeline sends
    # it to the queue, so the rollup does not name Microsoft.
    await _resync(test_session, 0.80)

    live = {r.id for r in await _live(test_session)}
    assert original in live, (
        "the rebuild removed an application because the scan was UNSURE about "
        "its mail. Nothing disproved it: the message went to the review queue, "
        "which is the scan saying it does not know. This is the owner's "
        "Microsoft card, and Microsoft is the employer the identity fix "
        "started from."
    )


@pytest.mark.asyncio
async def test_the_message_is_still_reachable_after_an_unsure_scan(
    test_session,
) -> None:
    """The half a card count cannot see.

    A row that survives while its mail is orphaned is not a fix — the board
    keeps a card the user can open onto nothing, which is worse than an honest
    removal with a restore link.
    """

    original = await _seed(test_session)
    await _resync(test_session, 0.80)

    email = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.message_id == MESSAGE)
        )
    ).one()
    assert email.application_id == original


@pytest.mark.asyncio
async def test_a_confident_scan_still_keeps_it(test_session) -> None:
    """The ordinary case, as the control on the two above."""

    original = await _seed(test_session)
    await _resync(test_session, 0.95)

    assert original in {r.id for r in await _live(test_session)}


@pytest.mark.asyncio
async def test_a_scan_that_disagrees_can_still_remove_the_row(test_session) -> None:
    """THE CONTROL THAT MATTERS, and the reason this is not a one-line revert.

    ``_scan_contradicts`` exists so a rebuild CAN clean up a row filed from a
    message the classifier has since corrected — that is the whole purpose of
    the Re-sync button. A fix that keeps every row keeps the garbage too, and
    the removal path would then be a check that cannot fail.

    Here the scan re-reads the same message and concludes it is not job mail at
    all. No rollup, no review item, and the row goes.
    """

    original = await _seed(test_session)

    settled_as_noise = p.PipelineItem(
        message_id=MESSAGE,
        thread_id="1a02341f84f11426",
        subject="Your receipt",
        sender_email="donotreply@email.careers.microsoft.com",
        sender_name="Microsoft",
        received_at=datetime.datetime(2026, 8, 21, 7, 43),
        category="other",
        confidence=0.97,
        snippet="Your order has shipped.",
    )
    known_multi = await employers_with_several_applications(test_session, USER)
    known_threads = await threads_naming_one_application(test_session, USER)
    rolled = p.roll_up_applications([settled_as_noise], known_multi, known_threads)
    review = p.collect_review_items(
        [settled_as_noise], None, known_multi, known_threads
    )
    assert not rolled and not review, (
        "this control only means something if the scan produces NEITHER a "
        "rolled application nor a review item — that is what 'disagreed' is"
    )
    await purge_and_rebuild_gmail_pipeline(
        test_session,
        USER,
        rolled,
        review,
        # from_items, not the bare constructor: the date span is half the
        # contradiction test, and coverage built without it can never remove
        # anything — which would make this control silently inert.
        ScanCoverage.from_items([settled_as_noise]),
    )
    await test_session.commit()

    assert original not in {r.id for r in await _live(test_session)}, (
        "a scan that re-read the row's own mail and concluded it is not an "
        "application must still be able to retire the row, or Re-sync stops "
        "being able to clean anything up."
    )
