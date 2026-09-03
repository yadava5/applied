"""The third application to one employer, when the mail names no role (#641).

THE COMPOSITION, WHICH IS WHAT NOTHING TESTED. Both layers were individually
correct and each was asserted against its own intent:

    partition_applications   an identity-less CONFIRMATION at an employer that
                             already holds several cards becomes its OWN
                             cluster — "a new confirmation is a new application,
                             an update is not".
    _pick_application rule 4 an identity-less cluster files onto the employer's
                             OLDEST live row.

Run one after the other, the partition's decision is honoured one layer up and
reversed one layer down. The confirmation lands on application #1's card;
application #3 never appears, no queue entry is written, and no counter moves.
The user has no signal that anything was lost.

IT IS WORSE THAN AN INVISIBLE CARD. ``_company_rows`` sorts LIVE rows first and
a rejected row is live, so rule 4's ``rows[0]`` can be a settled application. A
folded confirmation dated after that rejection trips ``_reopening_evidence`` and
walks the row out of its terminal status — a settled application silently
un-rejected on a card the mail was never about. That is
``test_the_fold_does_not_un_reject_a_settled_application`` below, and it is the
reason the ruling went to MINT rather than to ASK.

WHY MINT AND NOT ASK. A queued confirmation answered WITHOUT the user picking a
row falls through ``_resolve_application_for_email`` to the same rule 4 — the
fold being fixed, now wearing human authority — because only the "None of these"
control mints. Asking would therefore mean "the user must find the one
non-default control, or the application vanishes anyway". And the resolver's own
written contract for a confirmation is that it "opens a card or lands on its own
stored one and nothing else"; ``rows[0]`` is neither.

THE REMEDY FOR A SPARE CARD IS A DISMISS CLICK. There is no merge endpoint in
this repository — ``POST /applications/{id}/split`` exists and nothing pairs
with it — so the failure directions are not symmetrical: a spare card can be
taken off the board, and an application that never appears cannot be recovered.

SECTIONS (k) AND (l) ARE NOT ABOUT #641. They are #699's finding (c) item 2:
four of the SQL predicates this path leans on spell tenant scoping, and no
fixture that reaches them built a cross-user ``Email -> application`` link, so
any of the four could be deleted with every one of those tests still green.
Section (k) closed two; section (l) closes the remaining two, so each of the
four now reds on its own deletion and on no other. They live here because they
are variants of the fixtures above — same employer, same helpers, one second
account — and a sibling module would have had to copy all of it.

Every employer, sender and body here is invented. ``.test`` throughout.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

USER = uuid.UUID("00000000-0000-0000-0000-000000000641")
#: Control (j) runs the delta and the rebuild side by side. Two users in one
#: session is two independent boards — every read here is scoped to a user id —
#: which is cheaper and more direct than two engines.
REBUILD_USER = uuid.UUID("00000000-0000-0000-0000-00000000064b")
#: A SECOND ACCOUNT, for section (k). Not another board of the same user's —
#: another person's, whose mail must never answer a question asked about this
#: one. Numbered for the issue that found the gap rather than for #641.
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-000000000699")

DISPLAY = "Alderfield"
TOKEN = "alderfield"
SENDER = "careers@alderfield.test"

#: What the sync knows and the pipeline cannot: this employer already holds
#: more than one live card. Computed in production by
#: ``employers_with_several_applications`` and passed to the partitioner.
MULTI = frozenset({TOKEN})


def _mail(
    message_id: str,
    *,
    subject: str,
    snippet: str,
    day: int,
    category: str = "applied",
    thread_id: str | None = None,
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        sender_email=SENDER,
        sender_name=f"{DISPLAY} Talent",
        received_at=datetime.datetime(2026, 5, day, 9, 0),
        category=category,
        confidence=0.92,
        snippet=snippet,
    )


def identified(message_id: str, role: str, day: int, *, thread_id: str | None = None):
    """A confirmation that names its job, so the row it makes carries a role token."""

    return _mail(
        message_id,
        subject=f"Thank you for applying to {DISPLAY}",
        snippet=(
            f"Hi Ayush, Thank you for applying to the {role} position at {DISPLAY}. "
            "Your application has been received and our team will review it shortly."
        ),
        day=day,
        thread_id=thread_id,
    )


#: THE MAIL THE WHOLE ISSUE IS ABOUT. No job title, no requisition number, no
#: link — nothing a reader can turn into an identity. Same wording every time,
#: which is also what makes two of them two clusters rather than one: a repeat
#: of a template is a second submission, where two DIFFERENT templates hours
#: apart are one submission acknowledged twice.
ANONYMOUS_SNIPPET = (
    f"Hi Ayush, Thanks for applying to {DISPLAY}! There are a ton of great "
    "companies out there, so we appreciate your interest in joining our team. "
    "While we are not able to reach out to every applicant, our recruiting team "
    "will contact you if there is a match."
)


def anonymous(
    message_id: str,
    day: int,
    *,
    category: str = "applied",
    thread_id: str | None = None,
):
    return _mail(
        message_id,
        subject=f"Thanks for applying to {DISPLAY}",
        snippet=ANONYMOUS_SNIPPET,
        day=day,
        category=category,
        thread_id=thread_id,
    )


IDENT_A = identified("i1", "Backend Engineer", 1, thread_id="t-backend")
IDENT_B = identified("i2", "Data Engineer", 3, thread_id="t-data")
ANON = anonymous("a1", 20)
ANON_TWIN = anonymous("a2", 28)


async def _sync(
    session,
    items,
    *,
    user: uuid.UUID = USER,
    known_multi: frozenset[str] = frozenset(),
    known_threads: frozenset[str] = frozenset(),
) -> None:
    """One pass of the real sync's rollup + persist, exactly as gmail_oauth runs it."""

    await apps.upsert_applications_for_user(
        session, user, p.roll_up_applications(items, known_multi, known_threads)
    )
    await session.commit()


