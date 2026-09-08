"""A reminder about a stage the board already shows is not a question — #517.

The owner's review queue held FOUR rows at one employer about ONE assessment,
beside an ``ASSESSMENT`` card for the same thing: "are you still interested at
<Employer>", "your <Employer> assessments expire in 24 hours", "reminder from
<Employer>", "your <Employer> application". Four threads, three senders, so
every component of ``pipeline.review_dedup_key`` differed and #454's key
correctly declined to collapse them. They are four conversations. What they are
not is four decisions: the queue's subtitle promises "your decision files them"
and no answer available for any of them changes a card.

WHY THIS FILE IS MOSTLY ABOUT WHERE THE MESSAGE GOES
----------------------------------------------------

The obvious fix — "if the card is already at or past the suggested stage, do
not queue it" — LOSES THE MAIL. Filing and queueing are mutually exclusive
upstream: ``collect_review_items`` skips every item ``_qualifies_for_hard_row``
accepts, so a message that is neither filed nor queued gets no ``emails`` row,
no card, no counter and no log line. That is the one terminal drop
``cloud/pipeline`` documents, and trading four useless questions for four
vanished messages is strictly worse than the noise.

So the shape is an ATTACH. ``attach_reminders_to_their_cards`` links the message
to the employer's existing application: the card gains it, the queue loses it,
and ``Application.status`` does not move. Both halves are asserted here, always
together — "absent from the queue" alone is the bug this file exists to prevent,
and only :func:`test_the_reminder_reaches_the_card_and_leaves_the_queue` can
tell the fix from it.

THE POPULATION, ENUMERATED RATHER THAN REASONED ABOUT
-----------------------------------------------------

:data:`REMINDER_TABLE` is every ``(card status, incoming status)`` pair the
product can produce — 8 statuses from :class:`ApplicationStatus` against the 5
distinct statuses :data:`CATEGORY_TO_STATUS` maps to — with the verdict written
out as a literal. 10 of the 40 cells are reminders. Written out and not derived
from ``advance_application_status``: an expectation computed from the code it
checks compares the code to itself and is green on every edit.

The three categories ``CATEGORY_TO_STATUS`` does not map — ``other``,
``follow_up``, ``needs_review`` — assert no stage, so they are not in the table
and can never be attached. That is not a detail. The independent corpus's 260
``rescinded-offer`` withdrawals (an offer pulled back, quoting its own history)
score ``other`` at 0.50 and reach the queue on the ATS floor; a predicate
written on stage RANKS would have to argue about them, and this one cannot see
them at all. :func:`test_a_verdict_that_asserts_no_stage_is_never_attached` is
that claim, executable.

THE ADJACENT HALF OF #517 IS NOT HERE
--------------------------------------

The issue also reports a student-verification refusal from a consumer service
reaching this queue at ``REJECTION`` 0.70. That is #522, fixed in PR #909, and
``test_a_verification_refusal_is_not_a_rejection_522.py`` is where it lives.
Nothing in this file re-fixes it.

Test data
---------

Wholly invented employers on RFC-reserved, un-routable ``.test`` domains, per
``docs/TEST_DATA_POLICY.md``. No wording, employer or address here comes from a
real mailbox. Addresses are written out one literal at a time rather than
interpolated, because ``scripts/check_test_data.py`` matches addresses IN THE
TEXT and an f-string address is invisible to it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from jobtracker.cloud import applications as A
from jobtracker.cloud import pipeline
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    CATEGORY_TO_STATUS,
    Email,
    EmailCategory,
    EmailSource,
)

# ---------------------------------------------------------------------------
# The population
# ---------------------------------------------------------------------------

#: ``(card status, incoming status) -> is this message a REMINDER?``
#:
#: Every cell written out. 10 True, 30 False. The four rows of #517 are the
#: ``assessment`` row's first two entries; the terminal block at the bottom is
#: all False because a mail signal may never move a settled row, so "the
#: function declined to move it" must not be read as "there was nothing to say"
#: — an offer arriving at a rejected card is the most newsworthy message this
#: product can receive (#814).
REMINDER_TABLE: dict[tuple[str, str], bool] = {
    ("applied", "applied"): True,
    ("applied", "assessment"): False,
    ("applied", "interviewing"): False,
    ("applied", "offered"): False,
    ("applied", "rejected"): False,
    ("assessment", "applied"): True,
    ("assessment", "assessment"): True,
    ("assessment", "interviewing"): False,
    ("assessment", "offered"): False,
    ("assessment", "rejected"): False,
    ("interviewing", "applied"): True,
    ("interviewing", "assessment"): True,
    ("interviewing", "interviewing"): True,
    ("interviewing", "offered"): False,
    ("interviewing", "rejected"): False,
    ("offered", "applied"): True,
    ("offered", "assessment"): True,
    ("offered", "interviewing"): True,
    ("offered", "offered"): True,
    ("offered", "rejected"): False,
    ("rejected", "applied"): False,
    ("rejected", "assessment"): False,
    ("rejected", "interviewing"): False,
    ("rejected", "offered"): False,
    ("rejected", "rejected"): False,
    ("accepted", "applied"): False,
    ("accepted", "assessment"): False,
    ("accepted", "interviewing"): False,
    ("accepted", "offered"): False,
    ("accepted", "rejected"): False,
    ("withdrawn", "applied"): False,
    ("withdrawn", "assessment"): False,
    ("withdrawn", "interviewing"): False,
    ("withdrawn", "offered"): False,
    ("withdrawn", "rejected"): False,
    ("ghosted", "applied"): False,
    ("ghosted", "assessment"): False,
    ("ghosted", "interviewing"): False,
    ("ghosted", "offered"): False,
    ("ghosted", "rejected"): False,
}


def test_the_table_covers_every_pair_the_product_can_make() -> None:
    """The population is CLOSED, so a new status cannot slip past the table.

    Without this the table is a list of cases somebody thought of, and adding a
    status to :class:`ApplicationStatus` or a category to
    :data:`CATEGORY_TO_STATUS` would leave the new pairs ungraded and green.
    """

    expected = {
        (card.value, incoming.value)
        for card in ApplicationStatus
        for incoming in set(CATEGORY_TO_STATUS.values())
    }
    assert set(REMINDER_TABLE) == expected
    assert len(REMINDER_TABLE) == 40
    assert sum(REMINDER_TABLE.values()) == 10


@pytest.mark.parametrize(("pair", "expected"), sorted(REMINDER_TABLE.items()))
def test_the_predicate_matches_the_enumerated_population(
    pair: tuple[str, str], expected: bool
) -> None:
    card, incoming = pair
    assert pipeline.would_not_move_the_card(card, incoming) is expected


def test_the_four_rows_of_517_are_all_reminders() -> None:
    """The issue's own table, against a card at ``assessment``.

    Three ``ASSESSMENT`` proposals and one ``APPLIED``; the card is at
    ``assessment``. No answer to any of them moves it.
    """

    card = "assessment"
    for category in ("assessment", "assessment", "assessment", "applied"):
        incoming = CATEGORY_TO_STATUS[EmailCategory(category)].value
        assert pipeline.would_not_move_the_card(card, incoming) is True, category


def test_a_rejection_at_a_live_card_is_always_news() -> None:
    """The one downgrade mail may make. It must never be silenced."""

    for card in ("applied", "assessment", "interviewing", "offered"):
        assert pipeline.would_not_move_the_card(card, "rejected") is False, card


def test_an_offer_at_a_settled_card_is_always_news() -> None:
    """#814, and the reason the terminal guard is not a shortcut.

    ``advance_application_status`` returns a terminal status unchanged for every
    signal, so without the guard the equality would call this a reminder.
    """

    for card in ("rejected", "accepted", "withdrawn", "ghosted"):
        assert pipeline.advance_application_status(card, "offered") == card, card
        assert pipeline.would_not_move_the_card(card, "offered") is False, card


# ---------------------------------------------------------------------------
# The employer index the sweep is bounded by
# ---------------------------------------------------------------------------

#: ``(company name, token)`` pairs spanning both arms of the rule and both ways
#: of failing it. The tails are the shapes ``matches_company_token``'s own
#: docstring names — a display name against a domain brand, and a leading-word
#: match — plus names that normalize to nothing.
_MATCH_PAIRS = [
    ("Halvern Systems", "halvern"),
    ("Halvern Systems", "halvern systems"),
    ("Halvern Systems", "ostrow"),
    ("Ostrow", "ostrow"),
    ("Ostrow Labs", "ostrow"),
    ("Ostrow Labs", "ostrowlabs"),
    ("Y Combinator", "y-combinator"),
    ("Together AI", "together"),
    ("Together AI", "togetherai"),
    ("", "halvern"),
    ("Halvern Systems", ""),
    ("   ", "  "),
]


@pytest.mark.parametrize(("company", "token"), _MATCH_PAIRS)
def test_the_index_decides_exactly_what_the_matcher_decides(
    company: str, token: str
) -> None:
    """The bound must not become a second rule.

    ``attach_reminders_to_their_cards`` indexes the board with
    ``company_match_keys`` instead of scanning it with ``matches_company_token``
    — a linear scan measured SLOWER than the database lookups it replaced. The
    two answers have to be the same answer, so they are executed side by side.
    ``None`` keys mean "matches nothing", never a wildcard.
    """

    left = pipeline.company_match_keys(company)
    right = pipeline.company_match_keys(token)
    indexed = (
        left is not None
        and right is not None
        and (left[0] == right[0] or left[1] == right[1])
    )
    assert indexed is pipeline.matches_company_token(company, token)


# ---------------------------------------------------------------------------
# The attach, against a database
# ---------------------------------------------------------------------------

OWNER = uuid.UUID("00000000-0000-4000-8000-0000005170a1")

_WHEN = datetime(2026, 4, 6, 10, 30)

#: One employer, one card, four conversations — #517's shape, invented.
HALVERN = "Halvern Systems"
HALVERN_TOKEN = "halvern"

#: Four senders' worth of the same assessment. Literal addresses (see module
#: docstring): three distinct ones, as the issue reports.
FOUR_ROWS = (
    ("m517-a", "th-517-a", "Are you still interested in a position at Halvern Systems?", "noreply@halvern.test", EmailCategory.ASSESSMENT),
    ("m517-b", "th-517-b", "[Action Required] Your Halvern Systems Assessments Expire in 24 hours", "assessment-support@halvern.test", EmailCategory.ASSESSMENT),
    ("m517-c", "th-517-c", "Reminder from Halvern Systems!", "assessment@halvern.test", EmailCategory.ASSESSMENT),
    ("m517-d", "th-517-d", "[Action Required] Your Halvern Systems Application", "noreply@halvern.test", EmailCategory.APPLIED),
)

_SNIPPET = (
    "Your assessment window is still open. Sign in to the candidate portal to "
    "pick up where you left off."
)


async def _card(
    session,
    *,
    company: str = HALVERN,
    status: ApplicationStatus = ApplicationStatus.ASSESSMENT,
    source: str = "gmail",
    dismissed_at: datetime | None = None,
    dismissed_reason: str | None = None,
    req_id: str | None = None,
    role_token: str | None = None,
    position: str = "",
) -> Application:
    row = Application(
        user_id=OWNER,
        company=company,
        position=position,
        status=status,
        source=source,
        dismissed_at=dismissed_at,
        dismissed_reason=dismissed_reason,
        req_id=req_id,
        role_token=role_token,
    )
    session.add(row)
    await session.flush()
    return row


async def _queued(
    session,
    message_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    suggested: EmailCategory | None,
    *,
    snippet: str = _SNIPPET,
    identity_role: str | None = "",
    identity_req_id: str | None = "",
    received_at: datetime | None = None,
) -> Email:
    """A row as the two review persists write one: unlinked, needs_review."""

    row = Email(
        user_id=OWNER,
        application_id=None,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=thread_id,
        subject=subject,
        sender_email=sender,
        sender_name="Halvern Systems Talent",
        received_at=received_at or _WHEN,
        body_snippet=snippet,
        identity_role=identity_role,
        identity_req_id=identity_req_id,
        classified_as=EmailCategory.NEEDS_REVIEW,
        suggested_category=suggested,
        classification_confidence=0.70,
        is_reviewed=False,
    )
    session.add(row)
    await session.flush()
    return row


async def _reload(session, message_id: str) -> Email:
    rows = (
        await session.exec(
            select(Email).where(
                Email.user_id == OWNER, Email.message_id == message_id
            )
        )
    ).all()
    assert len(rows) == 1, f"expected one row for {message_id}, got {len(rows)}"
    return rows[0]


async def _still_in_the_queue(session, message_id: str) -> bool:
    """The queue's OWN predicate, imported rather than retyped.

    ``test_read_path_indexes_postgres.py`` drifted for a year by restating a
    handler's WHERE clause as literals; the predicate function is read from its
    definition site so this cannot.
    """

    rows = (
        await session.exec(
            select(Email.message_id).where(
                Email.user_id == OWNER,
                Email.classified_as == EmailCategory.NEEDS_REVIEW,
                A._not_filed_on_an_application_that_answers(OWNER),
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean
                Email.message_id == message_id,
            )
        )
    ).all()
    return bool(rows)


@pytest.mark.asyncio
async def test_the_reminder_reaches_the_card_and_leaves_the_queue(
    test_session,
) -> None:
    """BOTH HALVES, and they are one test on purpose.

    "Absent from the queue" alone is satisfied by the bug this fix exists to
    avoid — a message dropped on the floor. Only the card half tells the two
    apart, so they are asserted together and neither can pass without the other.
    """

    card = await _card(test_session)
    for message_id, thread_id, subject, sender, suggested in FOUR_ROWS:
        await _queued(test_session, message_id, thread_id, subject, sender, suggested)

    attached, of_arrived = await A.attach_reminders_to_their_cards(
        test_session, OWNER, frozenset(row[0] for row in FOUR_ROWS)
    )
    await test_session.commit()

    assert attached == 4
    assert of_arrived == 4
    for message_id, *_ in FOUR_ROWS:
        row = await _reload(test_session, message_id)
        assert row.application_id == card.id, f"{message_id} reached no card"
        assert not await _still_in_the_queue(
            test_session, message_id
        ), f"{message_id} is still being asked about"


@pytest.mark.asyncio
async def test_the_card_does_not_move_and_no_verdict_is_invented(
    test_session,
) -> None:
    """The stage is untouched, and nothing stamps a decision nobody made."""

    card = await _card(test_session)
    await _queued(test_session, *FOUR_ROWS[0][:4], FOUR_ROWS[0][4])

    await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert card.status == ApplicationStatus.ASSESSMENT
    row = await _reload(test_session, "m517-a")
    # ``classified_as`` is the COMMITTED verdict and NEEDS_REVIEW is its typed
    # null. The proposal stays where a proposal belongs.
    assert row.classified_as == EmailCategory.NEEDS_REVIEW
    assert row.suggested_category == EmailCategory.ASSESSMENT
    # No human reviewed anything, so nothing may say one did.
    assert row.is_reviewed is False
    assert row.user_corrected is False
    assert row.review_disposition is None


@pytest.mark.asyncio
async def test_the_attached_message_is_retrievable_from_the_card(
    test_session,
) -> None:
    """It is ON the card, not merely pointing at it.

    The card's detail view reads ``Email.application_id``, so this is the read
    a user actually makes when they open the row.
    """

    card = await _card(test_session)
    await _queued(test_session, *FOUR_ROWS[2][:4], FOUR_ROWS[2][4])
    await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    on_the_card = (
        await test_session.exec(
            select(Email.message_id).where(
                Email.user_id == OWNER, Email.application_id == card.id
            )
        )
    ).all()
    assert list(on_the_card) == ["m517-c"]


@pytest.mark.asyncio
async def test_a_signal_that_advances_the_card_stays_in_the_queue(
    test_session,
) -> None:
    """THE CONTROL THAT MATTERS. One field apart from the case above."""

    await _card(test_session)
    await _queued(
        test_session,
        "m517-interview",
        "th-517-e",
        "Scheduling your Halvern Systems interview",
        "noreply@halvern.test",
        EmailCategory.INTERVIEW,
    )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    row = await _reload(test_session, "m517-interview")
    assert row.application_id is None
    assert await _still_in_the_queue(test_session, "m517-interview")


@pytest.mark.asyncio
async def test_a_rejection_stays_in_the_queue(test_session) -> None:
    """The boundary in the other direction: the one downgrade mail may make."""

    await _card(test_session)
    await _queued(
        test_session,
        "m517-reject",
        "th-517-f",
        "An update on your Halvern Systems application",
        "noreply@halvern.test",
        EmailCategory.REJECTION,
    )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    assert await _still_in_the_queue(test_session, "m517-reject")


@pytest.mark.asyncio
async def test_an_offer_at_a_rejected_card_stays_in_the_queue(test_session) -> None:
    """#814. The terminal guard, at a database rather than at the predicate."""

    await _card(test_session, status=ApplicationStatus.REJECTED)
    await _queued(
        test_session,
        "m517-offer",
        "th-517-g",
        "Your offer from Halvern Systems",
        "noreply@halvern.test",
        EmailCategory.OFFER,
    )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    assert await _still_in_the_queue(test_session, "m517-offer")


