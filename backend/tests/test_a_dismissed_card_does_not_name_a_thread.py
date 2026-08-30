"""A DISMISSED CARD DOES NOT NAME A THREAD (#611).

``threads_naming_one_application`` and ``employers_with_several_applications``
are read on adjacent lines of ``gmail_oauth`` and handed to the same two
functions in the same breath. One filtered dismissed rows out; the other did
not. Reproduced by execution on one dismissed card plus one message linked to
it: the employers set came back empty (correct) and the threads set came back
holding that card's thread.

What the disagreement COSTS, and it is not symmetric between the two reasons:

* ``resync`` — the rebuild's opinion. #596 settled that such a card does not
  answer for its mail, so the mail comes back and asks. This helper said the
  thread already named one card, and ``pipeline`` used that to escape the
  ambiguous-goes-to-the-review-queue rule and FILE the message. The upsert then
  silently cleared the dismissal, so the board grew a card the user never asked
  for, chosen by a machine on delivery structure alone.
* ``user`` — a person said "this is not an application". The escape lands the
  message on an invisible card instead of asking beside the visible ones.

THE FIX IS LIVE-ONLY, matching the line-mate — NOT the settlement predicate.
The settlement predicate KEEPS a hand-dismissed thread, and keeping it
suppresses the arriving message by THREAD ALONE, where this product's
definition of "its mail" is thread PLUS identity. That is the LOST shape, not a
lucky landing. The helper's own docstring reasons this at length.

WHAT THIS FILE PINS, and why each case is here
----------------------------------------------

1. A thread whose only filed mail sits on a ``resync``-dismissed card is not
   named — with the twin at a LIVE card, which is what stops the assertion
   passing for a helper that returns the empty set.
2. The same for a ``user``-dismissed card, and its own twin. Both reasons,
   because the defect fired for both and the queue is the right answer for both.
3. THE MIXED THREAD — one live card and one dismissed card sharing a
   conversation. It is excluded today because it names TWO applications, and it
   must go on being excluded. This is the single most likely way to get the fix
   wrong: adding ``dismissed_at IS NULL`` to the grouping query makes that
   thread read as naming one card, and a message that used to ask now files
   silently. A loosening shipped inside a narrowing. Measured: with the filter
   on the query, ``test_a_thread_spanning_a_live_and_a_dismissed_card_is_not_named``
   reds while cases 1 and 2 stay green — which is what earns this fixture its
   place rather than making it a third copy of the dismissal tests.
4. The helper's CORE FAMILY still works: an employer replying inside its own
   confirmation's conversation, naming one live card, is still named and its
   update is still filed rather than queued.
5. The resolve-time twin ``_application_in_conversation``, which must stay
   unfiltered. A future "one predicate, N spellings" sweep that unifies the two
   breaks the resync resurrect, so the tests at the foot of this file red on it.

EVERY PIPELINE-LEVEL CASE GIVES ITS EMPLOYER TWO OR MORE LIVE CARDS, and that
is a requirement rather than decoration. ``known_threads`` is consulted only
inside ``if token in known_multi and len(keyed) != 1:`` and ``known_multi`` is
already live-only, so a single-live-card employer cannot reach the escape at
all — the ``elif not keyed`` branch takes the message first and the test would
pass for a reason unrelated to this change. That is the one-row-per-employer
blind spot named above ``test_a_hand_dismissal_is_final.CARDS`` in a new
costume, so the fixtures that need several rows are standalone functions with
their own seeds rather than more rows in the table-driven one.

Every employer, sender, requisition and role here is INVENTED and every domain
is RFC 2606 reserved. Nothing in this file comes from a real mailbox (#593).
"""

from __future__ import annotations

import datetime
import uuid
from typing import NamedTuple

import pytest
from sqlmodel import select

from jobtracker.cloud import applications as apps_module
from jobtracker.cloud import pipeline as p
from jobtracker.cloud.applications import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
    employers_with_several_applications,
    threads_naming_one_application,
)

USER = uuid.UUID("00000000-0000-0000-0000-000000000611")

DISMISSED_AT = datetime.datetime(2026, 8, 22, 5, 2, 29)
STORED_AT = datetime.datetime(2026, 8, 24, 10, 0, 0)
ARRIVED_AT = datetime.datetime(2026, 8, 26, 9, 0, 0)