async def _rows(session, user: uuid.UUID = USER) -> list[Application]:
    return await apps._company_rows(session, user, TOKEN)


async def _links(session, user: uuid.UUID = USER) -> dict[str, int | None]:
    emails = (await session.exec(select(Email).where(Email.user_id == user))).all()
    return {e.message_id: e.application_id for e in emails}


async def _row(
    session,
    *,
    user: uuid.UUID = USER,
    role_token: str | None = None,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    source: str = apps.SOURCE_GMAIL_AUTO,
    created_day: int = 1,
    dismissed_reason: str | None = None,
) -> Application:
    """A card that is already on the board, placed rather than synced.

    Used only for boards a delta cannot build for itself — a hand-dismissed
    sibling, a manual entry, a row whose only mail is a rejection. ``created_at``
    is always explicit: ``_company_rows`` breaks its live-first ordering on it,
    and rule 4's fold target is the row that sorts first, so leaving it to the
    default would make the assertion depend on insertion order.
    """

    row = Application(
        user_id=user,
        company=DISPLAY,
        position="Platform Engineer" if role_token else "—",
        status=status,
        applied_date=datetime.date(2026, 5, created_day),
        source=source,
        role_token=role_token,
        created_at=datetime.datetime(2026, 5, created_day, 8, 0),
        dismissed_at=(None if dismissed_reason is None else datetime.datetime(2026, 5, 15, 8, 0)),
        dismissed_reason=dismissed_reason,
    )
    session.add(row)
    await session.flush()
    return row


async def _file(
    session,
    row: Application,
    message_id: str,
    category: EmailCategory,
    day: int,
    *,
    user: uuid.UUID = USER,
    thread_id: str | None = None,
) -> None:
    """Mail already filed against a stored card, with a committed verdict.

    ``classified_as`` is the field the gate reads — "does this row already hold
    a confirmation of its own?" — so a fixture that omitted it would answer no
    for every row and the quantifier would be tested against nothing.
    """

    session.add(
        Email(
            user_id=user,
            application_id=row.id,
            source_account=EmailSource.GMAIL,
            message_id=message_id,
            thread_id=thread_id,
            subject=f"Mail for {DISPLAY}",
            sender_email=SENDER,
            received_at=datetime.datetime(2026, 5, day, 9, 0),
            body_snippet="stored",
            classified_as=category,
        )
    )
    await session.flush()


# --- the fixture measures what it claims --------------------------------------


def test_the_anonymous_confirmation_really_names_no_identity() -> None:
    """The precondition every control below rests on, asserted rather than assumed.

    If the role reader ever learns to pull a title out of this wording, every
    test in this file quietly starts measuring the identified path instead — and
    they would all still pass. This is the one that would go red.
    """

    (rolled,) = p.roll_up_applications([ANON], MULTI)
    assert rolled.req_id is None and rolled.role_token is None, (
        f"the fixture is no longer identity-less: req_id={rolled.req_id!r}, "
        f"role_token={rolled.role_token!r}"
    )
    assert rolled.company_token == TOKEN

    identified_rolled = p.roll_up_applications([IDENT_A, IDENT_B])
    assert {r.role_token for r in identified_rolled} == {
        "backend engineer",
        "data engineer",
    }, "the board this file builds is supposed to be an IDENTIFIED one"


# --- (a) the core -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_anonymous_confirmation_at_a_two_card_employer_mints(
    test_session,
) -> None:
    """Apply a third time; the acknowledgement names nothing. It is application #3.

    Before the fix this ended at two rows and the confirmation sat on the
    Backend Engineer card, which is the defect exactly as the user meets it.
    """

    await _sync(test_session, [IDENT_A, IDENT_B])
    before = await _rows(test_session)
    assert len(before) == 2 and all(r.role_token for r in before)

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == 3, (
        f"the third application ended on {len(rows)} cards. Before the fix this "
        "was 2: the confirmation folded onto the oldest existing row and nothing "
        "on the board said so."
    )
    minted = [r for r in rows if r.id not in {b.id for b in before}]
    assert len(minted) == 1
    assert minted[0].req_id is None and minted[0].role_token is None
    assert (await _links(test_session))["a1"] == minted[0].id, (
        "the card was minted but the confirmation was filed somewhere else"
    )


