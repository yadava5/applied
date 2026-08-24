"""A title printed past Gmail's snippet must still reach the board.

THE REPORT. Torc Robotics' card carried no position while its mail spelled the
title out. Pulled from the owner's mailbox on 2026-08-23:

    Your application has been received and will be reviewed by our Recruiting
    staff. If you are chosen to move forward in the interview process for the
    Software Engineer I - Metrics for Release opportunity, we will contact you
    soon.

That sentence begins at body character ~380. The stored snippet is 199
characters. No pattern was missing — ``role_from_message`` returns the right
answer the instant it is handed the body:

    Torc stored snippet -> None
    Torc FULL body      -> 'Software Engineer I - Metrics for Release'

THE MECHANISM. ``_classify_messages`` handed the classifier the body and handed
the ``PipelineItem`` ``msg.snippet``. So the half of the product that decides
WHICH APPLICATION a message is about ran on the least information available to
it, while the half that decides what KIND of message it is ran on the most.

Measured across the independent corpus once its harness stopped handing the
identity layer the full body: 50 applications split over two cards, 50 updates
opening a rival card beside the one they belong on, and 81 further updates
pushed into the review queue on top of the 371 that honestly belong there
(``RECORDED["update_held"]`` is 371, and it is a designed floor: mail that
genuinely names nothing at an employer with several cards is SUPPOSED to be
asked about rather than guessed at).

WHY THE ANSWER IS STORED RATHER THAN PASSED. Deriving from the body and keeping
the result in flight recreates a failure this repository has already measured.
``pipeline.STORED_SNIPPET_CHARS`` records it: a key computed from one width of
text when a decision is QUEUED and another width when it is SETTLED leaves the
row unlinked and un-reviewed, re-queued on every sync forever. The queue side
would hold a body-derived token and the settle side, recomputing from the
stored snippet, would hold None.

WHY NULL AND EMPTY STRING ARE DIFFERENT, which is the part most likely to be
"simplified" later and is therefore pinned hardest below. NULL means no
derivation was ever made for this row — it predates the columns, or it came
through the client relay, which carries a snippet and never had a body. Empty
string means a reader looked and the message names nothing, which is the normal
permanent state for mail like Google's acknowledgement. Collapsing the two would
send every already-stored row back to re-deriving from a snippet, forever.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from jobtracker.cloud.pipeline import (
    PipelineItem,
    identity_or_derive,
    item_identity,
    partition_applications,
    review_dedup_key,
    role_from_message,
)

TORC_SNIPPET = (
    "Hi Ayush, Thank you for beginning your application process with Torc "
    "Robotics! We are excited to learn more about your interests and how your "
    "skill set will best contribute to our vision of being the"
)

TORC_BODY = (
    TORC_SNIPPET
    + " world's leading autonomous trucking solution. Your application has been "
    "received and will be reviewed by our Recruiting staff. If you are chosen "
    "to move forward in the interview process for the Software Engineer I - "
    "Metrics for Release opportunity, we will contact you soon."
)

TORC_ROLE = "Software Engineer I - Metrics for Release"


def _item(
    message_id: str,
    *,
    subject: str,
    snippet: str,
    category: str = "applied",
    thread_id: str | None = "t-torc",
    identity_role: str | None = None,
    identity_req_id: str | None = None,
    day: int = 11,
) -> PipelineItem:
    return PipelineItem(
        message_id=message_id,
        category=category,
        sender_email="no-reply@torc.ai",
        subject=subject,
        sender_name="Torc Robotics",
        received_at=datetime(2026, 8, day, 5, 37),
        confidence=0.95,
        thread_id=thread_id,
        snippet=snippet,
        identity_role=identity_role,
        identity_req_id=identity_req_id,
    )


class TestTheDefect:
    def test_the_snippet_does_not_contain_the_title(self) -> None:
        """The premise. If this ever fails the rest measures nothing."""

        assert role_from_message("Thank you for applying to Torc Robotics!", TORC_SNIPPET) is None

    def test_the_shipped_extractor_reads_it_from_the_body(self) -> None:
        """No pattern was missing. The text never arrived."""

        assert (
            role_from_message("Thank you for applying to Torc Robotics!", TORC_BODY)
            == TORC_ROLE
        )

    def test_the_card_carries_the_title_the_body_named(self) -> None:
        """End of the chain, and the only part the user can see."""

        clusters, unplaced = partition_applications(
            [
                _item(
                    "m1",
                    subject="Thank you for applying to Torc Robotics!",
                    snippet=TORC_SNIPPET,
                    identity_role=TORC_ROLE,
                    identity_req_id="",
                )
            ]
        )

        assert unplaced == []
        assert [c.role for c in clusters] == [TORC_ROLE]


class TestNullIsNotEmptyString:
    """The distinction the whole design rests on."""

    def test_null_means_never_derived_and_falls_back_to_the_snippet(self) -> None:
        """A relay item, and every row written before the columns existed."""

        assert (
            identity_or_derive(
                req_id=None,
                role=None,
                subject="Your application has been received",
                snippet="Thanks for applying to our role: Backend Engineer.",
            )
            == "backend engineer"
        )

    def test_empty_string_means_derived_and_names_nothing(self) -> None:
        """It must NOT go back to the snippet and find a second answer.

        This is the case that would silently reintroduce two derivations for one
        message: a reader that looked at the body and found no title, and a
        fallback that then reads a different text and finds one.
        """

        assert (
            identity_or_derive(
                req_id="",
                role="",
                subject="Your application has been received",
                snippet="Thanks for applying to our role: Backend Engineer.",
            )
            is None
        )

    def test_a_derived_answer_beats_whatever_the_snippet_says(self) -> None:
        assert (
            identity_or_derive(
                req_id="",
                role=TORC_ROLE,
                subject="Thank you for applying to Torc Robotics!",
                snippet=TORC_SNIPPET,
            )
            == "software engineer i metrics for release"
        )


class TestTheQueueAndTheBoardAgree:
    """Both sides of a decision must read one value — the #454 discipline."""

    def test_the_dedup_key_uses_the_derivation(self) -> None:
        """Queue side, holding what the reader derived."""

        assert review_dedup_key(
            message_id="m1",
            thread_id="t-torc",
            subject="Thank you for applying to Torc Robotics!",
            snippet=TORC_SNIPPET,
            identity_role=TORC_ROLE,
            identity_req_id="",
        ) == ("t-torc", "software engineer i metrics for release")

    def test_without_a_derivation_it_is_exactly_what_it_always_was(self) -> None:
        """Settle side for an un-derived row, and the relay path.

        The fallback must be the OLD behaviour, not a third answer, or every
        pre-existing row changes meaning the day the columns ship.
        """

        assert review_dedup_key(
            message_id="m1",
            thread_id="t-torc",
            subject="Thank you for applying to Torc Robotics!",
            snippet=TORC_SNIPPET,
        ) == ("t-torc", None)

    def test_the_two_sides_agree_on_the_same_message(self) -> None:
        """The failure STORED_SNIPPET_CHARS records, asserted directly.

        A queue key of ``(thread, token)`` settled against ``(thread, None)``
        leaves the row unlinked, un-reviewed and re-queued on every sync. The
        columns exist so both computations read one stored value.
        """

        queued = review_dedup_key(
            message_id="m1",
            thread_id="t-torc",
            subject="Thank you for applying to Torc Robotics!",
            snippet=TORC_SNIPPET,
            identity_role=TORC_ROLE,
            identity_req_id="",
        )
        settled = review_dedup_key(
            message_id="m1",
            thread_id="t-torc",
            # what the DATABASE holds — the snippet, not the body
            subject="Thank you for applying to Torc Robotics!",
            snippet=TORC_SNIPPET[:500],
            identity_role=TORC_ROLE,
            identity_req_id="",
        )

        assert queued == settled


