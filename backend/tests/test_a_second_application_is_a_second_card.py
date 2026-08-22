"""Three applications to Google are three applications.

REPORTED FROM LIVE USE on 2026-08-21. The sync was healthy — last run 23:01:30,
status idle, no error, credentials valid. Google's confirmation was fetched and
classified correctly at 0.90. The board did not change, so from the user's side
the sync had done nothing.

It had been absorbed:

    application 104   company=Google   applied_date=2026-08-11
                      req_id=NULL      role_token=NULL      emails=3

Three separate applications, ten days apart, behind one card dated the first.
The mail gives nothing to tell them apart. Fetched from the mailbox, all three
bodies are byte-identical:

    Hi Ayush Yadav, Thanks for applying to Google! There are a ton of great
    companies out there, so we appreciate your interest in joining our team...

No role, no requisition number, no job link. Supabase is the same shape at two.

THE RULE. A confirmation ASSERTS an application; a rejection, assessment,
interview or offer REPORTS on one that already exists. So a confirmation with no
identity opens its own card, and an update with no identity never opens one — it
lands on the application it is about.

WHY THREAD IS NOT THE ANSWER, though it looks like one. The four Microsoft
confirmations of 21 August share a single Gmail thread and are four separate
applications: Gmail threaded them because the sender and subject are
byte-identical. A thread says how mail was delivered. It is used here for one
job only — routing an UPDATE to the right one of an employer's applications —
and never to decide whether an application exists.

WHY A SPLIT AND NOT A MERGE. The two failures are not symmetrical. A wrong split
puts two cards on the board where one belongs, which the user can see and fix. A
wrong merge destroys the record: nothing on the board says the second
application was ever made, and — because ``advance_application_status`` treats
rejected as terminal — one requisition's rejection settles every application
hiding behind it. ``pipeline._may_join`` already argues this for requisition
ids; this is the same argument where there is no id at all.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import Application, ApplicationStatus, Email, EmailSource

USER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

#: The real body, as the snippet delivers it. Identical for all three.
GOOGLE_SNIPPET = (
    "Hi Ayush Yadav, Thanks for applying to Google! There are a ton of great "
    "companies out there, so we appreciate your interest in joining our team. "
    "While we're not able to reach out to every applicant"
)


def google(message_id: str, day: int, *, category: str = "applied", thread_id: str | None = None):
    return p.PipelineItem(
        message_id=message_id,
        thread_id=thread_id,
        subject="Thanks for applying to Google",
        sender_email="noreply@google.com",
        sender_name=None,
        received_at=datetime.datetime(2026, 8, day, 7, 45),
        category=category,
        confidence=0.9,
        snippet=GOOGLE_SNIPPET,
    )


#: The three as they actually arrived, in the order the board showed them.
THREE = [google("g1", 11), google("g2", 13), google("g3", 21)]


async def _rows(session) -> list[Application]:
    return await apps._company_rows(session, USER, "google")


async def _links(session) -> dict[str, int | None]:
    emails = (await session.exec(select(Email))).all()
    return {e.message_id: e.application_id for e in emails}


# --- the defect as the user met it -------------------------------------------


def test_three_confirmations_are_three_applications() -> None:
    rolled = p.roll_up_applications(THREE)

    assert len(rolled) == 3, (
        f"three Google applications rolled up into {len(rolled)}. Before the fix "
        "this was 1, and the board did not move after a sync that read all three."
    )
    assert [{m.message_id for m in r.messages} for r in rolled] == [{"g1"}, {"g2"}, {"g3"}]


@pytest.mark.asyncio
async def test_the_board_ends_up_with_three_cards(test_session) -> None:
    """The rollup is not the surface. The board is."""

    await apps.upsert_applications_for_user(test_session, USER, p.roll_up_applications(THREE))
    await test_session.commit()

    rows = await _rows(test_session)
    assert len(rows) == 3
    assert sorted(str(r.applied_date) for r in rows) == ["2026-08-11", "2026-08-13", "2026-08-21"]
    assert len(set((await _links(test_session)).values())) == 3, "one confirmation per card"


@pytest.mark.asyncio
async def test_re_syncing_does_not_keep_minting(test_session) -> None:
    """The property that makes the split safe to ship.

    Nothing distinguishes these three clusters from each other, so the only
    thing that can stop the fourth sync from filing three more cards is the link
    an earlier sync already wrote (``_resolve_application``'s rule 0). Six syncs
    of the same mail must leave three rows.
    """

    rolled = p.roll_up_applications(THREE)
    for _ in range(6):
        await apps.upsert_applications_for_user(test_session, USER, rolled)
        await test_session.commit()

    rows = await _rows(test_session)
    assert len(rows) == 3, f"six syncs of three messages left {len(rows)} rows"
    assert all(r.dismissed_at is None for r in rows), (
        "a row minted and then emptied by the next cluster gets dismissed, which "
        "looks like a working sync and is not one"
    )


@pytest.mark.asyncio
async def test_the_merged_row_splits_in_place_and_keeps_its_id(test_session) -> None:
    """The migration, which is the half the live board actually needs.

    Row 104 already holds all three. The oldest confirmation must KEEP that row —
    every contact, note and user correction hangs off its id — and the later two
    mint beside it. This is also where ``_persist_message_refs``' sibling guard
    had to learn the difference between a message a cluster guessed at and the
    one it is defined by: the guard exists to stop an identity-less cluster
    taking mail off a sibling, and without the anchor exemption it blocked
    exactly the two moves this split consists of, leaving two empty new rows to
    be dismissed and the board unchanged.
    """

    row = Application(
        user_id=USER,
        company="Google",
        position="—",
        status=ApplicationStatus.APPLIED,
        applied_date=datetime.date(2026, 8, 11),
        source="gmail",
    )
    test_session.add(row)
    await test_session.flush()
    original = row.id
    for item in THREE:
        test_session.add(
            Email(
                user_id=USER,
                application_id=original,
                source_account=EmailSource.GMAIL,
                message_id=item.message_id,
                subject=item.subject,
                sender_email=item.sender_email,
                received_at=item.received_at,
                body_snippet=item.snippet,
            )
        )
    await test_session.commit()

    await apps.upsert_applications_for_user(test_session, USER, p.roll_up_applications(THREE))
    await test_session.commit()

    rows = await _rows(test_session)
    links = await _links(test_session)
    assert len(rows) == 3
    assert original in {r.id for r in rows}, "the row that was on the board must survive the split"
    assert links["g1"] == original, "the oldest application keeps the card it has always had"
    assert len(set(links.values())) == 3


# --- what must NOT split ------------------------------------------------------


def test_an_update_never_opens_a_second_card() -> None:
    """Palantir: an anonymous confirmation, then an anonymous rejection.

    A rejection reports on an application; it does not assert one. Under a
    blanket per-message split this employer becomes two cards, one of them a
    rejection with no application behind it.
    """

    confirmation = google("p1", 11)
    rejection = google("p2", 14, category="rejection")

    rolled = p.roll_up_applications([confirmation, rejection])

    assert len(rolled) == 1
    assert rolled[0].status == "rejected"


def test_a_single_role_less_confirmation_is_still_one_card() -> None:
    """The floor. Two or more is the claim; one is just mail that names no role.

    Without this the split would be free to fire on every anonymous confirmation
    in the mailbox and nothing here would notice.
    """

    rolled = p.roll_up_applications([google("only", 11)])

    assert len(rolled) == 1


def test_an_update_in_a_thread_lands_on_that_thread_s_application() -> None:
    """The user's rule, stated as a test: an update does not open a new card.

    Two applications on the board and an assessment invite that names no role.
    It arrives in the conversation the SECOND one started, so it belongs there —
    and guessing wrong is not cosmetic: ``advance_application_status`` treats a
    terminal status as final, so a misfiled rejection freezes a live application
    against every later interview and offer.
    """

    first = google("g1", 11, thread_id="t1")
    second = google("g2", 13, thread_id="t2")
    update = google("g2u", 15, category="assessment", thread_id="t2")

    rolled = p.roll_up_applications([first, second, update])

    assert len(rolled) == 2
    by_message = {frozenset(m.message_id for m in r.messages): r for r in rolled}
    assert frozenset({"g2", "g2u"}) in by_message
    assert by_message[frozenset({"g2", "g2u"})].status == "assessment"


def test_an_update_in_a_thread_holding_two_applications_goes_to_review() -> None:
    """The Microsoft shape, and the control on the routing above.

    One thread, two applications. The conversation names no single card, so it
    is exactly as ambiguous as an unthreaded update and is queued for the user
    rather than filed against whichever happened to sort first.
    """

    first = google("g1", 11, thread_id="shared")
    second = google("g2", 13, thread_id="shared")
    update = google("gu", 15, category="rejection", thread_id="shared")

    clusters, unplaced = p.partition_applications([first, second, update])

    assert len(clusters) == 2
    assert [i.message_id for i in unplaced] == ["gu"]
    assert p.unplaceable_message_ids([first, second, update]) == {"gu"}


def test_a_requisition_id_still_outranks_everything() -> None:
    """Microsoft: four applications, one thread, four requisition numbers.

    They never reach the anonymous path at all, which is the reason thread
    grouping was rejected as an identity — here it would have merged four real
    applications into one.
    """

    def microsoft(message_id: str, role: str, number: str, minute: int):
        return p.PipelineItem(
            message_id=message_id,
            thread_id="1a02341f84f11426",
            subject="Thank you for your application!",
            sender_email="donotreply@email.careers.microsoft.com",
            sender_name="Microsoft Careers",
            received_at=datetime.datetime(2026, 8, 21, 7, 38 + minute),
            category="applied",
            confidence=0.9,
            snippet=(
                f"Hi Ayush, Thank you for taking the time to submit your application "
                f"for {role} (Job number: {number}). We're glad you're interested in a "
                f"career at Microsoft"
            ),
        )

    rolled = p.roll_up_applications(
        [
            microsoft("m1", "Software Engineer II", "200045485", 0),
            microsoft("m2", "Customer Experience Engineer", "200049333", 3),
            microsoft("m3", "Software Engineer", "200043070", 4),
            microsoft("m4", "Pre-Training", "200007619", 5),
        ]
    )

    assert len(rolled) == 4
    assert {r.req_id for r in rolled} == {"200045485", "200049333", "200043070", "200007619"}


@pytest.mark.asyncio
async def test_a_card_keeps_its_own_application_when_older_mail_arrives_later(test_session) -> None:
    """The case that makes the stored link load-bearing rather than decorative.

    A first sync's window reached only the NEWEST confirmation, so the employer's
    single card is the 21 August application. A later sync — a rebuild, a wider
    window, a mailbox reconnect — then reads all three.

    Position cannot answer this. The clusters resolve oldest-first and the rows
    sort oldest-first, so matching them by order hands the 11 August application
    the card that belongs to the 21st: same three cards on the board, two of them
    now about a different application than the mail, notes and status included.
    Only the ``message → application`` link the earlier sync already wrote knows
    which is which, and it has to be read for the WHOLE pass before any of it is
    resolved, or the first cluster takes the row before the third can claim it.
    """

    await apps.upsert_applications_for_user(
        test_session, USER, p.roll_up_applications([google("g3", 21)])
    )
    await test_session.commit()
    rows = await _rows(test_session)
    assert len(rows) == 1
    newest = rows[0].id

    await apps.upsert_applications_for_user(test_session, USER, p.roll_up_applications(THREE))
    await test_session.commit()

    links = await _links(test_session)
    assert len(await _rows(test_session)) == 3
    assert links["g3"] == newest, (
        "the card that was on the board changed which application it is about"
    )
    assert links["g1"] != newest and links["g2"] != newest
    by_id = {r.id: r for r in await _rows(test_session)}
    assert str(by_id[newest].applied_date) == "2026-08-21"


@pytest.mark.asyncio
async def test_an_incremental_sync_files_new_mail_on_the_right_card(test_session) -> None:
    """The ordinary case, and the one that needs the link most.

    Three cards on the board. A routine sync then reads ONE of the three
    messages again — a re-scan, a corrected classification, a window that
    happened to reach it — and nothing else.

    Elimination cannot save this. With one cluster and three rows there is
    nothing to eliminate: rule 4 hands it the employer's OLDEST row, so a
    re-read of the 21 August confirmation walks off its own card and onto the
    11th's. The card it left is then empty and gets dismissed, and the user
    watches an application disappear from a sync that read nothing new.
    """

    await apps.upsert_applications_for_user(test_session, USER, p.roll_up_applications(THREE))
    await test_session.commit()
    before = await _links(test_session)
    assert len(set(before.values())) == 3

    # One message, on its own, exactly as an incremental pass would deliver it.
    await apps.upsert_applications_for_user(
        test_session, USER, p.roll_up_applications([google("g3", 21)])
    )
    await test_session.commit()

    after = await _links(test_session)
    assert after["g3"] == before["g3"], (
        "a re-read of one confirmation moved it onto a different application's card"
    )
    assert after == before
    rows = await _rows(test_session)
    assert len(rows) == 3 and all(r.dismissed_at is None for r in rows)