# --- (b) the directional control ----------------------------------------------


@pytest.mark.parametrize("category", ["rejection", "interview"])
@pytest.mark.asyncio
async def test_the_same_mail_as_an_update_mints_nothing(test_session, category) -> None:
    """#641's own requirement, built as a MUTATION of the core fixture.

    Byte-identical subject, body, sender, employer and date; the ONLY difference
    is the category. A fresh wording would have graded the wording. An update
    REPORTS on an application rather than asserting one, so at an employer
    holding several cards it goes to the review queue for the user to assign —
    it must never mint, and a fix that mints for both has broken the rule in the
    other direction.
    """

    update = dataclasses.replace(ANON, category=category)

    await _sync(test_session, [IDENT_A, IDENT_B])
    before = {r.id for r in await _rows(test_session)}

    clusters, unplaced = p.partition_applications([update], MULTI)
    assert clusters == [], "an anonymous update became a cluster of its own"
    assert [i.message_id for i in unplaced] == ["a1"], (
        "the update must reach the review queue, which is the designed answer"
    )

    await _sync(test_session, [update], known_multi=MULTI)
    assert {r.id for r in await _rows(test_session)} == before


@pytest.mark.asyncio
async def test_an_update_that_does_reach_the_resolver_lands_on_a_card(
    test_session,
) -> None:
    """The other half of the control, and the half that exercises the resolver.

    The queue is not the only route: an update whose Gmail conversation names
    exactly one stored card is placed by ``known_threads`` and DOES reach
    ``_resolve_application``. That is where a fix could still mint for an update
    by accident, so the arm is asserted separately from the queued one.
    """

    await _sync(test_session, [IDENT_A, IDENT_B])
    rows = await _rows(test_session)
    backend = next(r for r in rows if r.role_token == "backend engineer")

    update = anonymous("u1", 22, category="rejection", thread_id="t-backend")
    await _sync(
        test_session,
        [update],
        known_multi=MULTI,
        known_threads=frozenset({"t-backend"}),
    )

    after = await _rows(test_session)
    assert len(after) == 2, f"an anonymous update opened a card ({len(after)} rows)"
    assert (await _links(test_session))["u1"] == backend.id, (
        "the conversation names exactly one card and the update belongs to it"
    )


# --- (c) and (d) the anonymous board, frozen ----------------------------------


@pytest.mark.asyncio
async def test_an_entirely_anonymous_board_still_mints(test_session) -> None:
    """Case A, unchanged. Two anonymous cards, each holding its own confirmation."""

    await _sync(test_session, [anonymous("g1", 1), anonymous("g2", 8)])
    assert len(await _rows(test_session)) == 2

    await _sync(test_session, [anonymous("g3", 16)], known_multi=MULTI)

    assert len(await _rows(test_session)) == 3
    assert len(set((await _links(test_session)).values())) == 3


@pytest.mark.asyncio
async def test_an_anonymous_board_whose_only_mail_is_a_rejection_folds(
    test_session,
) -> None:
    """Case A's negative, unchanged, and the reason its quantifier exists.

    A rejection can mint a row of its own when it is the first thing the sync
    reads from an employer. The confirmation that follows is then far more
    likely to be the application that rejection REPORTED on than a second one,
    so it joins the row rather than splitting one application over two cards.
    """

    await _sync(test_session, [anonymous("r1", 4, category="rejection")])
    rows = await _rows(test_session)
    assert len(rows) == 1 and rows[0].status is ApplicationStatus.REJECTED

    await _sync(test_session, [anonymous("c1", 9)])

    after = await _rows(test_session)
    assert len(after) == 1, "an anonymous board holding only a rejection split in two"
    assert (await _links(test_session))["c1"] == after[0].id


# --- (e) one live row, frozen -------------------------------------------------


@pytest.mark.asyncio
async def test_one_live_identified_row_still_adopts_the_confirmation(
    test_session,
) -> None:
    """Case B, unchanged: the Roblox shape.

    One card at the employer and a role-less acknowledgement — an
    email-verification message, a second ATS wrapper around the same submission.
    With one card there is no "which of these" to get wrong, and rule 3's
    argument holds: this is the supporting message, not a second application.
    """

    await _sync(test_session, [IDENT_A])
    rows = await _rows(test_session)
    assert len(rows) == 1

    await _sync(test_session, [ANON])

    after = await _rows(test_session)
    assert len(after) == 1, f"a single-card employer minted a second card ({len(after)})"
    assert (await _links(test_session))["a1"] == rows[0].id