class TestARequisitionStillWins:
    """The cascade order is unchanged by where the parts came from."""

    def test_the_requisition_beats_the_role(self) -> None:
        assert (
            identity_or_derive(
                req_id="10464043", role=TORC_ROLE, subject="", snippet=""
            )
            == "10464043"
        )

    @pytest.mark.parametrize("empty", ["", None])
    def test_an_absent_requisition_falls_through_to_the_role(self, empty) -> None:
        assert (
            identity_or_derive(req_id=empty, role=TORC_ROLE, subject="", snippet="")
            == "software engineer i metrics for release"
        )


def test_two_titles_at_one_employer_stay_two_applications() -> None:
    """The reason any of this matters: a rejection must not settle the wrong row.

    Both messages name a role only in their bodies. Before the derivation was
    carried, both resolved to ``None`` at one employer and collapsed onto a
    single card — and a rejection for one would have terminated the other.
    """

    clusters, unplaced = partition_applications(
        [
            _item(
                "m1",
                subject="Thank you for applying to Torc Robotics!",
                snippet=TORC_SNIPPET,
                thread_id="t-a",
                identity_role=TORC_ROLE,
                identity_req_id="",
            ),
            _item(
                "m2",
                subject="Thank you for applying to Torc Robotics!",
                snippet=TORC_SNIPPET,
                thread_id="t-b",
                identity_role="Software Engineer I - Perception",
                identity_req_id="",
                day=13,
            ),
        ]
    )

    assert unplaced == []
    assert sorted(c.role or "" for c in clusters) == [
        "Software Engineer I - Metrics for Release",
        "Software Engineer I - Perception",
    ]


def test_item_identity_is_the_same_rule() -> None:
    """One rule, not three. ``item_identity`` must not drift from the helper."""

    item = _item(
        "m1",
        subject="Thank you for applying to Torc Robotics!",
        snippet=TORC_SNIPPET,
        identity_role=TORC_ROLE,
        identity_req_id="",
    )
    assert item_identity(item) == identity_or_derive(
        req_id=item.identity_req_id,
        role=item.identity_role,
        subject=item.subject,
        snippet=item.snippet,
    )
