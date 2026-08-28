"""THE ROLE SITS IN THE SEGMENT THE EMPLOYER WAS ALREADY READ OUT OF (#553).

``#512``/``#525`` taught ``resolve_employer`` to read the employer out of

    <Employer> Follow-Up for <Role> | <Candidate>

and it works. The job title in the middle of that same subject was still unread,
on the same message, in the same request. Reproduced on ``main`` (3401c20)::

    >>> pipeline.role_from_message(
    ...     "Northwind Follow-Up for Backend Engineer | <CANDIDATE>", "")
    None

WHY IT COSTS MORE THAN A BLANK CARD. ``identity_parts`` returning
``(None, None)`` is what sends the resolver into ``_pick_application``'s rule 4
— the tie-break that files onto the employer's OLDEST row rather than mint a
second card. So an unread role here blanked the title AND downgraded the filing
decision on the same message.

THE REFUSALS ARE THE LARGER HALF, deliberately, and that is not symmetry for its
own sake: this is the filing path. A role that resolves becomes the card's
displayed job and its ``role_token``, and the token then captures that
application's future mail — so a wrong title does not merely look wrong, it
splits one application into two. The must-not-resolve list below is therefore
the load-bearing one, exactly as
``test_a_lifecycle_word_does_not_hide_the_employer.py`` argues for the employer
half of this same subject.

THE HEAD-NOUN TEST IS THE ONE THAT EARNED ITS PLACE. Requiring only a Title-Case
shape accepts "Acme Interview for Tomorrow | <Candidate>" and "Acme Follow-Up
for Tuesday | <Candidate>" — single Title-Case words in exactly the reported
position, and both would have become an application's identity. ``TIME_SHAPED``
below is that population, and it is asserted separately so that deleting the
head-noun test cannot be mistaken for a cosmetic loosening.

Every fixture is invented. The two real subject SHAPES keep their public
employer names; role and candidate fields are redacted or replaced.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

GREENHOUSE = "no-reply@us.greenhouse-mail.io"


# ── the reported shape ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Northwind Follow-Up for Backend Engineer | <CANDIDATE>", "Backend Engineer"),
        ("Anthropic Follow-Up for Research Engineer | <CANDIDATE>", "Research Engineer"),
        # A comma-qualified title, which is how every ATS spells a team split.
        (
            "Verkada Follow-Up for Software Engineer, Storage | <CANDIDATE>",
            "Software Engineer, Storage",
        ),
        # A two-word employer still leaves a lifecycle word at the end of the run.
        ("Northwind Labs Update for Staff Data Scientist | <CANDIDATE>", "Staff Data Scientist"),
        # A TITLE THAT CONTAINS A SPACED DASH, which is the case that decided
        # where the segment ends. Both of these are real corpus titles; reading
        # the segment up to the first spaced dash truncates them, and a truncated
        # title is a rival card for an application the board already tracks.
        (
            "Sablewickridge Follow-Up for Software Engineer, Agentic AI Harness "
            "& Quality - Talonflow | <CANDIDATE>",
            "Software Engineer, Agentic AI Harness & Quality - Talonflow",
        ),
        (
            "Hazelstowridge Follow-Up for Software Development Engineer I - AI/ML "
            "Network Infrastructure, Kestrelan Labs | <CANDIDATE>",
            "Software Development Engineer I - AI/ML Network Infrastructure, Kestrelan Labs",
        ),
        # "regarding" introduces the object as surely as "for" does.
        (
            "Northwind Follow-Up regarding Product Designer | <CANDIDATE>",
            "Product Designer",
        ),
    ],
)
def test_the_role_is_read_out_of_the_same_segment(subject, expected):
    assert pipeline.role_from_message(subject, "") == expected


def test_the_role_reaches_the_identity_the_filing_path_reads():
    """The point of the fix: the resolver stops arriving with nothing to file on.

    ``role_from_message`` alone would be a cosmetic win. This asserts the value
    survives into ``identity_parts``, which is what ``_resolve_application_for_email``
    consults before falling back to the oldest-row tie-break.
    """

    subject = "Northwind Follow-Up for Backend Engineer | <CANDIDATE>"
    role, req_id = pipeline.identity_parts(
        req_id=None, role=None, subject=subject, snippet=""
    )
    assert role == "Backend Engineer"
    assert req_id is None
    assert pipeline.normalize_role_token(role) == "backend engineer"


def test_the_employer_half_of_the_same_subject_is_untouched():
    """The control for the whole file: this subject must still name its employer.

    A "fix" that read the role by consuming the segment differently could take
    the employer with it, and every assertion above would still pass.
    """

    assert pipeline.resolve_employer(
        GREENHOUSE, "Northwind Follow-Up for Backend Engineer | <CANDIDATE>"
    ) == ("northwind", "Northwind")


# ── the refusals ─────────────────────────────────────────────────────────────


# Each list below is named for the ONE guard that refuses it, and each is
# asserted twice: once in the broad sweep, and once on its own. That is not
# duplication. Deleting any single guard left the broad sweep entirely green,
# because a subject refused by four guards proves nothing about the fourth —
# the earlier ones answer first and the fixture never reaches the line under
# test. Every list here was chosen by running the deletion and watching it stay
# green, then finding the case that goes red.


#: Refused ONLY by the head-noun test. Title-Case single words in exactly the
#: reported position, correctly shaped, and not one of them is a job.
TIME_SHAPED = [
    "Acme Interview for Tomorrow | <CANDIDATE>",
    "Acme Follow-Up for Tuesday | <CANDIDATE>",
    "Acme Interview for Monday | <CANDIDATE>",
    "Acme Follow-Up for You | <CANDIDATE>",
    "Acme Update for Everyone | <CANDIDATE>",
    "Acme Follow-Up for Thursday Afternoon | <CANDIDATE>",
]

#: Prose after the introducer. Refused on shape: a title is Title Case, and
#: lowercase prose that happens to sit in this position must never key a card.
PROSE_SHAPED = [
    "Anthropic Follow-Up for your recent application | <CANDIDATE>",
    "Anthropic Follow-Up for the next steps | <CANDIDATE>",
    "Acme Update for our records | <CANDIDATE>",
    "Acme Follow-Up for a quick chat | <CANDIDATE>",
]

#: Refused ONLY by the shape test. Each one carries a real head noun and clears
#: `_clean_role` (which asks merely that SOME word be capitalised), and each
#: opens on a lowercase word, which is where a title cannot begin.
ONLY_SHAPE_REFUSES = [
    "Acme Follow-Up for interviewing Software Engineer candidates | <CANDIDATE>",
    "Acme Follow-Up for lead Engineer | <CANDIDATE>",
    "Acme Update for remote Backend Engineer openings | <CANDIDATE>",
]

#: Refused ONLY by the lifecycle-object test. The run reaches its four-word cap
#: on a lifecycle word, so a Title-Case remainder survives with nothing marking
#: it as that word's object — and a bare title after a lifecycle word is not
#: established to belong to it. This is the requirement #537 had to restore for
#: the employer half of the same subject after #525 lost it.
ONLY_THE_OBJECT_TEST_REFUSES = [
    "Northwind Labs Global Update Backend Engineer | <CANDIDATE>",
    "Acme Northwind Systems Follow-Up Staff Data Scientist | <CANDIDATE>",
]

#: Refused ONLY by the LIFECYCLE-WORD half of the employer-prefix test. Two
#: words in the run, so the length half is satisfied, and a perfectly good title
#: after a perfectly good "for" — but nothing here says a lifecycle event
#: happened, and "Sarah Chen for Backend Engineer" is a person writing about a
#: job, not an ATS naming one. The two halves of that test are each other's
#: control: `NO_EMPLOYER_PREFIX` pins the length half, this pins the word half,
#: and dropping either alone left every other assertion green.
ONLY_THE_LIFECYCLE_WORD_REFUSES = [
    "Sarah Chen for Backend Engineer | <CANDIDATE>",
    "Northwind Labs for Staff Data Scientist | <CANDIDATE>",
]

#: Refused ONLY by `_clean_role`. Correctly shaped, real head noun, and a
#: possessive no job title carries — "Your Backend Engineer" is the reader's
#: application, not the name of a job.
ONLY_CLEAN_ROLE_REFUSES = [
    "Acme Follow-Up for Your Backend Engineer | <CANDIDATE>",
    "Acme Update for Our Backend Engineer | <CANDIDATE>",
]

#: The remainder is not the lifecycle word's OBJECT. This is the requirement
#: #537 had to restore for the employer half after #525 lost it, and it is the
#: same requirement here.
NOT_AN_OBJECT = [
    "Quick Update from Sarah | <CANDIDATE>",
    "Acme Follow-Up with Sarah Chen | <CANDIDATE>",
    "Acme Interview by Backend Engineer | <CANDIDATE>",
    "Sarah Chen from Acme - quick chat?",
]

#: No lifecycle word ending an employer-shaped run, so there is no employer here
#: to attach a role to in the first place.
NO_EMPLOYER_PREFIX = [
    "Interview for Backend Engineer | Acme",
    "Follow-Up for Backend Engineer | Acme",
    "Invitation to interview | Acme",
    "Decision on your application | Acme",
    "Congratulations Ayush on your application | Acme",
    "Sorry for the delay in getting back to you | Acme",
]

#: No pipe. The employer rule refuses a subject with no delimiter at all, and
#: the role rule goes further: only a ``|`` bounds it.
#:
#: THE SPACED DASH IS NOT A BOUNDARY FOR A ROLE even though it is one for an
#: employer, and the last two entries are why. A job title carries a spaced dash
#: routinely — two of the corpus's own titles do — and an employer name in this
#: mail does not, so the same delimiter set cannot serve both halves of the
#: subject. Splitting these at the dash yields "Staff Data Scientist" and
#: "Software Development Engineer I": clean-looking, truncated, and a rival card
#: for an application already on the board. Refusing sends the row to the review
#: queue instead, which is the safe direction on this path.
NOT_A_SEGMENT = [
    "Northwind Follow-Up for Backend Engineer",
    "Acme Interview for Backend Engineer",
    "Thanks for applying to Northwind",
    "Northwind Labs Update for Staff Data Scientist - <CANDIDATE>",
    "Hazelstowridge Follow-Up for Software Development Engineer I - AI/ML "
    "Network Infrastructure, Kestrelan Labs - <CANDIDATE>",
]

#: Possessives and articles a real job title never carries.
POSSESSIVE = [
    "Northwind Follow-Up regarding our Backend Engineer | <CANDIDATE>",
    "Northwind Follow-Up for your Backend Engineer role | <CANDIDATE>",
]


@pytest.mark.parametrize(
    "subject",
    TIME_SHAPED
    + PROSE_SHAPED
    + ONLY_SHAPE_REFUSES
    + NOT_AN_OBJECT
    + ONLY_THE_OBJECT_TEST_REFUSES
    + NO_EMPLOYER_PREFIX
    + NOT_A_SEGMENT
    + POSSESSIVE
    + ONLY_CLEAN_ROLE_REFUSES
    + ONLY_THE_LIFECYCLE_WORD_REFUSES,
)
def test_a_subject_that_does_not_name_a_job_reads_no_role(subject):
    got = pipeline.role_from_message(subject, "")
    assert got is None, (
        f"{subject!r} produced the role {got!r} — this is the filing path, so "
        "that becomes a card's title and its role_token, and the token then "
        "captures that application's future mail"
    )


@pytest.mark.parametrize(
    "subject,guard",
    [(s, "the head-noun test") for s in TIME_SHAPED]
    + [(s, "the title-shape test") for s in ONLY_SHAPE_REFUSES]
    + [(s, "the lifecycle-object test") for s in ONLY_THE_OBJECT_TEST_REFUSES]
    + [(s, "_clean_role") for s in ONLY_CLEAN_ROLE_REFUSES]
    + [
        (s, "the lifecycle-word half of the employer-prefix test")
        for s in ONLY_THE_LIFECYCLE_WORD_REFUSES
    ],
)
def test_each_guard_is_the_only_thing_standing_between_a_subject_and_a_card(
    subject, guard
):
    """One case per guard that NO other guard refuses.

    Asserted against `_role_from_lead_segment` directly rather than through
    `role_from_message`, so an existing `_ROLE_PATTERNS` rule cannot answer for
    it and hide the guard being tested.
    """

    segment_role = pipeline._role_from_lead_segment(subject)
    assert segment_role is None, (
        f"{subject!r} -> {segment_role!r}; {guard} is the only guard that "
        "refuses this shape, so nothing else will catch its removal"
    )


# ── the rule must not pre-empt the ones that already worked ──────────────────


@pytest.mark.parametrize(
    "subject,expected",
    [
        # Read by _ROLE_PATTERNS, and they run first. A segment reader that ran
        # ahead of them would answer these differently.
        ("Your application for the Backend Engineer role | Acme", "Backend Engineer"),
        ("Interview for the Data Scientist position | Acme", "Data Scientist"),
    ],
)
def test_the_patterns_that_already_read_a_role_still_win(subject, expected):
    assert pipeline.role_from_message(subject, expected and "") == expected


def test_a_body_role_is_still_read_when_the_subject_names_none():
    """The body half of role_from_message is untouched by a subject-side rule."""

    assert (
        pipeline.role_from_message(
            "Thank you for Applying to Northwind!",
            "Thank you for applying to our role: Backend Engineer.",
        )
        == "Backend Engineer"
    )