@pytest.mark.asyncio
async def test_a_hand_dismissed_sibling_is_not_a_second_card(test_session) -> None:
    """The case sitting ON the live-only boundary.

    A card the user dismissed by hand is not on the board, and it still holds
    its own mail — including the confirmation that made it. Counting it would
    take this employer to "two cards" and turn the frozen case above into a
    minting one, on the strength of a row the user cannot see.
    ``employers_with_several_applications`` counts live rows for exactly this
    reason (#597); the gate has to count the same way or the two disagree about
    what a multi-card employer is.
    """

    await _sync(test_session, [IDENT_A])
    live = (await _rows(test_session))[0]

    dismissed = await _row(
        test_session,
        created_day=2,
        dismissed_reason=apps.DISMISSED_BY_USER,
    )
    await _file(test_session, dismissed, "old-ack", EmailCategory.APPLIED, 2)
    await test_session.commit()

    await _sync(test_session, [ANON])

    rows = await _rows(test_session)
    assert len(rows) == 2, (
        f"a dismissed sibling pushed the employer over the threshold ({len(rows)} rows)"
    )
    assert (await _links(test_session))["a1"] == live.id
    settled = next(r for r in rows if r.id == dismissed.id)
    assert settled.dismissed_at is not None, "a hand dismissal is final"


# --- (f) the manual-row trap --------------------------------------------------


@pytest.mark.asyncio
async def test_a_manual_row_does_not_veto_the_mint(test_session) -> None:
    """THE NARROWING MOST LIKELY TO BE DROPPED AS REDUNDANT, and its only control.

    A hand-entered card is anonymous by construction and has no linked mail at
    all, so "every live anonymous row already holds a confirmation" is FALSE for
    it and stays false forever. Quantifying over manual rows would therefore
    reinstate #641 at every employer the user has ever typed a card for — with
    every other test in this file still green. The quantifier runs over AUTO
    rows only, the same restriction rule 3 applies for the same reason.
    """

    await _sync(test_session, [IDENT_A, IDENT_B])
    before = {r.id for r in await _rows(test_session)}
    await _row(test_session, source=apps.SOURCE_MANUAL, created_day=2)
    await test_session.commit()

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    minted = {r.id for r in rows} - before - {r.id for r in rows if r.source == apps.SOURCE_MANUAL}
    assert len(minted) == 1, (
        f"a hand-entered card blocked the mint; {len(rows)} rows, {len(minted)} new"
    )
    assert (await _links(test_session))["a1"] in minted


# --- (g) the quantifier -------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unconfirmed_anonymous_row_holds_the_mint_back(test_session) -> None:
    """An anonymous auto row that holds no confirmation of its own.

    Such a row is plausibly THIS acknowledgement's own application: the sync
    minted it from a rejection, and the confirmation that rejection reported on
    is only now being read. Minting beside it would split one application over
    two cards, which is the defect pointing the other way, so the gate declines
    and the ordinary tie-break files the mail.

    THE FOLD TARGET IS IMPRECISE AND THAT IS RECORDED HERE RATHER THAN FIXED:
    rule 4 returns ``rows[0]``, the OLDEST live row, which is the identified one
    below and not the unconfirmed row the refusal was about. It is exactly as
    imprecise as the anonymous board's fold, whose target is also ``rows[0]``.

    AND THE IMPRECISION HAS A COST THAT WAS MEASURED. Swap the two
    ``created_day`` values so the unconfirmed row is the oldest live one and it
    becomes the fold target: it is rejected, the arriving confirmation is newer
    than its stored rejection, and ``_reopening_evidence`` reopens it — two
    rows, status ``applied``. That is the same corruption
    ``test_the_fold_does_not_un_reject_a_settled_application`` closes, surviving
    in the one shape this arm deliberately refuses to mint for. It is NOT fixed
    here: fixing it means steering rule 4, which serves review-classify and
    orphan-reconcile as well as the sync. Recorded as the boundary of the fix,
    and deliberately not asserted — a test pinning that reopen would read as a
    decision that it is acceptable, and that decision has not been made.
    """

    named = await _row(test_session, role_token="platform engineer", created_day=1)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 1)
    unconfirmed = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=6)
    await _file(test_session, unconfirmed, "rej", EmailCategory.REJECTION, 6)
    await test_session.commit()

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == 2, (
        f"minted beside an unconfirmed anonymous row ({len(rows)} rows); that "
        "splits one application in two"
    )
    assert (await _links(test_session))["a1"] == named.id, (
        "the imprecision this test records: the fold lands on the oldest live "
        f"row (the identified one, id={named.id}) and not on the unconfirmed "
        f"row (id={unconfirmed.id}) the refusal was actually about"
    )


@pytest.mark.asyncio
async def test_the_quantifier_is_every_and_not_some(test_session) -> None:
    """EVERY, not SOME — the discriminator the single-row case above cannot draw.

    Two anonymous auto rows: one holds its confirmation, one does not. Case A's
    some-condition would be satisfied by the first and mint. Here a held
    confirmation is not evidence FOR a second application — the identified rows
    already establish the employer holds several — so the unconfirmed row still
    speaks, and one is enough.
    """

    named = await _row(test_session, role_token="platform engineer", created_day=1)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 1)
    confirmed = await _row(test_session, created_day=5)
    await _file(test_session, confirmed, "ack", EmailCategory.APPLIED, 5)
    unconfirmed = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=6)
    await _file(test_session, unconfirmed, "rej", EmailCategory.REJECTION, 6)
    await test_session.commit()

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == 3, (
        f"one confirmed sibling was taken as licence to mint ({len(rows)} rows); "
        "the quantifier must be EVERY"
    )
    assert (await _links(test_session))["a1"] == named.id


