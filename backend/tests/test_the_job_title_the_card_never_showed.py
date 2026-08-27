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
            # This fixture ENDED HERE, with no full stop, until end-of-string
            # stopped counting as a clause end. That made it a truncated body —
            # the shape `test_a_truncated_body_yields_nothing_rather_than_half_a_title`
            # now requires to yield nothing — so it was finished into the
            # sentence a real offer mail actually sends.
            "We are delighted to extend an offer to join Northwind as an "
            "Infrastructure Engineer. The written terms are attached.",
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


# ── the sentence does not stop where the title does ──────────────────────────
#
# Both rules below have no trailing keyword to terminate on, so the first draft
# captured to whatever punctuation turned up next. Every case here returned a
# WRONG title from that draft, and the wrong title is worse than the blank one
# the rules exist to fill: `normalize_role_token` keys an application on the
# role, so "Staff Engineer at Northwind" in the offer and "Staff Engineer" in
# the confirmation are two applications, and the board grows the duplicate card
# this whole change set was opened to prevent.


@pytest.mark.parametrize(
    "body,expected",
    [
        # The title ends; the sentence carries on. Each of these captured the
        # continuation before the span was shaped.
        (
            "We are delighted to extend an offer for you to join Northwind as a "
            "Software Engineer starting on January 5, 2027.",
            "Software Engineer",
        ),
        (
            "We would like to extend an offer to join us as a Staff Engineer at "
            "Northwind.",
            "Staff Engineer",
        ),
        (
            "We are pleased to extend an offer to join Northwind as a Senior "
            "Engineer reporting to Jane Smith.",
            "Senior Engineer",
        ),
        # The employer's possessive, in both apostrophe glyphs. The ASCII guard
        # in the first draft made these two sentences disagree with each other:
        # one produced a title carrying the employer, the other produced nothing.
        (
            "We are pleased to extend an offer to join Northwind as a Software "
            "Engineer on Northwind\u2019s Platform team.",
            "Software Engineer",
        ),
        (
            "We are pleased to extend an offer to join Northwind as a Software "
            "Engineer on Northwind's Platform team.",
            "Software Engineer",
        ),
    ],
)
def test_the_title_ends_where_the_prose_resumes(body, expected):
    assert role_from_message("", body) == expected


CAPTURED_THE_SENTENCE = [
    # "at <Employer>" is the terminator, and in each of these it sits a whole
    # clause downstream — so the capture ran through a verb, a conjunction or a
    # comma to reach it.
    "Your application for Data Scientist is under review at Northwind.",
    "We have kept your application for Data Scientist on file and will reach "
    "out about future opportunities at Northwind.",
    "Thank you for your application for Data Scientist, and at Northwind we "
    "review every submission carefully.",
    # "application TO <X>" names the employer, never the job. This one filed the
    # company itself as the position, which is the token most likely to collide
    # with a real card.
    "Thanks for applying to Northwind at GHC last week!",
]


@pytest.mark.parametrize("body", CAPTURED_THE_SENTENCE)
def test_a_capture_that_spans_a_clause_yields_nothing(body):
    """Refusing is correct here: the row goes to the queue, not onto a card."""
    assert role_from_message("", body) is None, (
        f"{body!r} produced a title out of a sentence fragment"
    )


def test_a_hard_wrapped_title_is_refused_rather_than_truncated():
    """Plain-text bodies wrap at ~72 columns, and a wrap is not a clause end.

    Treating it as one produced "Machine Learning" — clean enough to look
    correct on a card and wrong enough to split the identity. This is the one
    case where refusing costs a real title, and it is still the right trade: a
    blank card is repairable by the next message about the same job, a wrong
    identity is not.
    """
    assert (
        role_from_message(
            "",
            "We are pleased to extend an offer to join Northwind as a Machine "
            "Learning\nEngineer.",
        )
        is None
    )


def test_the_shaped_span_does_not_cross_a_full_stop():
    """The control for dropping "." out of the title-word class.

    A title word may not carry a full stop, because a word that can carry one
    can carry the sentence boundary with it — "Operator Experience. We" was a
    real capture from the draft that allowed it.
    """
    got = role_from_message(
        "",
        "Hi, We are delighted to extend you an offer to join Northwind as an "
        "Associate Software Engineer, Operator Experience. We are thrilled.",
    )
    assert got == "Associate Software Engineer, Operator Experience"


def test_the_requisition_eater_is_bounded():
    """An unclosed "(id:" must not make the scan quadratic in the body length.

    Bodies are untrusted third-party text and this pattern anchors on the most
    common word in it. Unbounded, this shape grew 6ms -> 233ms across four
    doublings; bounded it is linear. Asserted as a wall-clock ceiling because
    the defect IS the time.
    """
    import time

    body = "application for Aaaa (id:" * 4000
    start = time.perf_counter()
    role_from_message("", body)
    assert time.perf_counter() - start < 1.0


def test_a_truncated_body_yields_nothing_rather_than_half_a_title():
    """THE OFFER RULE IS THE ONE PATTERN THAT CAN FAIL OPEN, so it is pinned here.

    Every other body pattern needs a trailing keyword and therefore stops
    producing anything when the text runs out. This one has no keyword, so
    while end-of-string counted as a clause end it happily returned whatever
    fragment the truncation left behind.

    The input is real: the extractor is handed `bodies.get(id) or msg.snippet`,
    and Gmail's snippet is cut at an arbitrary character. A truncated capture is
    not a cosmetic wrong title — the role token is half the identity, so it
    mints a card no later, fuller-text message about the same job can join.
    """
    cut_mid_word = "We are delighted to extend an offer to join Northwind as a Software Eng"
    cut_at_a_boundary = "We are delighted to extend an offer to join Northwind as a Software"
    assert role_from_message("", cut_mid_word) is None
    assert role_from_message("", cut_at_a_boundary) is None
    # THE CONTROL. The same sentence, finished, must still produce its title —
    # otherwise "refuse truncated bodies" is satisfied by refusing everything.
    assert (
        role_from_message(
            "",
            "We are delighted to extend an offer to join Northwind as a Software "
            "Engineer.",
        )
        == "Software Engineer"
    )


def test_a_title_joined_by_an_en_dash_is_read():
    """An ASCII-only joiner refused the module's own worked example.

    `_ROLE_BODY_PATTERNS`' documentation uses "Software Development Engineer I
    – AI/ML Network Infrastructure" to explain the width bound, and until the
    joiner accepted en and em dashes that exact title produced nothing.
    """
    got = role_from_message(
        "",
        "We are delighted to extend an offer to join Amazon as a Software "
        "Development Engineer I \u2013 AI/ML Network Infrastructure.",
    )
    assert got == "Software Development Engineer I \u2013 AI/ML Network Infrastructure"
