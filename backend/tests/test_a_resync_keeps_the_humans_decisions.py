"""RE-SYNC IS THE BUTTON THE OWNER IS BEING TOLD TO PRESS. It must not eat his work.

``purge_and_rebuild_gmail_pipeline`` is named for what it does: it PURGES. It
is also the only path that can repair a board grouped before the identity fix
shipped, because an incremental sync has no delta to roll up and correctly does
nothing. So the recommendation "press Re-sync" is unavoidable, and it runs a
rebuild across the rows carrying every decision the owner ever made.

``test_resync_splits_the_merged_card.py`` proves the split happens, the row id
survives, and a second press changes nothing. NONE of that is a statement about
the human's data. On the live board every REJECTION row is ``user_corrected``:
the classifier has never once auto-detected one. If a rebuild re-derives status
and category from mail, it overwrites exactly the rows worth the most, and it
does it silently — a forged verdict where a person made a decision, which is
the ``classified_as is a commitment`` defect with the blast radius of the whole
board.

This file is the control on that. Every assertion below is a thing a human
typed or chose, checked across the rebuild that also splits the card underneath
it. The split is not incidental to the risk, it is the sharp edge of it: the
row the correction hangs off is the row being taken apart.
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
    ROLE_FROM_USER,
    ScanCoverage,
    classify_review_item,
    employers_with_several_applications,
    purge_and_rebuild_gmail_pipeline,
    record_role_correction,
    threads_naming_one_application,
)
from jobtracker.database.models import (
    ClassificationMethod,
    EmailCategory,
    ReviewDisposition,
)

USER = uuid.UUID("00000000-0000-0000-0000-0000000000dd")

GOOGLE_SNIPPET = (
    "Hi Ayush Yadav, Thanks for applying to Google! There are a ton of great "
    "companies out there, so we appreciate your interest in joining our team. "
    "While we're not able to reach out to every applicant"
)

#: The three as they sit in production: one row, three emails, ten days apart.
THREE = [("19ff2bc0b2f2f06b", 11), ("19ff9e22271ac010", 13), ("1a0234892a062ff6", 21)]

#: A fourth message the human RULED ON. It is a rejection for one of the three,
#: and on the live board a row like this is only ever ``user_corrected`` —
#: Applied has never auto-detected a rejection.
RULED_ON = "1a02aaa0deadbeef"


#: The same confirmation from an employer that DOES name the role. Used where a
#: test needs the rebuild to have a role to write, which is the only condition
#: under which a typed role could be overwritten.
NAMED_ROLE_SNIPPET = (
    "Hi Ayush Yadav, Thank you for applying to the Software Engineer, "
    "Infrastructure position at Google. There are a ton of great companies out "
    "there, so we appreciate your interest in joining our team."
)


def _item(message_id: str, day: int, snippet: str = GOOGLE_SNIPPET) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=None,
        subject="Thanks for applying to Google",
        sender_email="noreply@google.com",
        sender_name=None,
        received_at=datetime.datetime(2026, 8, day, 7, 45),
        category="applied",
        confidence=0.9,
        snippet=snippet,
    )


async def _seed_the_merged_board(session) -> int:
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


async def _resync(
    session,
    extra: list[p.PipelineItem] | None = None,
    items: list[p.PipelineItem] | None = None,
) -> None:
    """What POST /gmail/sync with mode='rebuild' runs, in the same order.

    ``extra`` is not a convenience. A rebuild RE-READS THE WHOLE MAILBOX, so
    every message a human ever ruled on comes back through the classifier
    carrying a fresh machine verdict, and that verdict is what would overwrite
    the human's. A version of this file that rolled up only the three
    confirmations passed every assertion below with the ``user_corrected``
    guard deleted from the product: nothing re-read the corrected message, so
    nothing could have overwritten it, and four green tests said so. That is a
    check that cannot fail. The scanned set has to contain the human's message
    or this file is decoration.
    """

    items = (items or [_item(m, d) for m, d in THREE]) + list(extra or [])
    known_multi = await employers_with_several_applications(session, USER)
    known_threads = await threads_naming_one_application(session, USER)
    rolled = p.roll_up_applications(items, known_multi, known_threads)
    review = p.collect_review_items(items, None, known_multi, known_threads)
    await purge_and_rebuild_gmail_pipeline(
        session,
        USER,
        rolled,
        review,
        # from_items, not the bare constructor: coverage with no date span
        # fails the contradiction test outright, so a removal path tested
        # against it can never fire and the archived-mail case below would
        # pass for the wrong reason.
        ScanCoverage.from_items(items),
    )
    await session.commit()


async def _live(session) -> list[Application]:
    rows = (
        await session.exec(select(Application).where(Application.user_id == USER))
    ).all()
    return [r for r in rows if r.dismissed_at is None]


async def _email(session, message_id: str) -> Email:
    return (
        await session.exec(
            select(Email).where(
                Email.user_id == USER, Email.message_id == message_id
            )
        )
    ).one()


@pytest.mark.asyncio
async def test_a_corrected_verdict_survives_the_rebuild(test_session) -> None:
    """The single most valuable row on the board, across the purge.

    A human read this message and said "rejection". The rebuild re-classifies
    from mail and would say "applied" for anything wearing Google's
    confirmation shape. ``user_corrected`` is the only thing standing between
    those two, and this asserts it holds through the path that PURGES rather
    than only through the additive one.
    """

    original = await _seed_the_merged_board(test_session)

    # The human rules on a fourth message. Not on file yet, so it arrives the
    # way the live-scan path delivers it.
    from jobtracker.cloud.applications import ScannedMessageIn

    await classify_review_item(
        test_session,
        USER,
        RULED_ON,
        EmailCategory.REJECTION,
        application_id=original,
        scanned=ScannedMessageIn(
            message_id=RULED_ON,
            subject="Update on your Google application",
            sender_email="noreply@google.com",
            received_at=datetime.datetime(2026, 8, 22, 9, 0),
            snippet="After careful consideration we are moving forward with other candidates",
            category=None,
            confidence=None,
        ),
    )
    await test_session.commit()

    before = await _email(test_session, RULED_ON)
    assert before.classified_as == EmailCategory.REJECTION
    assert before.user_corrected is True

    # The rebuild re-reads it and the classifier disagrees. ``interview`` and
    # not ``applied`` on purpose: a report routes to an existing card where a
    # confirmation would mint one, so the only thing this can change is the
    # verdict itself. It is also the live defect — a rejection that quotes its
    # own thread reads as an invitation.
    await _resync(
        test_session,
        [
            p.PipelineItem(
                message_id=RULED_ON,
                thread_id=None,
                subject="Update on your Google application",
                sender_email="noreply@google.com",
                sender_name=None,
                received_at=datetime.datetime(2026, 8, 22, 9, 0),
                category="interview",
                confidence=0.91,
                snippet="we would like to schedule time to speak with you",
            )
        ],
    )

    after = await _email(test_session, RULED_ON)
    assert after.classified_as == EmailCategory.REJECTION, (
        "the rebuild overwrote a verdict a person made. Every rejection on the "
        "live board is user_corrected, so this is not an edge case: it is most "
        "of what the owner has told the product."
    )
    assert after.user_corrected is True, "the flag that protects it must survive too"
    assert after.classification_method == ClassificationMethod.USER
    assert after.classification_confidence is None, (
        "a human decision carries no probability; restoring one re-forges the "
        "certainty the correction removed"
    )
    assert after.review_disposition == ReviewDisposition.UNATTRIBUTED, (
        "which act the human performed is itself a record, and a rebuild that "
        "recomputes it invents an agreement or an override that never happened"
    )
    assert after.application_id is not None, (
        "the corrected message must still be ON a card. Orphaning it is data "
        "loss in the shape the user cannot see: the row survives in the table "
        "and reaches no screen."
    )
    assert after.application_id in {r.id for r in await _live(test_session)}, (
        "and that card must be a LIVE one, not a row the rebuild dismissed"
    )


@pytest.mark.asyncio
async def test_a_role_the_user_typed_survives_the_rebuild(test_session) -> None:
    """A typed role is a decision, and the split is what makes it fragile.

    The rebuild re-takes an auto row's company AND its position, deliberately,
    so an improvement to extraction reaches rows already on the board. That
    same clause is what would overwrite the human's. ``position_source`` is the
    guard; this holds it across the rebuild, on the row that is simultaneously
    being split into three.
    """

    original = await _seed_the_merged_board(test_session)
    await record_role_correction(
        test_session, USER, original, "Software Engineer, Search Infrastructure"
    )

    # The oldest confirmation is re-read with a snippet the extractor CAN name a
    # role from. Without this the rebuild has no role to write and the guard is
    # never reached — the first version of this test passed with
    # ``position_source`` deleted from the product, because ``if r.role`` short
    # circuits on Google's role-less wording and nothing was ever at risk.
    items = [_item(THREE[0][0], THREE[0][1], NAMED_ROLE_SNIPPET)] + [
        _item(m, d) for m, d in THREE[1:]
    ]
    await _resync(test_session, items=items)

    rows = {r.id: r for r in await _live(test_session)}
    assert original in rows, "the row the human typed on must still be on the board"
    kept = rows[original]
    assert kept.position == "Software Engineer, Search Infrastructure", (
        f"the rebuild replaced a typed role with {kept.position!r}. Google's "
        "confirmation names no role at all, so the value that wins here is "
        "either the human's or a placeholder."
    )
    assert kept.position_source == ROLE_FROM_USER


@pytest.mark.asyncio
async def test_a_status_the_user_settled_is_not_reopened_by_the_rebuild(
    test_session,
) -> None:
    """Terminal means terminal, including across a purge.

    The mail says ``applied``. The human says ``rejected``. A rebuild that
    re-derives from mail walks the card backwards to APPLIED and the person
    watches a job they were turned down for climb back onto the active board.
    """

    original = await _seed_the_merged_board(test_session)
    row = (
        await test_session.exec(
            select(Application).where(Application.id == original)
        )
    ).one()
    row.status = ApplicationStatus.REJECTED
    test_session.add(row)
    await test_session.commit()

    await _resync(test_session)

    rows = {r.id: r for r in await _live(test_session)}
    assert original in rows
    assert rows[original].status == ApplicationStatus.REJECTED, (
        f"the rebuild moved a settled card to {rows[original].status}. "
        "advance_application_status treats rejected as terminal precisely so "
        "this cannot happen; the rebuild must go through that gate too."
    )
    # The control: the two cards the split MINTS are new applications, and they
    # must not inherit the terminal status of the row they were split off.
    minted = [r for r in rows.values() if r.id != original]
    assert len(minted) == 2
    assert all(r.status == ApplicationStatus.APPLIED for r in minted), (
        "a second application is not settled by the first one's rejection. "
        "That merge, in reverse, is the whole defect this fix exists for."
    )


@pytest.mark.asyncio
async def test_no_message_is_lost_by_the_rebuild(test_session) -> None:
    """Every message that was on file is still on file, and still reachable.

    The archived-mail case, which is the one that has actually destroyed real
    data here. On 2026-08-10 the rebuild deleted two applications whose ATS
    confirmations had been archived: an ``in:inbox`` scan cannot see archived
    mail, and the rebuild read that silence as "this application does not
    exist". A scan that cannot see a message reports exactly what a mailbox
    that no longer contains it reports, so absence had to stop being evidence.

    Stated as reachability and not as a row count, because the failure is the
    silent one: the ``Email`` rows survive in the table, nothing errors, and
    nothing is missing from the database. It is only missing from the product.
    """

    original = await _seed_the_merged_board(test_session)

    # A second employer whose confirmation was archived months ago. The rescan
    # below never names it — that is the whole point.
    archived_row = Application(
        user_id=USER,
        company="Roblox",
        position="Software Engineer, Simulation",
        status=ApplicationStatus.APPLIED,
        applied_date=datetime.date(2026, 6, 2),
        source="gmail",
    )
    test_session.add(archived_row)
    await test_session.flush()
    test_session.add(
        Email(
            user_id=USER,
            application_id=archived_row.id,
            source_account=EmailSource.GMAIL,
            message_id="19aaaaaaaaaaaaaa",
            subject="Thanks for applying to Roblox",
            sender_email="noreply@roblox.com",
            received_at=datetime.datetime(2026, 6, 2, 10, 0),
            body_snippet="Thank you for applying to the Software Engineer, Simulation position",
        )
    )
    await test_session.commit()

    before = {
        e.message_id
        for e in (
            await test_session.exec(select(Email).where(Email.user_id == USER))
        ).all()
    }
    assert len(before) == 4

    # The rescan sees the three Google confirmations and nothing else, exactly
    # as a scope-bounded scan of a real mailbox does.
    await _resync(test_session)

    live_ids = {r.id for r in await _live(test_session)}
    emails = (
        await test_session.exec(select(Email).where(Email.user_id == USER))
    ).all()
    assert {e.message_id for e in emails} == before, "a message went missing entirely"
    assert archived_row.id in live_ids, (
        "the rebuild took an application off the board because the scan could "
        "not see its mail. That is the 2026-08-10 destruction, and it is not "
        "recoverable by pressing the button again."
    )
    unreachable = [e.message_id for e in emails if e.application_id not in live_ids]
    assert not unreachable, (
        f"{len(unreachable)} message(s) survive in the table but hang off no "
        f"live card, so no screen can reach them: {unreachable}. "
        "That is data loss the database cannot see."
    )