# --- (h) idempotency ----------------------------------------------------------


@pytest.mark.asyncio
async def test_re_reading_the_same_confirmation_mints_nothing_more(
    test_session,
) -> None:
    """The property that makes minting safe to ship at all.

    Nothing tells one anonymous confirmation from another, so the only thing
    that can stop the next sync filing a fourth card is the ``message ->
    application`` link the mint wrote in the same transaction. Rule 0 reads it
    for the whole pass before anything is resolved and returns the row before
    the gate is even consulted.
    """

    await _sync(test_session, [IDENT_A, IDENT_B])
    await _sync(test_session, [ANON], known_multi=MULTI)
    rows = await _rows(test_session)
    assert len(rows) == 3
    home = (await _links(test_session))["a1"]

    for _ in range(4):
        await _sync(test_session, [ANON], known_multi=MULTI)

    after = await _rows(test_session)
    assert len(after) == 3, f"four more syncs of one message left {len(after)} rows"
    assert (await _links(test_session))["a1"] == home, (
        "the confirmation walked off the card it minted"
    )
    assert all(r.dismissed_at is None for r in after), (
        "a row minted and then emptied by a later pass gets dismissed, which "
        "looks like a working sync and is not one"
    )


@pytest.mark.asyncio
async def test_two_anonymous_confirmations_in_one_delta_are_two_cards(
    test_session,
) -> None:
    """Two applications arriving together, and the second one resolving after the
    first has already minted.

    Within a single pass the minted id enters ``claimed`` and is blocked from
    rule 4, so the twin cannot resolve straight onto the row three lines older
    than it. The gate has to hold for the second one too: by then the board is
    MIXED with a fresh anonymous auto row on it, and that row holds the
    confirmation the first cluster just filed — which is what keeps the
    quantifier satisfied.
    """

    await _sync(test_session, [IDENT_A, IDENT_B])

    clusters, unplaced = p.partition_applications([ANON, ANON_TWIN], MULTI)
    assert len(clusters) == 2 and not unplaced, (
        "the fixture must present TWO clusters or it measures one mint twice"
    )

    await _sync(test_session, [ANON, ANON_TWIN], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == 4, f"two new applications came out as {len(rows) - 2} cards"
    links = await _links(test_session)
    assert links["a1"] != links["a2"], "both confirmations landed on one card"


# --- (i) the corruption regression -------------------------------------------


@pytest.mark.asyncio
async def test_the_fold_does_not_un_reject_a_settled_application(test_session) -> None:
    """The reason this is worse than an invisible card.

    The board holds a settled application — applied, then rejected — and a
    second, live, identified one. A role-less acknowledgement arrives AFTER the
    rejection. Folding it puts it on ``rows[0]``, the oldest live row, which is
    the rejected one; ``_reopening_evidence`` then reads a dated applied signal
    newer than the stored rejection and executes ``existing.status =
    ApplicationStatus(r.status)``. A settled application is silently reopened on
    a card the mail was never about, and the real third application still does
    not exist.

    Both assertions were red before the fix, and they are one failure: the
    status write and the missing card are the same fold seen from two sides.
    """

    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=1)
    await _file(test_session, settled, "old-ack", EmailCategory.APPLIED, 1)
    await _file(test_session, settled, "old-rej", EmailCategory.REJECTION, 9)
    await _row(test_session, role_token="platform engineer", created_day=4)
    await test_session.commit()
    assert len(await _rows(test_session)) == 2

    await _sync(test_session, [ANON], known_multi=MULTI)

    reread = next(r for r in await _rows(test_session) if r.id == settled.id)
    assert reread.status is ApplicationStatus.REJECTED, (
        f"a settled application was reopened to {reread.status.value} by a "
        "confirmation that was never about it"
    )
    rows = await _rows(test_session)
    assert len(rows) == 3, f"and the third application still does not exist ({len(rows)})"


# --- (j) a delta and a rebuild agree ------------------------------------------