@pytest.mark.asyncio
async def test_a_verdict_that_asserts_no_stage_is_never_attached(
    test_session,
) -> None:
    """``other`` / ``follow_up`` / no proposal at all.

    The corpus's rescinded offers live here: a withdrawal quoting the offer it
    withdraws scores ``other`` 0.50 and reaches the queue on the ATS floor. A
    message that names no stage cannot be compared to one, so this pass cannot
    reach it — and the card that overstates the outcome keeps the question that
    can correct it.
    """

    await _card(test_session, status=ApplicationStatus.OFFERED)
    for message_id, suggested in (
        ("m517-other", EmailCategory.OTHER),
        ("m517-followup", EmailCategory.FOLLOW_UP),
        ("m517-none", None),
    ):
        await _queued(
            test_session,
            message_id,
            f"th-{message_id}",
            "Re: Your offer from Halvern Systems",
            "noreply@halvern.test",
            suggested,
        )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    for message_id in ("m517-other", "m517-followup", "m517-none"):
        assert await _still_in_the_queue(test_session, message_id), message_id


@pytest.mark.asyncio
async def test_no_card_means_no_attach_and_no_new_card(test_session) -> None:
    """A reminder about nothing is not a reminder. This pass NEVER mints."""

    await _queued(test_session, *FOUR_ROWS[0][:4], FOUR_ROWS[0][4])
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    assert await _still_in_the_queue(test_session, "m517-a")
    cards = (
        await test_session.exec(
            select(Application.id).where(Application.user_id == OWNER)
        )
    ).all()
    assert list(cards) == []


