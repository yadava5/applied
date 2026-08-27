"""Two confirmation shapes name the job and nothing read it.

MEASURED, not suspected. The board score gained a title check on 2026-08-26
(#487) and immediately reported **600 cards with a blank position** where the
mail named a role. Sorted by whether the role is even present in the text the
extractor is handed:

    role IS in the text, extractor returns None ....... 404
    the mail genuinely names no role .................. 196

The 404 are two wordings, and both are ordinary rather than exotic:

    "…an offer to join <Employer> as a <ROLE>."                        260
    "…submit your application for <ROLE> at <Employer>."               127
    (the remaining 17 name the role in the SUBJECT only — see #485)

WHY EVERY EXISTING PATTERN WALKS PAST THEM. ``_ROLE_BODY_PATTERNS`` terminates a
capture on a keyword — "position", "role", "opening" — or on a parenthesised
requisition label. Neither wording has one. The first ends the sentence on the
title; the second follows it with "at <Employer>". The one subject rule for
"application for" needs an unbroken Title-Case run, so a real title dies on its
own punctuation: "Software Engineer I, Entry-Level (Graduation Date: Fall
2025-Summer 2026)" yields nothing at all.

WHY THIS IS NOT COSMETIC. The role token IS the application's identity
(``application_sub_key``), so a blank title is not only a card that reads badly
— it is a card that a later message about the same job may fail to join. And
the 260 offers are exactly the cards a rescission has to find later (#417).

THE TERMINATOR IS THE SAFETY, in both rules, and it is the same argument the
Lever rule already makes: the capture must END on something that is only there
because a job was named — an employer, or the end of the clause after an offer
verb — so a sentence that names no job produces no capture rather than a wrong
one. Both rules are appended LAST in the tuple, so neither can change a capture
the board already has; ``test_identity_from_lever_confirmations.py`` carries the
ordering guard.

Every fixture here is invented. The two real SHAPES are public ATS conventions.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.pipeline import role_from_message

# ── the two shapes, and they must produce the whole title ────────────────────


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "Hi Ayush, We are delighted to extend you an offer to join Northwind "
            "Labs as a Associate Software Engineer, Operator Experience. We are "
            "thrilled at the prospect of you joining the team.",
            "Associate Software Engineer, Operator Experience",
        ),
        # The title is the last thing in the message — no full stop, no trailing
        # sentence to lean on. The clause-end lookahead is what reads this, and
        # without it the rule would need a terminator that is not there.
        (
            "We are delighted to extend an offer to join Northwind as an "
            "Infrastructure Engineer",
            "Infrastructure Engineer",
        ),
        (
            "Hi Ayush, Thank you for taking the time to submit your application "
            "for Software Engineer I, Entry-Level (Graduation Date: Fall "
            "2025-Summer 2026) at Northwind. We are glad you are interested.",
            "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)",
        ),
        (
            "Thanks for applying for Staff Machine Learning Engineer at Northwind.",
            "Staff Machine Learning Engineer",
        ),
    ],
)
def test_the_role_is_read_out_of_the_body(body: str, expected: str) -> None:
    got = role_from_message("", body)
    assert got == expected, f"got {got!r}"


# ── the refusals, which are the half that keeps this safe ────────────────────


NOT_A_JOB_TITLE = [
    # "as a" is ordinary English. A rule keyed on it alone lifts a noun out of
    # any sentence in the mailbox, so the offer verb AND the join verb are both
    # required ahead of it.
    "We will be in touch as a team once we have news.",
    "This message is sent as a courtesy to applicants at Northwind.",
    "Please treat this as a formality.",
    "Your offer to join our mailing list as a subscriber at Northwind.",
    # No capital: a verb is not a job title. This is what refuses the shape
    # where "application to <verb> at <Employer>" reads like the real one.
    "Please submit your application to work at Northwind.",
    "We received your application to intern at Northwind.",
    # The employer must be the terminator. A lowercase continuation is not an
    # employer, so the capture fails rather than running to the sentence end.
    "We received your application for Software Engineer at a company like ours.",
    # The control from the Lever rule, restated: "to be a <Title> at <Employer>"
    # with no application verb is ordinary correspondence.
    "We have invited you to be a Mentor at Palantir University.",
]


@pytest.mark.parametrize("body", NOT_A_JOB_TITLE)
def test_a_sentence_that_names_no_job_produces_no_title(body: str) -> None:
    """A wrong title is worse than none: it is the application's identity."""

    got = role_from_message("", body)
    assert got is None, f"{body!r} minted the job title {got!r}"


def test_the_offer_rule_needs_both_verbs_not_just_one() -> None:
    """The two halves of the offer anchor, each removed on its own.

    A guard no test can distinguish from its absence is untested. "offer" alone
    and "join" alone are both common; only the pair asserts a job.
    """

    both = "We are delighted to extend you an offer to join Northwind as a Platform Engineer."
    assert role_from_message("", both) == "Platform Engineer"

    # "join" without the offer
    assert role_from_message("", "We would love for you to join Northwind as a Platform Engineer.") is None
    # "offer" without the join
    assert role_from_message("", "We have an offer for you at Northwind as a Platform Engineer.") is None


def test_a_title_the_board_already_has_is_not_changed() -> None:
    """Both rules are appended LAST, so they fire only where nothing else did.

    These four are owned by earlier patterns. If either new rule ever answers
    one of them, the tuple's order has stopped protecting the captures the live
    board was built from.
    """

    owned = {
        "Thank you for applying to our role: Software Engineer I, Storage.":
            "Software Engineer I, Storage",
        "We received your application for the Frontend Engineer position.":
            "Frontend Engineer",
        "Thank you for submitting your application to be a Software Engineer, "
        "New Grad at Northwind.": "Software Engineer, New Grad",
        "Thanks for applying to Northwind's Frontend Engineer position!":
            "Frontend Engineer",
    }
    for body, expected in owned.items():
        assert role_from_message("", body) == expected, body