#: At/above ``AUTO_FILE_GATE``. An arrival under the gate reaches the queue for
#: a reason that has nothing to do with this helper, so every arriving item here
#: is one the pipeline would file if it could place it.
GATED = 0.92

#: Names no role in either field, which is the shape that asks the thread
#: question at all. 24 of the 26 corpus cards are rejections whose snippet ends
#: mid-preamble, so this is the production shape rather than a contrived one.
BLIND_SNIPPET = "Thank you for taking the time to speak with us."


def _sender_for(company: str) -> str:
    """An address whose domain brand resolves BACK to ``company``.

    ``resolve_employer`` returns the sender's domain brand, and ``known_multi``
    is keyed on ``normalize_company_name`` of the stored name. The two have to
    meet or the escape rule is never reached and every pipeline assertion below
    is about a different code path. The fixture controls assert the meeting
    rather than assuming it.
    """

    return f"careers@{company.lower()}.test"


def _blind_subject(company: str) -> str:
    return f"Update on your {company} application"


async def _add_card(
    session,
    company: str,
    *,
    reason: str | None,
    position: str = "",
) -> int:
    """One application row. ``reason=None`` means a live card.

    ``position=""`` is ``applications._NO_ROLE`` — an anonymous auto row, what
    an employer's unattributed confirmation leaves behind. ``source="gmail"`` is
    ``SOURCE_GMAIL_AUTO`` spelled literally; the plausible-looking "gmail_auto"
    reads as user-owned to ``_is_auto_row``.
    """

    row = Application(
        user_id=USER,
        company=company,
        position=position,
        status=ApplicationStatus.APPLIED,
        source="gmail",
        dismissed_at=None if reason is None else DISMISSED_AT,
        dismissed_reason=reason,
    )
    session.add(row)
    await session.flush()
    return row.id


async def _add_mail(
    session,
    *,
    company: str,
    message_id: str,
    thread_id: str,
    application_id: int | None,
    offset_minutes: int = 0,
    category: EmailCategory = EmailCategory.REJECTION,
) -> None:
    session.add(
        Email(
            user_id=USER,
            application_id=application_id,
            source_account=EmailSource.GMAIL,
            message_id=message_id,
            thread_id=thread_id,
            subject=_blind_subject(company),
            sender_name="Careers",
            sender_email=_sender_for(company),
            received_at=STORED_AT - datetime.timedelta(minutes=offset_minutes),
            body_snippet=BLIND_SNIPPET,
            classified_as=category,
            classification_confidence=0.78,
            is_reviewed=False,
            user_corrected=False,
        )
    )


def _arrival(company: str, message_id: str, thread_id: str) -> p.PipelineItem:
    """A gated, identity-less update arriving on an existing conversation."""

    return p.PipelineItem(
        message_id=message_id,
        thread_id=thread_id,
        subject=_blind_subject(company),
        sender_email=_sender_for(company),
        sender_name="Careers",
        received_at=ARRIVED_AT,
        category="rejection",
        confidence=GATED,
        snippet=BLIND_SNIPPET,
    )


async def _sets(session) -> tuple[frozenset[str], frozenset[str]]:
    """The two sets ``gmail_oauth`` reads on adjacent lines, read the same way."""

    known_multi = await employers_with_several_applications(session, USER)
    known_threads = await threads_naming_one_application(session, USER)
    return known_multi, known_threads


# =============================================================================
# One card per employer — the two dismissal reasons and their live twins
# =============================================================================
#
# ONE EMPLOYER PER CASE and one row per employer, the rule
# ``test_a_hand_dismissal_is_final`` states above its own table: sharing an
# employer would make each assertion depend on which row a lookup happened to
# return first. The multi-row cases below are standalone by design, for the
# reason that file gives — adding a second row here would reintroduce exactly
# the luck this rule forbids for every case that reads it.


class SingleCase(NamedTuple):
    company: str
    #: ``None`` is a live card.
    reason: str | None
    #: Whether the employer's thread should come back in the set.
    named: bool