@pytest.mark.asyncio
async def test_a_blind_landing_stays_in_the_queue(test_session) -> None:
    """"Which of your applications?" is the queue's question, not this pass's.

    Two live cards at one employer and a message naming no role: the cascade
    would pick the oldest by tie-break. Filing on a coin toss AND removing the
    question is the worst of both.
    """

    await _card(test_session, role_token="backend engineer", position="Backend Engineer")
    await _card(test_session, role_token="platform engineer", position="Platform Engineer")
    await _queued(
        test_session,
        "m517-blind",
        "th-517-h",
        "Reminder from Halvern Systems!",
        "noreply@halvern.test",
        EmailCategory.ASSESSMENT,
        snippet="Your window is still open. Sign in to continue.",
    )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    assert await _still_in_the_queue(test_session, "m517-blind")


@pytest.mark.asyncio
async def test_a_card_off_the_board_does_not_take_the_reminder(
    test_session,
) -> None:
    """#595: a message that leaves the queue and reaches no screen is worse."""

    await _card(
        test_session,
        dismissed_at=datetime(2026, 4, 1, 9, 0),
        dismissed_reason="resync",
    )
    await _queued(test_session, *FOUR_ROWS[0][:4], FOUR_ROWS[0][4])
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 0
    assert await _still_in_the_queue(test_session, "m517-a")


