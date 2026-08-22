"""The RE-SYNC button is what actually repairs a board that is already wrong.

Found by driving production after the identity fix deployed. The ordinary sync
answered:

    no new mail since last sync · 3 s

and the board did not move — correctly. An incremental sync rolls up the delta,
and there was no delta: the three Google confirmations were read days ago and
are already filed. Nothing re-examines mail that has already been filed, so a
fix to how mail is GROUPED cannot reach a board that was grouped before it
shipped. Only ``purge_and_rebuild_gmail_pipeline`` — the explicit "Re-sync" —
re-reads the mailbox and rebuilds from the corrected rollup.

That path is not the one ``test_a_second_application_is_a_second_card.py``
exercises. It calls ``upsert_applications_for_user`` directly, and the rebuild
does three things around it that could each undo the repair: it dismisses auto
rows the scan contradicts, it reconciles orphaned classifications, and it
resets the review queue. This file drives the real entry point, from the state
the owner's board is actually in.
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

USER = uuid.UUID("00000000-0000-0000-0000-0000000000cc")

GOOGLE_SNIPPET = (
    "Hi Ayush Yadav, Thanks for applying to Google! There are a ton of great "
    "companies out there, so we appreciate your interest in joining our team. "
    "While we're not able to reach out to every applicant"
)

#: The three as they sit in production: one row, three emails, ten days apart.
THREE = [("19ff2bc0b2f2f06b", 11), ("19ff9e22271ac010", 13), ("1a0234892a062ff6", 21)]


def _item(message_id: str, day: int) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=None,
        subject="Thanks for applying to Google",
        sender_email="noreply@google.com",
        sender_name=None,
        received_at=datetime.datetime(2026, 8, day, 7, 45),
        category="applied",
        confidence=0.9,
        snippet=GOOGLE_SNIPPET,
    )


async def _seed_the_merged_board(session) -> int:
    """One Google card holding all three confirmations, as production has it."""

    row = Application(
        user_id=USER,
        company="Google",
        position="—",
        status=ApplicationStatus.APPLIED,
        applied_date=datetime.date(2026, 8, 11),
        source="gmail",
    )
    session.add(row)
    await session.flush()
    for message_id, day in THREE:
        session.add(
            Email(
                user_id=USER,
                application_id=row.id,
                source_account=EmailSource.GMAIL,
                message_id=message_id,
                subject="Thanks for applying to Google",
                sender_email="noreply@google.com",
                received_at=datetime.datetime(2026, 8, day, 7, 45),
                body_snippet=GOOGLE_SNIPPET,
            )
        )
    await session.commit()
    return row.id


async def _resync(session) -> None:
    """What POST /gmail/sync with mode='rebuild' runs, in the same order."""

    items = [_item(m, d) for m, d in THREE]
    known_multi = await employers_with_several_applications(session, USER)
    known_threads = await threads_naming_one_application(session, USER)
    rolled = p.roll_up_applications(items, known_multi, known_threads)
    review = p.collect_review_items(items, None, known_multi, known_threads)
    await purge_and_rebuild_gmail_pipeline(
        session,
        USER,
        rolled,
        review,
        # A server-side scan's own account of what it read. The rebuild may only
        # remove a row this coverage CONTRADICTS, so passing it is what makes
        # the removal half of this test real rather than skipped.
        ScanCoverage(message_ids={m for m, _d in THREE}),
    )
    await session.commit()


async def _board(session) -> list[Application]:
    rows = (
        await session.exec(select(Application).where(Application.user_id == USER))
    ).all()
    return [r for r in rows if r.dismissed_at is None]


async def _links(session) -> dict[str, int | None]:
    emails = (await session.exec(select(Email).where(Email.user_id == USER))).all()
    return {e.message_id: e.application_id for e in emails}


@pytest.mark.asyncio
async def test_a_resync_splits_the_card_that_is_already_wrong(test_session) -> None:
    original = await _seed_the_merged_board(test_session)
    assert len(await _board(test_session)) == 1

    await _resync(test_session)

    rows = await _board(test_session)
    links = await _links(test_session)
    assert len(rows) == 3, (
        f"a re-sync left {len(rows)} Google card(s). This is the only path that "
        "can repair a board grouped before the fix shipped — the ordinary sync "
        "has no delta to roll up and correctly does nothing."
    )
    assert original in {r.id for r in rows}, (
        "the card that was on the board must survive the split, id and all: "
        "every note, contact and correction hangs off it"
    )
    assert links["19ff2bc0b2f2f06b"] == original, "the oldest keeps the original card"
    assert len(set(links.values())) == 3
    assert sorted(str(r.applied_date) for r in rows) == [
        "2026-08-11",
        "2026-08-13",
        "2026-08-21",
    ]


@pytest.mark.asyncio
async def test_a_second_resync_changes_nothing(test_session) -> None:
    """Re-sync is a button a worried user presses twice.

    The rebuild dismisses auto rows a scan contradicts, and the two cards it
    just minted are exactly the shape that test looks at — a row whose company
    is in the fresh rollup is kept, but only because the token matches. If that
    ever stopped holding, the second press would clear what the first created
    and the board would flicker between three cards and one.
    """

    await _seed_the_merged_board(test_session)
    await _resync(test_session)
    first = {r.id for r in await _board(test_session)}
    links_first = await _links(test_session)

    await _resync(test_session)

    assert {r.id for r in await _board(test_session)} == first
    assert await _links(test_session) == links_first