SINGLE_CASES: tuple[SingleCase, ...] = (
    # #596's card. Its mail is an open question, so its thread names nothing.
    SingleCase("Ashcombe", "resync", False),
    # Ashcombe's directional twin: identical in every respect except that the
    # card is live. Without it the resync assertion passes for a helper that
    # returns the empty set.
    SingleCase("Brightmoor", None, True),
    # #597's card. A human's removal stands, and the queue is where its mail
    # belongs — beside the cards the user can actually see.
    SingleCase("Culverton", "user", False),
    # Culverton's own twin. Each reason gets its own control so a failure names
    # the reason rather than leaving the two to alibi each other.
    SingleCase("Dunhollow", None, True),
)

#: Hardcoded, so a mistake in the table cannot quietly redefine what is proved.
#: A derived-only expectation agrees with any fixture, including an empty one.
EXPECTED_NAMED = {"t-brightmoor", "t-dunhollow"}


def _thread_for(company: str) -> str:
    return f"t-{company.lower()}"


@pytest.fixture
async def singles(test_session) -> dict[str, int]:
    """One card per :data:`SINGLE_CASES`, and the one message that names it.

    EVERY CARD SHARES ONE ``dismissed_at`` where it has one. That is the
    control: the reason column is the only variable between a ``user`` case and
    its ``resync`` twin, and the live twins differ from both only in carrying no
    dismissal at all.
    """

    ids: dict[str, int] = {}
    for index, case in enumerate(SINGLE_CASES):
        row_id = await _add_card(test_session, case.company, reason=case.reason)
        ids[case.company] = row_id
        await _add_mail(
            test_session,
            company=case.company,
            message_id=f"m-{case.company.lower()}",
            thread_id=_thread_for(case.company),
            application_id=row_id,
            offset_minutes=index,
        )
    await test_session.commit()
    return ids


@pytest.mark.asyncio
async def test_the_single_card_fixture_is_the_shape_these_tests_assume(
    test_session, singles
) -> None:
    """The positive control. Every claim below assumes a reachable fixture.

    Four employers, one row each, one filed message each, each on its own
    thread. If any of that drifts, the assertions further down are about
    something other than dismissal.
    """

    rows = (await test_session.exec(select(Application).where(Application.user_id == USER))).all()
    assert len(rows) == len(SINGLE_CASES)
    assert {r.company for r in rows} == {c.company for c in SINGLE_CASES}
    assert {r.dismissed_reason for r in rows} == {None, "resync", "user"}

    mail = (await test_session.exec(select(Email).where(Email.user_id == USER))).all()
    assert len(mail) == len(SINGLE_CASES)
    assert all(m.application_id is not None for m in mail)
    assert len({m.thread_id for m in mail}) == len(SINGLE_CASES)

    # And there is no employer here with two cards, so nothing in this fixture
    # could reach the escape rule by a route other than the one being tested.
    known_multi, _ = await _sets(test_session)
    assert known_multi == frozenset()


@pytest.mark.asyncio
async def test_a_thread_whose_only_card_was_resync_dismissed_is_not_named(
    test_session, singles
) -> None:
    """#596's rule, on this helper. Reds when the live narrowing is removed."""

    _, known_threads = await _sets(test_session)
    assert "t-ashcombe" not in known_threads


@pytest.mark.asyncio
async def test_a_thread_whose_only_card_is_live_is_still_named(test_session, singles) -> None:
    """The directional twin of the case above — the same shape, live.

    Its whole job is to fail for a helper that has been narrowed into returning
    nothing, which the assertion above cannot detect on its own.
    """

    _, known_threads = await _sets(test_session)
    assert "t-brightmoor" in known_threads


@pytest.mark.asyncio
async def test_a_thread_whose_only_card_was_hand_dismissed_is_not_named(
    test_session, singles
) -> None:
    """#597's rule, on this helper. A card the user removed names nothing."""

    _, known_threads = await _sets(test_session)
    assert "t-culverton" not in known_threads


@pytest.mark.asyncio
async def test_a_thread_whose_only_card_is_live_is_named_beside_the_hand_case(
    test_session, singles
) -> None:
    """The hand-dismissed case's own twin, so the two reasons do not alibi."""

    _, known_threads = await _sets(test_session)
    assert "t-dunhollow" in known_threads