@pytest.mark.asyncio
async def test_what_the_reminder_names_arrives_with_it(test_session) -> None:
    """The issue's counter-case: a reminder can carry what the card lacks.

    The card is anonymous and untitled; the message names a requisition id and a
    role. Attaching without this drops exactly the information the issue says
    makes a reminder more than a reminder.
    """

    card = await _card(test_session)
    assert card.req_id is None and card.position == ""
    await _queued(
        test_session,
        "m517-req",
        "th-517-i",
        "Reminder from Halvern Systems!",
        "noreply@halvern.test",
        EmailCategory.ASSESSMENT,
        identity_role="Backend Engineer",
        identity_req_id="R-40080",
    )
    attached, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert attached == 1
    assert card.req_id == "R-40080"
    assert card.position == "Backend Engineer"
    assert card.role_token == pipeline.normalize_role_token("Backend Engineer")


@pytest.mark.asyncio
async def test_the_pass_is_idempotent(test_session) -> None:
    """A second run finds nothing: the row it linked no longer matches."""

    await _card(test_session)
    await _queued(test_session, *FOUR_ROWS[0][:4], FOUR_ROWS[0][4])
    first, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    second, _ = await A.attach_reminders_to_their_cards(test_session, OWNER)
    await test_session.commit()

    assert (first, second) == (1, 0)


