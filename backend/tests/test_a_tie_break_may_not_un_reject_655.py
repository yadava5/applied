"""A rule-4 tie-break may not walk a settled application out of REJECTED (#655).

WHAT THE DEFECT WAS. ``_pick_application``'s rule 4 hands an identity-less
cluster the employer's OLDEST LIVE row. ``_company_rows`` sorts live rows first
and a REJECTED row is live, so that row can be the fold target. A confirmation
dated after its stored rejection then satisfied every test
``_reopening_evidence`` applies — all of which ask what the MAIL says — and the
row left its terminal status. The evidence was real and it was about a
DIFFERENT application.

#641 closed this for a settled row that holds its own confirmation or names a
role, and recorded in ``_is_a_further_application``'s docstring that it stayed
open for "a row whose only mail is the rejection that minted it", on the grounds
that closing it meant steering rule 4. It does not. Rule 4 still returns the
same row to all three of its callers; what changed is what a rule-4 landing is
allowed to LICENSE.

WHY THE OBVIOUS RULE IS WRONG, WHICH IS THE POINT OF SECTION 2. The first
version of this fix refused the reopen whenever the cluster was anonymous. Every
one of the 181 tests around this path stayed green — because
``test_reopen_after_rejection`` is built entirely from mail that names a role
("Thanks for applying to the Data Scientist role at Acme"), so the anonymous
re-application had no test anywhere. It is a real shape: one employer, one
settled card, a fresh role-less acknowledgement. With one candidate there is no
tie to break, rule 4's own contract is satisfied literally, and refusing there
breaks the feature this function exists for. The discriminator is not "was the
cluster anonymous" but "did the tie-break have a CHOICE".

Every employer, sender and body here is invented. ``.test`` throughout.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    EmailSource,
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
)

USER = uuid.UUID("00000000-0000-0000-0000-000000000655")
DISPLAY = "Halverstock"
TOKEN = "halverstock"
SENDER = "careers@halverstock.test"

#: No job title, no requisition number — nothing a reader turns into an
#: identity. This is what makes the cluster reach rule 4 at all.
ANON_SNIPPET = (
    "Hi Ayush, thanks for applying! We appreciate your interest in joining the "
    "team and will be in contact if there is a match."
)
#: Names its job, so the cluster carries a role token and rules 1 to 3 answer
#: it. The control for section 3.
NAMED_SNIPPET = (
    "Hi Ayush, thank you for applying to the Platform Engineer position. Your "
    "application has been received and our team will review it shortly."
)


def _mail(message_id: str, *, day: int, category: str, snippet: str, subject: str):
    return p.PipelineItem(
        message_id=message_id,
        thread_id=None,
        subject=subject,
        sender_email=SENDER,
        sender_name=f"{DISPLAY} Talent",
        received_at=datetime.datetime(2026, 5, day, 9, 0),
        category=category,
        confidence=0.92,
        snippet=snippet,
    )


def anon_confirmation(message_id: str, day: int):
    return _mail(
        message_id,
        day=day,
        category="applied",
        snippet=ANON_SNIPPET,
        subject=f"Thanks for applying to {DISPLAY}",
    )


def named_confirmation(message_id: str, day: int):
    return _mail(
        message_id,
        day=day,
        category="applied",
        snippet=NAMED_SNIPPET,
        subject=f"Thank you for applying to {DISPLAY}",
    )


async def _row(
    session,
    *,
    role_token: str | None = None,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    created_day: int,
) -> Application:
    """A card already on the board. ``created_at`` is always explicit: rule 4's
    fold target is whichever row sorts first, so a default would make every
    assertion here depend on insertion order."""

    row = Application(
        user_id=USER,
        company=DISPLAY,
        position="Platform Engineer" if role_token else "—",
        status=status,
        applied_date=datetime.date(2026, 5, created_day),
        source=apps.SOURCE_GMAIL_AUTO,
        role_token=role_token,
        created_at=datetime.datetime(2026, 5, created_day, 8, 0),
    )
    session.add(row)
    await session.flush()
    return row


async def _file(session, row: Application, message_id: str, category, day: int) -> None:
    session.add(
        Email(
            user_id=USER,
            source_account=EmailSource.GMAIL,
            message_id=message_id,
            thread_id=None,
            subject="—",
            sender_email=SENDER,
            received_at=datetime.datetime(2026, 5, day, 9, 0),
            classified_as=category,
            classification_confidence=0.92,
            application_id=row.id,
        )
    )
    await session.flush()


async def _sync(session, items) -> None:
    await apps.upsert_applications_for_user(
        session, USER, p.roll_up_applications(items, frozenset({TOKEN}), frozenset())
    )
    await session.commit()


async def _rows(session) -> list[Application]:
    return await apps._company_rows(session, USER, TOKEN)


async def _links(session) -> dict[str, int | None]:
    rows = (await session.exec(select(Email).where(Email.user_id == USER))).all()
    return {e.message_id: e.application_id for e in rows}


# --- 1. the defect ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_blind_fold_does_not_un_reject_the_row_it_landed_on(test_session):
    """#655's reproduction, and BOTH halves are asserted.

    The board holds an identified live row and an anonymous REJECTED row whose
    only mail is the rejection that minted it, and the rejected one is OLDEST so
    it is rule 4's fold target. An anonymous confirmation arrives, newer than
    that rejection.

    ``_is_a_further_application`` correctly declines to mint — an unconfirmed
    anonymous row is plausibly this acknowledgement's own application, and
    splitting one application over two cards is the defect pointing the other
    way. So the fold happens. What must not happen is the reopen.
    """

    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=1)
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    named = await _row(test_session, role_token="platform engineer", created_day=6)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 6)
    await test_session.commit()

    await _sync(test_session, [anon_confirmation("a1", 20)])

    rows = {row.id: row for row in await _rows(test_session)}
    assert rows[settled.id].status == ApplicationStatus.REJECTED, (
        "a tie-break walked a settled application out of its terminal status; "
        "the confirmation that licensed it named no role and could have been "
        "about either card"
    )
    # THE OTHER HALF, asserted rather than left unstated. The mail still files
    # on the row it folded onto — refusing the reopen changes what the landing
    # LICENSES, not where the message goes — and no card is minted. Writing this
    # down is the difference between a decision and a silence: if the product
    # later decides an invisible re-application is worse than a stale card, this
    # is the assertion that has to change, and it will be found.
    assert (await _links(test_session))["a1"] == settled.id
    assert len(rows) == 2, f"minted a card ({len(rows)} rows); the fold was the decision"
    assert rows[named.id].status == ApplicationStatus.APPLIED, "the sibling moved"


@pytest.mark.asyncio
async def test_the_row_the_refusal_protects_is_the_one_the_tie_break_chose(test_session):
    """The fold target is the OLDEST live row, so the order is load-bearing.

    Same board as above with the two ``created_day`` values swapped. Now rule 4
    lands on the identified row instead, nothing settled is touched, and the
    reopen never arises. Without this the test above could pass for the wrong
    reason — a fix that refused every reopen everywhere would satisfy it.
    """

    named = await _row(test_session, role_token="platform engineer", created_day=1)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 1)
    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=6)
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 6)
    await test_session.commit()

    await _sync(test_session, [anon_confirmation("a1", 20)])

    rows = {row.id: row for row in await _rows(test_session)}
    assert (await _links(test_session))["a1"] == named.id
    assert rows[settled.id].status == ApplicationStatus.REJECTED


# --- 2. the directional control the first version of this fix broke -----------


@pytest.mark.asyncio
async def test_an_anonymous_re_application_to_a_single_card_still_reopens(test_session):
    """ONE row, so rule 4 has no tie to break, and the reopen must survive.

    This is the shape ``test_reopen_after_rejection`` cannot reach: every
    fixture there names a role, so the cluster is identified and rules 1 to 3
    answer it. Here the employer holds exactly one card, settled, whose only
    mail is its rejection, and a role-less acknowledgement arrives after it. The
    user re-applied. Rule 4's own contract — "joins the employer's only row if
    there is exactly one" — is satisfied literally, and there is no other card
    the mail could be about.

    A rule of the form "anonymous ⇒ refuse" passes every other test in this file
    and reds HERE. That is why it is written, and it is the assertion to run
    first if this fix is ever widened.
    """

    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=1)
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    await test_session.commit()

    await _sync(test_session, [anon_confirmation("a1", 20)])

    rows = await _rows(test_session)
    assert len(rows) == 1, f"minted beside the only card ({len(rows)} rows)"
    assert rows[0].id == settled.id
    assert rows[0].status == ApplicationStatus.APPLIED, (
        "a genuine re-application to an employer holding one settled card was "
        "refused; there was no tie to break and nothing else it could mean"
    )


# --- 3. the landings that are claims, which must be untouched -----------------


@pytest.mark.asyncio
async def test_an_identified_re_application_still_reopens_beside_a_sibling(test_session):
    """A KEYED landing on the same two-row board section 1 uses.

    The confirmation names its role, so rules 1 to 2 resolve it against the row
    carrying that role token. The tie-break is never consulted and the reopen is
    licensed exactly as before. A fix that keyed on "the employer has more than
    one row" rather than on HOW the row was reached reds here.
    """

    settled = await _row(
        test_session,
        role_token="platform engineer",
        status=ApplicationStatus.REJECTED,
        created_day=1,
    )
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    other = await _row(test_session, created_day=6)
    await _file(test_session, other, "other-ack", EmailCategory.APPLIED, 6)
    await test_session.commit()

    await _sync(test_session, [named_confirmation("n1", 20)])

    rows = {row.id: row for row in await _rows(test_session)}
    assert rows[settled.id].status == ApplicationStatus.APPLIED, (
        "a keyed landing was refused a reopen; re-applying to a role you were "
        "turned down for is the feature this function exists for"
    )


@pytest.mark.asyncio
async def test_a_stored_link_is_a_claim_and_still_reopens(test_session):
    """RULE 0 — the cluster's own message is already filed on the settled row.

    Two live rows, so rule 4 would have a choice; but the arriving message is
    already linked, and ``_anonymous_homes`` returns that row before the cascade
    is consulted. A stored link is the strongest claim there is, so this is not
    a blind landing however anonymous the mail reads.
    """

    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=1)
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    await _file(test_session, settled, "a1", EmailCategory.APPLIED, 20)
    other = await _row(test_session, role_token="platform engineer", created_day=6)
    await _file(test_session, other, "named-ack", EmailCategory.APPLIED, 6)
    await test_session.commit()

    await _sync(test_session, [anon_confirmation("a1", 20)])

    rows = {row.id: row for row in await _rows(test_session)}
    assert rows[settled.id].status == ApplicationStatus.APPLIED, (
        "the reopen was refused on a landing the stored link had already "
        "decided; rule 0 is a claim, not a tie-break"
    )


# --- 4. the resolver's own report ---------------------------------------------


@pytest.mark.asyncio
async def test_the_resolver_reports_blind_only_when_it_had_a_choice(test_session):
    """``_resolve_application``'s second return value, asserted directly.

    The three tests above reach it through the reopen, which means a fix that
    reported the flag correctly and then ignored it would still pass them in one
    direction. This pins the flag itself, and the two arms differ in exactly one
    thing: how many rows the employer holds.
    """

    settled = await _row(test_session, status=ApplicationStatus.REJECTED, created_day=1)
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    await test_session.commit()

    rolled = p.roll_up_applications(
        [anon_confirmation("a1", 20)], frozenset({TOKEN}), frozenset()
    )
    row, blind = await apps._resolve_application(test_session, USER, rolled[0])
    assert row is not None and row.id == settled.id
    assert blind is False, "one candidate is not a tie-break"

    named = await _row(test_session, role_token="platform engineer", created_day=6)
    await _file(test_session, named, "named-ack", EmailCategory.APPLIED, 6)
    await test_session.commit()

    row, blind = await apps._resolve_application(test_session, USER, rolled[0])
    assert row is not None and row.id == settled.id, "the fold target is unchanged"
    assert blind is True, (
        "two candidates and the cluster names neither; the resolver has to say "
        "it does not know or the reopen cannot tell a claim from a coin toss"
    )