@pytest.mark.asyncio
async def test_the_set_is_exactly_the_live_singletons(test_session, singles) -> None:
    """Both directions at once, against the hardcoded expectation."""

    _, known_threads = await _sets(test_session)
    assert set(known_threads) == EXPECTED_NAMED


# =============================================================================
# THE MIXED THREAD — the trap, and the only fixture that catches it
# =============================================================================
#
# One conversation, two of the employer's cards: one live, one dismissed. Today
# it names TWO applications, so it is excluded and the update it carries is
# asked about — the four-Microsoft rule working. The obvious one-line fix,
# ``Application.dismissed_at.is_(None)`` on the grouping query, makes the query
# see only the live one: the thread reads as unambiguous and the message files
# straight to it. A thread that used to ask now files, silently.
#
# THE EMPLOYER GETS A THIRD, LIVE CARD so the token reaches ``known_multi`` and
# the pipeline arm below is actually exercised. With only the live-plus-
# dismissed pair the employer holds ONE live card, the escape rule is never
# consulted, and the arrival would be placed by a branch this change cannot
# touch.

MIXED_COMPANY = "Everleigh"
MIXED_THREAD = "t-everleigh"
MIXED_ARRIVAL = "m-everleigh-arrival"


@pytest.fixture
async def mixed(test_session) -> dict[str, int]:
    """One employer: a live card, a dismissed card sharing its thread, a spare.

    The spare live card is on its own conversation and exists only to put the
    employer over the two-live-cards line ``known_multi`` counts.
    """

    live = await _add_card(test_session, MIXED_COMPANY, reason=None)
    dismissed = await _add_card(test_session, MIXED_COMPANY, reason="resync")
    spare = await _add_card(test_session, MIXED_COMPANY, reason=None)

    await _add_mail(
        test_session,
        company=MIXED_COMPANY,
        message_id="m-everleigh-live",
        thread_id=MIXED_THREAD,
        application_id=live,
    )
    await _add_mail(
        test_session,
        company=MIXED_COMPANY,
        message_id="m-everleigh-dismissed",
        thread_id=MIXED_THREAD,
        application_id=dismissed,
        offset_minutes=1,
    )
    await _add_mail(
        test_session,
        company=MIXED_COMPANY,
        message_id="m-everleigh-spare",
        thread_id="t-everleigh-spare",
        application_id=spare,
        offset_minutes=2,
    )
    await test_session.commit()
    return {"live": live, "dismissed": dismissed, "spare": spare}


@pytest.mark.asyncio
async def test_the_mixed_fixture_is_one_thread_across_two_cards(test_session, mixed) -> None:
    """The control for the trap case: the thread really does span both cards."""

    mail = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.thread_id == MIXED_THREAD)
        )
    ).all()
    assert len(mail) == 2
    assert {m.application_id for m in mail} == {mixed["live"], mixed["dismissed"]}

    # And the employer is over the line the escape rule is gated on, so the
    # pipeline assertion below reaches it.
    known_multi, _ = await _sets(test_session)
    assert p.normalize_company_name(MIXED_COMPANY) in known_multi


@pytest.mark.asyncio
async def test_a_thread_spanning_a_live_and_a_dismissed_card_is_not_named(
    test_session, mixed
) -> None:
    """THE TRAP. Unchanged behaviour, and the reason to group UNFILTERED.

    The thread names two applications, so it names no single card. A fix that
    filters the grouping query instead of narrowing after it sees only the live
    one, and this assertion is what reds on it — while the dismissal cases above
    stay green, which is what makes this fixture load-bearing rather than a
    third copy of them.
    """

    _, known_threads = await _sets(test_session)
    assert MIXED_THREAD not in known_threads


@pytest.mark.asyncio
async def test_an_arrival_on_the_mixed_thread_is_still_asked_about(test_session, mixed) -> None:
    """The same claim one level up, where the loosening would actually be paid.

    A gated, identity-less update on that conversation is unplaceable today and
    must stay unplaceable: nothing here tells the pipeline which of the two
    cards it is about.
    """

    known_multi, known_threads = await _sets(test_session)
    items = [_arrival(MIXED_COMPANY, MIXED_ARRIVAL, MIXED_THREAD)]
    assert MIXED_ARRIVAL in p.unplaceable_message_ids(items, known_multi, known_threads)
    assert MIXED_ARRIVAL in {
        r.message_id for r in p.collect_review_items(items, None, known_multi, known_threads)
    }