# ---------------------------------------------------------------------------
# Placement: BOTH sync entrypoints, and the receipt they hand back
# ---------------------------------------------------------------------------
#
# A pass nothing calls is a pass that does not exist. These two are what stop
# the call sites from being deleted as redundant, and they are separate tests
# because the two entrypoints are separate code paths: the routine/auto sync
# every user hits, and the explicit "Re-sync" button, which CLEARS and restates
# the queue and would otherwise undo the fix on the next press.


def _reminder_item(
    message_id: str, thread_id: str, category: str = "assessment"
) -> pipeline.ReviewItem:
    return pipeline.ReviewItem(
        message_id=message_id,
        thread_id=thread_id,
        subject="Reminder from Halvern Systems!",
        sender_email="noreply@halvern.test",
        sender_name="Halvern Systems Talent",
        received_at=_WHEN,
        category=category,
        confidence=0.70,
        company_display=HALVERN,
        snippet=_SNIPPET,
    )


@pytest.mark.asyncio
async def test_the_routine_sync_files_the_reminder(test_session) -> None:
    card = await _card(test_session)
    merged = await A.sync_gmail_pipeline_additive(
        test_session, OWNER, [], [_reminder_item("m517-sync", "th-517-sync")]
    )

    row = await _reload(test_session, "m517-sync")
    assert row.application_id == card.id, "the routine sync never calls the pass"
    assert not await _still_in_the_queue(test_session, "m517-sync")
    # THE RECEIPT AGREES WITH THE QUEUE. A row surfaced and then filed in one
    # pass was never in the queue the user is being told the size of, and two
    # renderers of one number disagreeing is this repo's recurring defect.
    assert merged.needs_review == 0


