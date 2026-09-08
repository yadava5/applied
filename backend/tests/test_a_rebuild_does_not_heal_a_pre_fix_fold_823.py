"""Does the Re-sync rebuild heal a fold that predates #641's fix? (#823)

#641 fixed the MINT: an identity-less confirmation at a multi-card employer now
opens its own card instead of folding onto an existing one. That fix runs at
classification time and says nothing about mail already ingested. #823 asks the
question that could not be answered from the code alone — whether the explicit
"Re-sync" rebuild recovers the two things a pre-fix fold left wrong:

  (a) the card that never appeared, and
  (b) a terminal status the fold reversed.

This module ANSWERS it by execution rather than by reading, and the answer is
NO to both. Read the assertions as a recorded finding, not as a specification of
desired behaviour: each one says what the product does today and names what it
would have to do instead for the remedy to exist.

Why a reading could not settle it. `purge_and_rebuild_gmail_pipeline` is named
for a purge, and it does remove rows — but removal is a DISMISSAL, and it never
touches the stored ``Email -> application`` link. Rule 0 (``_anonymous_homes``)
consults exactly that link, before ``_is_a_further_application`` is reached, for
idempotency. So the rebuild walks the same pin the delta path walks. Whether the
two other stages (`reconcile_orphaned_classifications`, the status re-derivation)
undo it anyway is the part only a run can tell you.

Every employer, sender and body here is invented. ``.test`` throughout.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
)

from tests.test_an_anonymous_confirmation_is_a_third_application import (
    ANON,
    IDENT_A,
    IDENT_B,
    MULTI,
    SENDER,
    TOKEN,
    USER,
    _file,
    _links,
    _row,
    _rows,
)

CORPUS = [IDENT_A, IDENT_B, ANON]


async def _rebuild(session, items, *, user=USER):
    """One press of the Re-sync button, exactly as `gmail_oauth` runs it."""

    return await apps.purge_and_rebuild_gmail_pipeline(
        session,
        user,
        p.roll_up_applications(items, MULTI, frozenset()),
        p.collect_review_items(items, MULTI, frozenset()),
        apps.ScanCoverage.from_items(items),
    )


async def _fold(session, row, message_id: str, day: int) -> None:
    """The pre-#641 wrong state: a confirmation stored against a card that is
    not its own. This is what the old mint did, written directly because the
    code that produced it no longer exists to be run."""

    session.add(
        Email(
            user_id=USER,
            message_id=message_id,
            thread_id=None,
            subject="—",
            sender_email=SENDER,
            received_at=p.datetime.datetime(2026, 5, day, 9, 0)
            if hasattr(p, "datetime")
            else None,
            classified_as=EmailCategory.APPLIED,
            classification_confidence=0.92,
            source_account=EmailSource.GMAIL,
            application_id=row.id,
        )
    )
    await session.flush()


# --- (a) the card that never appeared -----------------------------------------


@pytest.mark.asyncio
async def test_a_rebuild_does_not_recover_the_card_a_pre_fix_fold_swallowed(
    test_session,
):
    """The finding: rule 0's stored link survives the purge, so it still pins.

    Board built as a pre-fix sync would have left it — two identified cards, and
    the anonymous confirmation stored against the FIRST of them rather than
    holding a card of its own. Then a full Re-sync over all three messages.

    Post-#641 the partition gives that confirmation its own cluster, because the
    employer holds two or more live cards. The rebuild still does not mint it: it
    reaches `_resolve_application`, whose rule 0 finds the stored link and
    returns that row before `_is_a_further_application` is ever consulted.
    """

    ident_a = await _row(test_session, role_token="backend engineer", created_day=1)
    await _file(test_session, ident_a, "i1", EmailCategory.APPLIED, 1)
    ident_b = await _row(test_session, role_token="data engineer", created_day=3)
    await _file(test_session, ident_b, "i2", EmailCategory.APPLIED, 3)
    # THE FOLD. `a1` is the anonymous confirmation; pre-fix it was stored
    # against ident_a instead of opening a third card.
    await _file(test_session, ident_a, "a1", EmailCategory.APPLIED, 20)
    await test_session.commit()

    before = len(await _rows(test_session))
    await _rebuild(test_session, CORPUS)
    await test_session.commit()

    rows = await _rows(test_session)
    live = [r for r in rows if r.dismissed_at is None]
    links = await _links(test_session)

    assert before == 2
    assert len(live) == 2, (
        f"the rebuild recovered the swallowed card ({len(live)} live rows) — if "
        "this fires, #823's remedy EXISTS and this module should be rewritten "
        "as a regression test rather than a finding"
    )
    assert links["a1"] == ident_a.id, (
        "the confirmation is still pinned to the card it was wrongly folded "
        "onto; rule 0 reads the stored link before the mint gate is consulted"
    )
    assert ident_b.id in {r.id for r in live}, "the untouched sibling was disturbed"


@pytest.mark.asyncio
async def test_the_same_mail_arriving_fresh_DOES_mint_the_third_card(test_session):
    """The control that makes the finding above mean something.

    Identical board, identical rebuild, identical messages — with one thing
    varied: the anonymous confirmation carries no stored link. It mints. So the
    two-row result above is the PIN, not a rebuild that cannot mint at all and
    not a fixture that fails to reach the gate.
    """

    ident_a = await _row(test_session, role_token="backend engineer", created_day=1)
    await _file(test_session, ident_a, "i1", EmailCategory.APPLIED, 1)
    ident_b = await _row(test_session, role_token="data engineer", created_day=3)
    await _file(test_session, ident_b, "i2", EmailCategory.APPLIED, 3)
    await test_session.commit()

    await _rebuild(test_session, CORPUS)
    await test_session.commit()

    live = [r for r in await _rows(test_session) if r.dismissed_at is None]
    assert len(live) == 3, (
        f"unlinked, the same confirmation should open its own card; got {len(live)}"
    )


# --- (b) the terminal status the fold reversed --------------------------------


@pytest.mark.asyncio
async def test_a_rebuild_leaves_the_reversed_row_holding_only_its_rejection(
    test_session,
):
    """The second half, and the rebuild makes it WORSE rather than leaving it.

    A row whose only mail was its own rejection, walked out of `rejected` by a
    confirmation that was never about it — #655's shape, in the data it leaves
    behind. Both messages are linked to that row and the row reads `applied`.

    Measured after one Re-sync over the same mail:

        row 1  APPLIED   links: {rej}        <- the reversed row
        row 2  APPLIED   links: {i2, a1}     <- the identified sibling

    Two findings, and the second is not in #823.

    1. The status is NOT re-derived. A rebuild rolls up the SCAN and advances the
       row, and `advance_application_status` is monotone — it will not walk
       `applied` back to `rejected`. Nothing recomputes a stored row's status
       from its own linked mail, on any path.

    2. The confirmation MOVES OFF the row, and the row keeps the status that
       confirmation was the only evidence for. So the rebuild leaves a card
       whose sole linked message is a REJECTION reading `applied` — a state no
       scan can produce and no user action explains. Before the rebuild the row
       was at least internally consistent about its own (wrong) reason.

    Neither assertion here is a specification. Both record what the product does
    today, and each says what firing would mean.
    """

    settled = await _row(
        test_session, status=ApplicationStatus.REJECTED, created_day=1
    )
    await _file(test_session, settled, "rej", EmailCategory.REJECTION, 1)
    other = await _row(test_session, role_token="data engineer", created_day=3)
    await _file(test_session, other, "i2", EmailCategory.APPLIED, 3)
    # THE REVERSAL, as the pre-fix fold left it: the confirmation is stored on
    # the settled row and the status has been walked forward.
    await _file(test_session, settled, "a1", EmailCategory.APPLIED, 20)
    settled.status = ApplicationStatus.APPLIED
    test_session.add(settled)
    await test_session.commit()

    # The state going in, asserted so the move below is a MOVE and not a fixture
    # that never put the message there.
    assert (await _links(test_session))["a1"] == settled.id

    await _rebuild(test_session, [IDENT_B, ANON])
    await test_session.commit()

    rows = {r.id: r for r in await _rows(test_session)}
    links = await _links(test_session)

    assert rows[settled.id].status == ApplicationStatus.APPLIED, (
        "the rebuild re-derived the terminal status — if this fires, #823's "
        "second remedy EXISTS and this module should be rewritten as a "
        "regression test rather than a finding"
    )
    assert links["a1"] == other.id, (
        "the confirmation stayed on the row it was folded onto; the finding "
        "below depends on it having moved"
    )
    assert links["rej"] == settled.id
    assert [m for m, a in links.items() if a == settled.id] == ["rej"], (
        "the reversed row should now hold its rejection and nothing else"
    )
    # THE STATE THAT SHOULD NOT EXIST, stated as its own assertion because it is
    # the finding: a card reading `applied` whose only linked message is a
    # rejection. Re-deriving from linked mail would answer this in one query.
    assert (
        rows[settled.id].status == ApplicationStatus.APPLIED
        and [m for m, a in links.items() if a == settled.id] == ["rej"]
    )