# =============================================================================
# The escape rule itself — where the disposition actually changes
# =============================================================================
#
# Three employers, each holding at least two LIVE cards so ``known_multi``
# carries the token and the thread question is reached:
#
#   * Fernwick — plus a ``resync``-dismissed card whose conversation holds its
#     filed mail. Today the arrival escapes to that card and the upsert clears
#     the dismissal. After, it asks.
#   * Halloway — the same with a HAND-dismissed card. Today the arrival lands on
#     a card the user cannot see.
#   * Glenmara — the control, and the helper's core family: the conversation
#     belongs to a LIVE card, the employer is replying inside its own
#     confirmation, and the update must still be filed rather than queued.
#
# Glenmara is what makes the other two directional. Without it, a change that
# emptied the set entirely would satisfy both.


class EscapeCase(NamedTuple):
    company: str
    #: The dismissal reason on the card that owns the conversation; ``None``
    #: means the conversation's card is live.
    reason: str | None
    #: Whether the arrival on that conversation should be filed rather than
    #: asked about.
    filed: bool


ESCAPE_CASES: tuple[EscapeCase, ...] = (
    EscapeCase("Fernwick", "resync", False),
    EscapeCase("Halloway", "user", False),
    EscapeCase("Glenmara", None, True),
)


def _escape_arrival_id(company: str) -> str:
    return f"m-{company.lower()}-arrival"


@pytest.fixture
async def escapes(test_session) -> dict[str, dict[str, int]]:
    """Per employer: two live cards, plus the card owning the conversation.

    For Glenmara the conversation's owner IS one of the two live cards, so that
    employer has two rows where the others have three. That asymmetry is the
    case: what varies between the arms is whether the card the thread names can
    be seen, and nothing else.
    """

    seeds: dict[str, dict[str, int]] = {}
    for index, case in enumerate(ESCAPE_CASES):
        first = await _add_card(test_session, case.company, reason=None)
        second = await _add_card(test_session, case.company, reason=None)
        if case.reason is None:
            owner = first
        else:
            owner = await _add_card(test_session, case.company, reason=case.reason)
        seeds[case.company] = {"first": first, "second": second, "owner": owner}

        await _add_mail(
            test_session,
            company=case.company,
            message_id=f"m-{case.company.lower()}-stored",
            thread_id=_thread_for(case.company),
            application_id=owner,
            offset_minutes=index,
            # The employer's own confirmation, which is what makes a reply
            # inside this conversation "more about this one".
            category=EmailCategory.APPLIED,
        )
        # The second live card's own mail, on its own conversation, so the
        # employer is genuinely two-carded from the pipeline's point of view.
        await _add_mail(
            test_session,
            company=case.company,
            message_id=f"m-{case.company.lower()}-second",
            thread_id=f"{_thread_for(case.company)}-second",
            application_id=second,
            offset_minutes=index + 10,
            category=EmailCategory.APPLIED,
        )
    await test_session.commit()
    return seeds


def _escape_items() -> list[p.PipelineItem]:
    return [
        _arrival(case.company, _escape_arrival_id(case.company), _thread_for(case.company))
        for case in ESCAPE_CASES
    ]


@pytest.mark.asyncio
async def test_the_escape_fixture_reaches_the_rule_it_is_about(test_session, escapes) -> None:
    """The positive control, and the one this family is easiest to fake.

    ``known_threads`` is read only inside ``token in known_multi``. If the
    sender did not resolve to the stored employer's token, every arm below would
    take a branch that has nothing to do with dismissal and pass anyway.
    """

    known_multi, _ = await _sets(test_session)
    for case in ESCAPE_CASES:
        assert p.normalize_company_name(case.company) in known_multi, case.company

    # And each arrival really is anonymous — an item carrying a role or a
    # requisition number never asks the thread question in the first place.
    for item in _escape_items():
        assert p.extract_req_id(item.subject, item.snippet) is None
        assert p.role_from_message(item.subject, item.snippet) is None