@pytest.mark.asyncio
async def test_the_resync_files_the_reminder_too(test_session) -> None:
    card = await _card(test_session)
    merged = await A.purge_and_rebuild_gmail_pipeline(
        test_session, OWNER, [], [_reminder_item("m517-rebuild", "th-517-rebuild")]
    )

    row = await _reload(test_session, "m517-rebuild")
    assert row.application_id == card.id, "Re-sync would put the question back"
    assert not await _still_in_the_queue(test_session, "m517-rebuild")
    assert merged.needs_review == 0


@pytest.mark.asyncio
async def test_the_receipt_still_counts_a_real_question(test_session) -> None:
    """The control for the two counts above: a row that IS a question.

    Without it, ``needs_review == 0`` is satisfied by a sync that surfaces
    nothing at all, and the accounting assertion proves nothing.
    """

    await _card(test_session)
    asking = _reminder_item("m517-asking", "th-517-asking", category="interview")
    merged = await A.sync_gmail_pipeline_additive(test_session, OWNER, [], [asking])

    assert merged.needs_review == 1
    assert await _still_in_the_queue(test_session, "m517-asking")


# ---------------------------------------------------------------------------
# The attach must not settle the conversation
# ---------------------------------------------------------------------------
#
# This is the half a naive attach gets wrong, and it was found by execution
# rather than by reading. ``_persist_review_items_additive`` refuses an arriving
# ref whose (thread, application) key matches a SETTLED stored row, and the
# refusal happens before ``_persist_message_refs`` — so the message gets no row
# at all (#630). Attaching a reminder makes its row "filed on an application
# that answers"; without a carve-out, the next 0.70 rejection on that thread is
# destroyed by a link the machine made and nobody saw.

_SIB_THREAD = "th-517-sibling"
_SIB_SUBJECT = "Reminder from Halvern Systems!"


async def _sibling_arm(session, *, verdict: EmailCategory | None) -> bool:
    """Seed one stored sibling and offer an arriving rejection on its thread.

    ``verdict is None`` seeds the row UNLINKED. Otherwise the row is linked to a
    live card and stored under ``verdict``. Returns whether the arriving message
    got a row at all.
    """

    card = await _card(session)
    row = await _queued(
        session,
        "m517-sib-old",
        _SIB_THREAD,
        _SIB_SUBJECT,
        "noreply@halvern.test",
        EmailCategory.ASSESSMENT,
    )
    if verdict is not None:
        row.application_id = card.id
        row.classified_as = verdict
        session.add(row)
        await session.flush()

    arriving = pipeline.ReviewItem(
        message_id="m517-sib-new",
        thread_id=_SIB_THREAD,
        subject=_SIB_SUBJECT,
        sender_email="noreply@halvern.test",
        sender_name="Halvern Systems Talent",
        received_at=_WHEN + timedelta(days=3),
        category="rejection",
        confidence=0.70,
        company_display=HALVERN,
        snippet=_SNIPPET,
    )
    await A._persist_review_items_additive(session, OWNER, [arriving])
    await session.commit()
    stored = (
        await session.exec(
            select(Email.id).where(
                Email.user_id == OWNER, Email.message_id == "m517-sib-new"
            )
        )
    ).all()
    return bool(stored)