@pytest.mark.asyncio
async def test_a_delta_and_a_rebuild_reach_the_same_board(test_session) -> None:
    """The two entrypoints compute ``known_multi`` before they branch, so they must.

    A delta hands the resolver one anonymous cluster; a rebuild hands it the
    same cluster alongside the two identified ones it re-reads. If the two ever
    disagreed the board would depend on which button the user pressed, which is
    the failure the in-scan and incremental halves of this rule exist to keep
    apart.
    """

    for user in (USER, REBUILD_USER):
        await _sync(test_session, [IDENT_A, IDENT_B], user=user)
        assert len(await _rows(test_session, user)) == 2

    await _sync(test_session, [ANON], user=USER, known_multi=MULTI)
    await _sync(test_session, [IDENT_A, IDENT_B, ANON], user=REBUILD_USER, known_multi=MULTI)

    delta = await _rows(test_session, USER)
    rebuild = await _rows(test_session, REBUILD_USER)
    assert len(delta) == len(rebuild) == 3, (
        f"delta produced {len(delta)} cards and rebuild {len(rebuild)}"
    )

    def shape(rows):
        return sorted((r.role_token or "", r.status.value, r.dismissed_at is None) for r in rows)

    assert shape(delta) == shape(rebuild)
    assert [r.role_token for r in delta].count(None) == 1, (
        "exactly one anonymous card, on both routes"
    )


# --- (k) the tenant predicate (#699) ------------------------------------------
#
# TWO CONJUNCTS SPELL TENANT SCOPING ON THIS PATH: ``Email.user_id == user_id``
# in ``_linked_applications_by_message``, which is how rule 0 finds a message's
# stored home, and the same clause in the mixed arm of
# ``_is_a_further_application``, which is how the quantifier decides whether an
# anonymous row already holds a confirmation. #699 measured both as
# unfalsifiable: no fixture in the modules that reach this code built a
# cross-user ``Email -> application`` link, so DELETING EITHER ONE LEFT EVERY
# ONE OF THOSE TESTS GREEN. A tenant-isolation clause that can be dropped in a
# refactor with the suite still green is this repository's named recurring
# shape, and the three cases below are its control.
#
# WHAT SECTION (k) DOES NOT COVER. These are controls over two SQL predicates,
# not an isolation audit. Nothing here asserts that RLS is enabled, that any API
# route scopes its reads, or that a writer in this repository can actually
# produce the rows the fixtures seed. Each asserts one thing — that the conjunct
# changes the answer — which is exactly what nothing asserted before.
#
# AND TWO IS NOT ALL OF THEM. The same clause guards the entirely-anonymous arm
# of ``_is_a_further_application`` and ``_application_in_conversation``; both
# were measured as still unfalsifiable when these cases were written, and
# neither is named in #699's finding. Written down rather than widened into, so
# that the next reader knows section (k) covers two of the four and not the set.
# CLOSED 2026-09-02 by section (l) below, which controls the other two. The
# note is kept because it is the record of how the gap was found.


@pytest.mark.asyncio
async def test_another_accounts_copy_of_a_message_is_not_this_ones_link(
    test_session,
) -> None:
    """Rule 0's lookup answers for ONE owner, asserted at the function itself.

    ``(user_id, message_id)`` is the emails table's unique key and ``message_id``
    alone is NOT: migration ``485296d24828`` removed the global UNIQUE precisely
    because the second user to receive the same Gmail message id would otherwise
    hit a unique violation and 500 their whole sync. Two accounts holding one
    message id is therefore a state the schema is designed for, and the conjunct
    is the only thing keeping this account's rule-0 lookup off the other
    account's card.

    ASSERTED HERE AND NOT THROUGH A SYNC because this is the order-independent
    half. ``_linked_applications_by_message`` folds its rows into a dict keyed by
    message id, so with the conjunct deleted the leak only reaches the board when
    the foreign row happens to be the LAST writer — see the sibling below, which
    depends on that and says so. This user's mailbox holds nothing at all for
    ``a1``, so the answer is empty or it is wrong, whatever order the database
    returns.

    IT DOES NOT COVER how a message id comes to be shared, and it is not
    evidence that one ever is here — only that if one is, the lookup stays on
    its own side.
    """

    theirs = await _row(test_session, user=OTHER_USER, created_day=1)
    await _file(test_session, theirs, "a1", EmailCategory.APPLIED, 1, user=OTHER_USER)
    await test_session.commit()

    asked_as_this_user = await apps._linked_applications_by_message(test_session, USER, ["a1"])
    asked_as_the_owner = await apps._linked_applications_by_message(
        test_session, OTHER_USER, ["a1"]
    )

    assert asked_as_this_user == {}, (
        "another account's copy of this Gmail message id answered rule 0's "
        "lookup — the application it names is not on this user's board at all"
    )
    # DIRECTIONAL. A lookup that had simply stopped finding anything would pass
    # the assertion above and fail this one.
    assert asked_as_the_owner == {"a1": theirs.id}, "the owner's own link went missing"