@pytest.mark.asyncio
async def test_an_arrival_on_a_resync_dismissed_cards_thread_now_asks(
    test_session, escapes
) -> None:
    """DISPOSITION CHANGE, stated rather than discovered.

    Before: the thread was in the set, the arrival escaped the ambiguity rule
    and was filed onto the dismissed card, and ``upsert_applications_for_user``
    cleared the dismissal — a card back on the board that the user never asked
    for. After: it asks, and the answer lands where the human says.
    """

    # THE DISPOSITION FIRST, then the mechanism. Asserting the set before the
    # outcome would let a revert red on the mechanism line and never reach the
    # claim this test is actually making.
    known_multi, known_threads = await _sets(test_session)
    items = _escape_items()
    unplaceable = p.unplaceable_message_ids(items, known_multi, known_threads)
    assert _escape_arrival_id("Fernwick") in unplaceable
    assert _escape_arrival_id("Fernwick") in {
        r.message_id for r in p.collect_review_items(items, None, known_multi, known_threads)
    }
    assert "t-fernwick" not in known_threads


@pytest.mark.asyncio
async def test_an_arrival_on_a_hand_dismissed_cards_thread_now_asks(test_session, escapes) -> None:
    """The second disposition change: silent drop becomes a question.

    The suppression backstop only fires when the sub-keys match, so a keyed
    stored message and an unkeyed arrival differ and the arrival is stored and
    queued. Asking beside the cards the user can see is the settled answer for a
    card they removed by hand (#597).
    """

    known_multi, known_threads = await _sets(test_session)
    items = _escape_items()
    unplaceable = p.unplaceable_message_ids(items, known_multi, known_threads)
    assert _escape_arrival_id("Halloway") in unplaceable
    assert "t-halloway" not in known_threads


@pytest.mark.asyncio
async def test_an_arrival_inside_a_live_cards_own_conversation_is_still_filed(
    test_session, escapes
) -> None:
    """THE CORE FAMILY, and the twin that makes the two arms above directional.

    An employer replying inside its own confirmation names that application, and
    this is the whole reason the helper exists: without it every follow-up at a
    multi-application employer went to the queue, including the ones the mail
    answers by itself. A narrowing that reached this case would be a regression
    dressed as a fix.
    """

    known_multi, known_threads = await _sets(test_session)
    assert "t-glenmara" in known_threads

    items = _escape_items()
    arrival = _escape_arrival_id("Glenmara")
    assert arrival not in p.unplaceable_message_ids(items, known_multi, known_threads)

    rolled = p.roll_up_applications(items, known_multi, known_threads)
    landed = [r for r in rolled if any(m.message_id == arrival for m in r.messages)]
    assert len(landed) == 1, [r.company_token for r in rolled]
    assert landed[0].company_token == p.normalize_company_name("Glenmara")
    assert arrival not in {
        r.message_id for r in p.collect_review_items(items, None, known_multi, known_threads)
    }


# =============================================================================
# The resolve-time twin, which must stay UNFILTERED
# =============================================================================
#
# ``_application_in_conversation`` asks the same question this file's helper
# asks — "does this conversation name a card?" — and is deliberately NOT given
# the same dismissal narrowing. The asymmetry is in the callers: this file's
# helper feeds an escape FROM the review queue at a multi-live-card employer,
# where a dismissed card is not one of the options the user is choosing between.
# The twin feeds a resolver whose caller already reads the reason column, and in
# the zero- and one-live-card cases its routing is doctrine-correct — a
# resync-dismissed card landing mail is the intended resurrect (#595), and a
# hand-dismissed one is stopped by ``upsert_applications_for_user``'s
# ``continue`` (#597).
#
# THESE TESTS EXIST TO RED ON A UNIFICATION SWEEP. If a future "one predicate,
# N spellings" pass adds ``Application.dismissed_at.is_(None)`` to the twin, the
# first two go red and the resurrect path is defended.