def test_the_two_siblings_really_share_a_key() -> None:
    """POSITIVE CONTROL. Without a collision the arms below prove nothing."""

    stored = pipeline.review_dedup_key(
        message_id="m517-sib-old",
        thread_id=_SIB_THREAD,
        subject=_SIB_SUBJECT,
        snippet=_SNIPPET,
        identity_role="",
        identity_req_id="",
    )
    arriving = pipeline.review_dedup_key(
        message_id="m517-sib-new",
        thread_id=_SIB_THREAD,
        subject=_SIB_SUBJECT,
        snippet=_SNIPPET,
        identity_role=None,
        identity_req_id=None,
    )
    assert stored == arriving


@pytest.mark.asyncio
async def test_an_attached_reminder_does_not_destroy_its_thread_s_next_message(
    test_session,
) -> None:
    """The row the machine linked carries no verdict, so it answers for nothing."""

    assert await _sibling_arm(test_session, verdict=EmailCategory.NEEDS_REVIEW)


@pytest.mark.asyncio
async def test_an_unlinked_sibling_never_suppressed_anything(test_session) -> None:
    """The arm that differs by ONE field, so the one above is not vacuous."""

    assert await _sibling_arm(test_session, verdict=None)


@pytest.mark.asyncio
async def test_a_filed_sibling_still_settles_its_conversation(test_session) -> None:
    """#630's behaviour, UNCHANGED. A committed verdict still answers.

    This is the arm that stops the carve-out from being "delete the settled
    filter": a thread-mate the sync FILED at or above the auto-file gate carries
    a real category, and it still suppresses.
    """

    assert not await _sibling_arm(test_session, verdict=EmailCategory.APPLIED)


# ---------------------------------------------------------------------------
# The whole cycle, through the real endpoints
# ---------------------------------------------------------------------------

#: At least 32 bytes: the HS256 verifier refuses a shorter key and every
#: request comes back 401 with nothing saying why.
JWT_SECRET = "a-reminder-is-not-a-question-517-secret-key"


def _token_for(user_id: str) -> str:
    """A Supabase-shaped HS256 JWT.

    ``time.time()`` and NOT ``datetime.utcnow().timestamp()``: the latter reads
    a naive-UTC value as LOCAL time, so west of UTC every claim lands hours in
    the future and PyJWT answers ``Invalid token`` with nothing saying why.
    """

    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory test DB — the form #582 requires.

    Patched on every settings instance the request path reads, because a module
    earlier in collection order may have reloaded ``jobtracker.config`` and left
    the auth verifier holding a different object.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "environment", "test")
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "supabase_jwt_secret", JWT_SECRET)

    connection_module._engine = None

    from jobtracker.database import init_db

    await init_db()

    import jobtracker.main_cloud as main_cloud_module

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


@pytest.mark.asyncio
async def test_the_queue_and_the_card_agree_over_http(client: AsyncClient) -> None:
    """The two screens, read as the product renders them.

    The direct-session tests above read the predicate; this one reads the
    ENDPOINTS, because a fix that satisfies a WHERE clause and not the handler
    is the shape this repo keeps shipping.
    """

    from jobtracker.database import get_session

    headers = {"Authorization": f"Bearer {_token_for(str(OWNER))}"}

    async with get_session() as session:
        card = await _card(session)
        for message_id, thread_id, subject, sender, suggested in FOUR_ROWS:
            await _queued(session, message_id, thread_id, subject, sender, suggested)
        await session.commit()
        card_id = card.id

    before = await client.get("/applications/review", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["total"] == 4

    async with get_session() as session:
        attached, _ = await A.attach_reminders_to_their_cards(session, OWNER)
        await session.commit()
    assert attached == 4

    after = await client.get("/applications/review", headers=headers)
    assert after.status_code == 200
    assert after.json()["total"] == 0, "the queue still asks about the reminders"

    detail = await client.get(f"/applications/{card_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert {m["message_id"] for m in body["messages"]} == {
        row[0] for row in FOUR_ROWS
    }, "the reminders left the queue and reached no card"
    # And the card did not move.
    assert body["application"]["status"] == "assessment"