@pytest.mark.asyncio
async def test_a_second_account_holding_the_message_id_keeps_the_resync_idempotent(
    test_session,
) -> None:
    """The same predicate seen from the board: what a leak would actually cost.

    ``test_re_reading_the_same_confirmation_mints_nothing_more`` shows that the
    stored ``message -> application`` link is the ONLY thing stopping the next
    sync filing another anonymous card. This is that property with a second
    account holding the same Gmail message id beside it — the state migration
    ``485296d24828`` exists to permit — and the assertion is that it changes
    nothing.

    WITHOUT THE CONJUNCT it changes two things at once: rule 0 reads the other
    account's application id, finds it is not one of this employer's rows, and
    returns no home; the anonymous-board arm then sees this user's single row
    already holding a confirmation, calls the arriving message a second
    application, and mints. The user gets a duplicate card AND the confirmation
    walks off the card it opened.

    THE KILL HERE IS ORDER-DEPENDENT AND THE CONTROL IS THE TEST ABOVE.
    ``_linked_applications_by_message`` writes ``found[message_id] =
    application_id``, so with the conjunct deleted the answer is whichever row
    the database returned last. The foreign copy is stored AFTER this user's on
    purpose — under SQLite's ascending walk of ``ix_emails_message_id`` that
    makes it the last writer, which is measured and is why this case reds. A
    planner that returned them the other way would leave the leak real and this
    test quiet, which is the whole reason the order-independent assertion exists
    next to it rather than instead of it.
    """

    await _sync(test_session, [ANON])
    mine = (await _rows(test_session))[0]
    home = (await _links(test_session))["a1"]
    assert home == mine.id

    # The other account receives the same message id and files it against its
    # own card. Stored second: see the docstring.
    theirs = await _row(test_session, user=OTHER_USER, created_day=1)
    await _file(test_session, theirs, "a1", EmailCategory.APPLIED, 1, user=OTHER_USER)
    await test_session.commit()

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == 1, (
        f"a re-read of one confirmation left {len(rows)} cards because another "
        "account holds the same Gmail message id; rule 0 lost this user's own link"
    )
    assert (await _links(test_session))["a1"] == home, (
        "the confirmation walked off the card it opened"
    )
    # DIRECTIONAL, and the cheapest half: the other board is untouched, so a
    # lookup that refused every message id would not pass here either.
    assert [r.id for r in await _rows(test_session, OTHER_USER)] == [theirs.id]


@pytest.mark.parametrize(
    ("owner", "cards"),
    [(USER, 3), (OTHER_USER, 2)],
    ids=["this-account", "another-account"],
)
@pytest.mark.asyncio
async def test_only_this_accounts_mail_confirms_an_anonymous_row(
    test_session, owner, cards
) -> None:
    """The mixed arm's quantifier counts THIS user's mail, as a mutation of the owner.

    Byte-identical board and byte-identical confirmation across the two runs —
    same subject, sender, date, category, and the same application id it is
    filed against. The ONLY difference is ``Email.user_id``. A fixture that
    varied anything else would be grading that something else.

    ``[this-account]`` is the direction. The confirmation lands on the board's
    one unconfirmed anonymous auto row, "every live anonymous auto row already
    holds a confirmation" becomes true, and the arriving acknowledgement mints
    application #3. ``[another-account]`` is the same board with that row still
    unconfirmed as far as THIS user is concerned, so the gate declines and the
    mail folds by rule 4 — which is
    ``test_an_unconfirmed_anonymous_row_holds_the_mint_back`` reached by a
    different route, and the reason the pair is directional: a gate that had
    started refusing everything would fail the first case.

    A ROW LIKE THIS SHOULD NOT EXIST, AND THE SCHEMA DOES NOT FORBID IT.
    ``emails.application_id`` carries a plain foreign key to ``applications.id``
    and nothing ties ``emails.user_id`` to ``applications.user_id`` — no
    composite key, no check constraint. So the conjunct is what keeps the gate
    correct if one ever appears: a mis-scoped write, a restored backup, a future
    writer that forgets the scope.

    IT DOES NOT COVER whether any code path here can write such a row, and it
    says nothing about RLS or about the API's own scoping. It asserts that
    deleting the conjunct changes the board, which is the claim that had no test.
    """

    named = await _row(test_session, role_token="platform engineer", created_day=1)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 1)
    unconfirmed = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=6)
    await _file(test_session, unconfirmed, "rej", EmailCategory.REJECTION, 6)
    # THE ONE VARIABLE. Filed against THIS user's row either way; only the owner
    # of the Email row moves.
    await _file(test_session, unconfirmed, "ack", EmailCategory.APPLIED, 6, user=owner)
    await test_session.commit()

    await _sync(test_session, [ANON], known_multi=MULTI)

    rows = await _rows(test_session)
    assert len(rows) == cards, (
        f"a confirmation held by {owner} left {len(rows)} cards where {cards} "
        "was the answer; the quantifier must read only this account's mail"
    )
    links = await _links(test_session)
    if cards == 2:
        assert links["a1"] == named.id, (
            "the gate declined, so the fold target is rule 4's oldest live row"
        )
    else:
        assert links["a1"] not in {named.id, unconfirmed.id}, (
            "the card was minted but the confirmation was filed on an older row"
        )