def _rolled(company: str, thread_id: str) -> p.RolledApplication:
    """An anonymous cluster carrying one message on ``thread_id``.

    ``req_id`` and ``role_token`` are None, which is the only shape that
    consults the conversation at all — an identified cluster has a real key and
    does not need to guess.
    """

    return p.RolledApplication(
        company_token=p.normalize_company_name(company),
        company_display=company,
        role=None,
        status="applied",
        applied_at=ARRIVED_AT,
        last_activity=ARRIVED_AT,
        messages=(
            p.MessageRef(
                message_id=f"m-{company.lower()}-twin-arrival",
                thread_id=thread_id,
                subject=_blind_subject(company),
                sender_email=_sender_for(company),
                sender_name="Careers",
                received_at=ARRIVED_AT,
                category="rejection",
                confidence=GATED,
                snippet=BLIND_SNIPPET,
            ),
        ),
        req_id=None,
        role_token=None,
    )


async def _rows_for(session, company: str) -> list[Application]:
    return list(
        (
            await session.exec(
                select(Application).where(
                    Application.user_id == USER, Application.company == company
                )
            )
        ).all()
    )


@pytest.fixture
async def twin_seeds(test_session) -> dict[str, dict[str, int]]:
    """Three employers for the twin: a resync card, a hand card, an ambiguous pair."""

    seeds: dict[str, dict[str, int]] = {}

    for index, (company, reason) in enumerate((("Ilminster", "resync"), ("Juniperion", "user"))):
        row_id = await _add_card(test_session, company, reason=reason)
        seeds[company] = {"owner": row_id}
        await _add_mail(
            test_session,
            company=company,
            message_id=f"m-{company.lower()}-stored",
            thread_id=_thread_for(company),
            application_id=row_id,
            offset_minutes=index,
            category=EmailCategory.APPLIED,
        )

    first = await _add_card(test_session, "Kestrelby", reason=None)
    second = await _add_card(test_session, "Kestrelby", reason=None)
    seeds["Kestrelby"] = {"first": first, "second": second}
    for offset, row_id in enumerate((first, second)):
        await _add_mail(
            test_session,
            company="Kestrelby",
            message_id=f"m-kestrelby-{offset}",
            thread_id="t-kestrelby",
            application_id=row_id,
            offset_minutes=offset + 20,
            category=EmailCategory.APPLIED,
        )

    await test_session.commit()
    return seeds


@pytest.mark.asyncio
async def test_the_resolve_time_twin_still_finds_a_resync_dismissed_card(
    test_session, twin_seeds
) -> None:
    """THE RESURRECT PATH. Reds if a sweep narrows the twin to live rows.

    A machine's removal yields to newer evidence: mail arriving in the removed
    card's own conversation resolves onto that card, and the upsert un-dismisses
    it. That is #595's acceptance criterion, and it is why the twin is not given
    this file's narrowing.
    """

    rows = await _rows_for(test_session, "Ilminster")
    found = await apps_module._application_in_conversation(
        test_session, USER, _rolled("Ilminster", "t-ilminster"), rows
    )
    assert found is not None
    assert found.id == twin_seeds["Ilminster"]["owner"]


@pytest.mark.asyncio
async def test_the_resolve_time_twin_still_finds_a_hand_dismissed_card(
    test_session, twin_seeds
) -> None:
    """The other half of the asymmetry, so the comment on it is checkable.

    The twin returns a hand-dismissed row too. Nothing is filed onto it: the
    refusal lives one level up, in ``upsert_applications_for_user``'s
    ``continue`` and in ``_resolve_application_for_email``'s reading of the
    reason column, which is where a human's "no" is supposed to be enforced.
    """

    rows = await _rows_for(test_session, "Juniperion")
    found = await apps_module._application_in_conversation(
        test_session, USER, _rolled("Juniperion", "t-juniperion"), rows
    )
    assert found is not None
    assert found.id == twin_seeds["Juniperion"]["owner"]


@pytest.mark.asyncio
async def test_the_resolve_time_twin_refuses_an_ambiguous_conversation(
    test_session, twin_seeds
) -> None:
    """The directional control: the twin does not simply return whatever it finds.

    A conversation spanning two of the employer's rows names no single card and
    falls through to the cascade — the same refusal this file's helper makes,
    and the reason both are safe to leave asymmetric on dismissal alone.
    """

    rows = await _rows_for(test_session, "Kestrelby")
    assert len(rows) == 2
    found = await apps_module._application_in_conversation(
        test_session, USER, _rolled("Kestrelby", "t-kestrelby"), rows
    )
    assert found is None