# --- (l) the other two conjuncts (#699 finding (c), the half (k) left open) ----
#
# Section (k) closed two of the four ``Email.user_id == user_id`` clauses on this
# path and recorded, in its own header, that it was closing two and not the set.
# These are the other two: the entirely-anonymous arm of
# ``_is_a_further_application`` and ``_application_in_conversation``. Both were
# still unfalsifiable — deleting either left the suite green — for the same
# reason as before: no fixture built a cross-user ``Email -> application`` link.
#
# WHY THAT LINK IS THE ONLY FIXTURE THAT WORKS, and why the existing OTHER_USER
# cases do not reach these clauses. Both queries already narrow by
# ``application_id``, to ids taken from THIS user's rows. A second account
# holding its own rows and its own mail is therefore excluded by the
# application_id filter before the tenant clause is consulted, so those fixtures
# cannot tell a scoped query from an unscoped one. The state that separates them
# is a foreign account's Email pointing at OUR application — which the schema
# permits, because ``Email.application_id`` is a plain foreign key to
# ``applications.id`` with no composite constraint tying it to ``user_id``.
#
# WHAT THIS DOES NOT CLAIM. Not that any writer in this repository produces such
# a row, and not that RLS is on. Only that if the row exists, the answer stays on
# its own side of the fence — which is the whole content of a defence-in-depth
# clause, and is exactly what nothing asserted.


@pytest.mark.asyncio
async def test_a_foreign_link_does_not_make_our_anonymous_row_confirmed(
    test_session,
) -> None:
    """The quantifier asks "does this row already hold a confirmation?"

    On an entirely anonymous board the answer decides whether an arriving
    confirmation MINTS a card or folds into an existing one. Our row holds no
    applied-signal mail of its own; the only such mail pointing at it belongs to
    somebody else. The honest answer is therefore no.

    Read the failure as a user would: with the conjunct deleted the gate says
    "already confirmed", the mint is held back, and this account's third
    application never appears — caused by a row in an account it cannot see.
    """

    ours = await _row(test_session, created_day=1)
    # The foreign account's mail, filed against OUR application id.
    await _file(test_session, ours, "x1", EmailCategory.APPLIED, 1, user=OTHER_USER)
    await test_session.commit()

    rolled = p.RolledApplication(
        company_token=TOKEN,
        company_display=DISPLAY,
        role=None,
        status="applied",
        applied_at=None,
        last_activity=None,
        messages=(
            p.MessageRef(
                message_id="n1",
                thread_id=None,
                subject="Application received",
                sender_email=SENDER,
                sender_name=None,
                received_at=datetime.datetime(2026, 5, 2, 9, 0),
                category="applied",
                confidence=0.9,
            ),
        ),
    )

    asked_as_us = await apps._is_a_further_application(test_session, USER, rolled, [ours])
    # DIRECTIONAL. A gate that had simply stopped finding anything would satisfy
    # the assertion above and fail this one: asked as the account that actually
    # owns that mail, the very same row IS confirmed.
    asked_as_them = await apps._is_a_further_application(
        test_session, OTHER_USER, rolled, [ours]
    )

    assert asked_as_us is False, (
        "another account's mail answered the question 'does OUR anonymous row "
        "already hold a confirmation?' — the mint would be held back by a row "
        "this user cannot see"
    )
    assert asked_as_them is True, "the owner's own confirmation stopped counting"


@pytest.mark.asyncio
async def test_a_foreign_link_does_not_name_our_conversation(test_session) -> None:
    """Thread routing is the else-arm: where mail carries no key at all.

    ``_application_in_conversation`` answers "which of this employer's cards does
    this Gmail thread already sit on?" and, finding exactly one, files the
    arriving update there. Our mailbox holds nothing on this thread. The only
    row that does belongs to another account and merely points at our card.

    Cost of the leak: an update lands on a card whose thread this user never
    participated in, and — because a filed update can carry a status — moves it.
    """

    ours = await _row(test_session, created_day=1)
    await _file(
        test_session, ours, "t1", EmailCategory.APPLIED, 1, user=OTHER_USER, thread_id="thr-1"
    )
    await test_session.commit()

    rolled = p.RolledApplication(
        company_token=TOKEN,
        company_display=DISPLAY,
        role=None,
        status="applied",
        applied_at=None,
        last_activity=None,
        messages=(
            p.MessageRef(
                message_id="u1",
                thread_id="thr-1",
                subject="Re: your application",
                sender_email=SENDER,
                sender_name=None,
                received_at=datetime.datetime(2026, 5, 3, 9, 0),
                category="other",
                confidence=0.9,
            ),
        ),
    )

    asked_as_us = await apps._application_in_conversation(test_session, USER, rolled, [ours])
    asked_as_them = await apps._application_in_conversation(
        test_session, OTHER_USER, rolled, [ours]
    )

    assert asked_as_us is None, (
        "another account's mail on this thread named a card on OUR board — the "
        "update would file onto an application whose conversation this user "
        "was never part of"
    )
    # DIRECTIONAL, same argument as above: the query still works, and it is the
    # tenant clause and nothing else that changed the answer.
    assert asked_as_them is ours, "the owner's own thread stopped resolving"
