"""THE EMPLOYER BRACKETS THE SUBJECT AND THE TITLE SITS BETWEEN (#626).

An ATS confirmation of this shape filed with NO role at all::

    <Employer> | <Boilerplate> | <Role> - <Employer> (<Location>)

Reproduced on the base of this branch (``26564b4``)::

    >>> pipeline.role_from_message(
    ...     "Brackenhill | Thank you for applying! | Software Engineer, "
    ...     "Distributed Systems Platform, New Grad - Brackenhill (Remote)", "")
    None

The employer resolves fine. Four separate reasons the subject readers decline
the title, all confirmed by execution before a line was written:

1. ``_ROLE_PATTERNS[2]`` and ``[3]`` are ``^``-anchored and two segments sit in
   front of the role;
2. their capture class ``[\\w/&.\\-]`` excludes the comma, and this title has two;
3. their ``{0,4}`` caps a title at five words, and this one is seven;
4. ``_role_from_subject`` calls none of ``_clean_role``, ``_TITLE_SHAPED`` or
   ``_ROLE_HEAD_NOUNS`` on that path, so there is no guard behind it to widen
   safely against.

The body of this template says "this role" and "the role" throughout and never
names the title, so ``_ROLE_BODY_PATTERNS`` cannot rescue it. The subject is the
only place the title exists.

WHY THE EXISTING PATTERNS ARE NOT RELAXED, and why this is a whole new reader
rather than three characters deleted from an old one. Removing only the ``^``
from ``_ROLE_PATTERNS[3]`` yields the role ``'Grad'``: the comma-adjacent starts
die in the capture class, the engine walks forward to "New", the pattern's own
``(?i:new\\s+)?`` prefix eats it, and ``\\s+[-–—]\\s+[A-Z]`` is satisfied by
" - Brackenhill". ``'Grad'`` clears the filler and length filters and would
become the card's displayed title AND its ``role_token``, which then captures
that application's future mail. A wrong role is strictly worse than a blank one,
so ``_ROLE_PATTERNS`` is pinned byte-for-byte below.

THE REFUSALS ARE THE LARGER HALF, and every one of them is paired with an
ACCEPTING TWIN one edit away. A refusal test on its own passes for a reader that
always returns ``None``, which is precisely the reader this module must not
ship: a control has to be directional.

Every fixture here is INVENTED. "Brackenhill" and "Northwind" are not companies;
no real mailbox content appears in this file, in the reader, or in the commit.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

EMPLOYER = "Brackenhill"
BOILER = "Thank you for applying!"
#: The reported title: seven words, two commas — every bound the old readers hit.
REPORTED_TITLE = "Software Engineer, Distributed Systems Platform, New Grad"
REPORTED = f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} - {EMPLOYER} (Remote)"


# ── the reported shape, end to end ───────────────────────────────────────────


def test_the_reported_subject_names_its_role() -> None:
    """The bug report itself, through the public entrypoint."""

    assert pipeline.role_from_message(REPORTED, "") == REPORTED_TITLE


def test_the_reported_subject_names_its_role_through_the_reader() -> None:
    """...and through the reader, so a later chaining slip is attributable."""

    assert pipeline._role_from_trailing_segment(REPORTED) == REPORTED_TITLE


@pytest.mark.parametrize(
    "subject,expected",
    [
        # Five words.
        (
            f"{EMPLOYER} | {BOILER} | Senior Software Engineer, Platform - "
            f"{EMPLOYER} (Remote)",
            "Senior Software Engineer, Platform",
        ),
        # Seven, the reported width.
        (REPORTED, REPORTED_TITLE),
        # Eight — past every ``{0,4}`` in the module.
        (
            f"{EMPLOYER} | {BOILER} | Senior Staff Software Engineer, Distributed "
            f"Systems Platform, New Grad - {EMPLOYER} (Remote)",
            "Senior Staff Software Engineer, Distributed Systems Platform, New Grad",
        ),
        # No location parenthetical at all.
        (
            f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} - {EMPLOYER}",
            REPORTED_TITLE,
        ),
        # A two-part location parenthetical.
        (
            f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} - {EMPLOYER} (Remote, US)",
            REPORTED_TITLE,
        ),
        # No commas anywhere in the title.
        (
            f"{EMPLOYER} | {BOILER} | Distributed Systems Platform Engineer - "
            f"{EMPLOYER} (Remote)",
            "Distributed Systems Platform Engineer",
        ),
        # Two segments rather than three: the boilerplate segment is optional.
        (f"{EMPLOYER} | Software Engineer - {EMPLOYER}", "Software Engineer"),
    ],
)
def test_the_shape_resolves_at_every_width(subject: str, expected: str) -> None:
    assert pipeline.role_from_message(subject, "") == expected


def test_a_title_containing_a_spaced_dash_survives() -> None:
    """#553's measured regression, in the position this reader works in.

    The cut is made at the LAST spaced dash, so an interior one stays inside the
    title. Splitting at the first yields "Software Engineer" and a card that no
    later message about the same job can join.
    """

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer - Storage - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == "Software Engineer - Storage"


def test_a_requisition_id_is_not_part_of_the_title() -> None:
    """``_clean_role`` deletes the id; the reader must actually call it."""

    subject = (
        f"{EMPLOYER} | {BOILER} | Software Engineer (Job ID: 10475660) - "
        f"{EMPLOYER} (Remote)"
    )
    assert pipeline.role_from_message(subject, "") == "Software Engineer"


def test_the_subject_outranks_a_body_that_names_a_different_title() -> None:
    """PRECEDENCE, stated rather than left accidental.

    ``role_from_message`` tries the subject first and only falls through to
    ``_ROLE_BODY_PATTERNS`` when it yields nothing, so chaining this reader into
    ``_role_from_subject`` moves the subject ahead of the body for every message
    of this shape. That is intended — the trailing segment is the posted title
    verbatim, while the body is prose — but it is a real change of precedence
    and it is asserted here so it cannot move without a red.
    """

    snippet = "Thank you for applying to our role: Data Scientist, Search."
    assert pipeline.role_from_message(REPORTED, snippet) == REPORTED_TITLE
    # ...and the body still answers when the subject has nothing to say.
    assert (
        pipeline.role_from_message(f"{EMPLOYER} | {BOILER}", snippet)
        == "Data Scientist, Search"
    )


# ── refusal 1: a lifecycle word as the candidate's last word ─────────────────


def test_a_lifecycle_tail_is_what_the_mail_is_about_not_what_the_job_is() -> None:
    """THE MOST MISSABLE REFUSAL IN THIS MODULE.

    "Engineering Manager Interview" is Title-Case, is title-SHAPED, and its head
    noun ("manager") is real, so ``_clean_role``, ``_TITLE_SHAPED`` and
    ``_ROLE_HEAD_NOUNS`` all accept it. Only a lifecycle test on the tail
    refuses, and it is the same cut ``_employer_from_subject_segment`` already
    makes on the employer half of an ATS subject.
    """

    subject = f"{EMPLOYER} | {BOILER} | Engineering Manager Interview - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_the_same_subject_without_the_lifecycle_word_resolves() -> None:
    """The accepting twin, one word away."""

    subject = f"{EMPLOYER} | {BOILER} | Engineering Manager - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == "Engineering Manager"


# ── refusal 2: the employer's own name as the candidate ──────────────────────


@pytest.mark.parametrize(
    "candidate",
    [EMPLOYER, f"{EMPLOYER} Technologies", f"{EMPLOYER}, Inc."],
)
def test_the_employer_echoed_twice_names_no_role(candidate: str) -> None:
    subject = f"{EMPLOYER} | {BOILER} | {candidate} - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_a_company_whose_own_name_carries_a_title_head_noun_is_still_refused() -> None:
    """The refusal that is NOT an accident of the head-noun test.

    "Brackenhill Developer Tools" contains "developer", so the head-noun test
    accepts it and every other guard passes. Without an explicit
    candidate-equals-employer refusal this subject files the company as the job
    title. Relying on one set to catch what another set is for is how a rule
    silently stops refusing when the first set is widened.
    """

    employer = "Brackenhill Developer Tools"
    subject = f"{employer} | {BOILER} | {employer} - {employer} (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_a_real_title_from_that_same_employer_resolves() -> None:
    """The accepting twin: only the candidate changes."""

    employer = "Brackenhill Developer Tools"
    subject = f"{employer} | {BOILER} | Software Engineer - {employer} (Remote)"
    assert pipeline.role_from_message(subject, "") == "Software Engineer"


# ── refusal 3: a requisition id in the title's place ─────────────────────────


@pytest.mark.parametrize("candidate", ["REQ-10475660", "R2938471", "JR-004821"])
def test_a_requisition_id_is_not_a_job_title(candidate: str) -> None:
    """Pinned in its own right.

    Refused today by the head-noun test rather than by anything about digits, so
    a future widening of ``_ROLE_HEAD_NOUNS`` could un-refuse it without a
    single red. This test is what makes that widening visible.
    """

    subject = f"{EMPLOYER} | {BOILER} | {candidate} - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_a_title_carrying_a_requisition_id_still_resolves() -> None:
    """The accepting twin: the id rides along, the title is still read."""

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer II (Req ID: 10475660) - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") == "Software Engineer II"


# ── refusal 4: a bare work-arrangement word outside the parentheses ──────────


@pytest.mark.parametrize("tail", ["Remote", "Hybrid", "Onsite", "On-Site"])
def test_a_bare_work_arrangement_tail_is_not_part_of_the_title(tail: str) -> None:
    """The parenthetical strip does not reach a location written without brackets.

    "…New Grad Remote" is exactly as Title-Case as "…New Grad", and the extra
    word changes the ``role_token``, which splits one application into two.
    """

    subject = f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} {tail} - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") is None


def test_the_same_location_inside_the_parentheses_resolves() -> None:
    """The accepting twin: the brackets are the whole difference."""

    subject = f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == REPORTED_TITLE


def test_a_parenthesised_arrangement_on_the_title_is_refused_as_well() -> None:
    """BOTH PLACEMENTS OR NEITHER.

    "<Role> (Remote) - <Employer>" and "<Role> - <Employer> (Remote)" are one
    posting written the two ways an ATS writes it. The reader strips the second
    and would keep the first, handing back "Software Engineer (Remote)" against
    the other's "Software Engineer" — and ``normalize_role_token`` deletes the
    brackets but KEEPS THE WORD, so those are two ``role_token``s for one job.
    That is the split this whole module exists to prevent, reached from the
    other direction, so the odd spelling refuses to the review queue.
    """

    attached = f"{EMPLOYER} | {BOILER} | Software Engineer (Remote) - {EMPLOYER}"
    trailing = f"{EMPLOYER} | {BOILER} | Software Engineer - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(attached, "") is None
    assert pipeline.role_from_message(trailing, "") == "Software Engineer"
    # ...and this is the reason, not a taste: the two spellings never join.
    assert pipeline.normalize_role_token(
        "Software Engineer (Remote)"
    ) != pipeline.normalize_role_token("Software Engineer")


def test_a_parenthesised_cohort_on_the_title_is_kept() -> None:
    """The accepting twin: a parenthetical that is not a work arrangement.

    ``_ROLE_PAREN`` exists because "Software Engineer I, Entry-Level (Graduation
    Date: Fall 2026)" is a real posted title, and refusing every parenthetical
    to catch a location would take that with it.
    """

    subject = (
        f"{EMPLOYER} | {BOILER} | Software Engineer I (Graduation Date: Fall 2026) - "
        f"{EMPLOYER}"
    )
    assert (
        pipeline.role_from_message(subject, "")
        == "Software Engineer I (Graduation Date: Fall 2026)"
    )


# ── refusal 5: prose that is not title-shaped ───────────────────────────────


def test_prose_in_the_trailing_segment_is_not_a_title() -> None:
    """``_TITLE_SHAPED`` is the only guard that refuses this one.

    It survives ``_clean_role`` (it is not all-lowercase, carries no
    preposition+article and no unbalanced quote) and it satisfies the head-noun
    test on "Engineer". The colon and the exclamation mark are the structural
    tell that this is marketing copy, not a noun phrase.
    """

    subject = f"{EMPLOYER} | {BOILER} | Engineer Wanted: Apply Now! - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") is None


def test_the_noun_phrase_inside_that_copy_resolves_on_its_own() -> None:
    """The accepting twin: the same head noun, shaped like a title."""

    subject = f"{EMPLOYER} | {BOILER} | Platform Engineer - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") == "Platform Engineer"


# ── refusal 6: the licence itself ───────────────────────────────────────────


def test_no_pipe_segment_reads_no_trailing_role() -> None:
    """Without the pipe requirement the "last segment" is the whole subject.

    "<Employer> - <Role> - <Employer>" then cuts at its last dash and hands back
    "Brackenhill - Software Engineer" — the company welded onto the front of the
    title. Asserted on the reader directly because ``_ROLE_PATTERNS[3]`` answers
    this subject first, so an end-to-end assertion here would prove nothing
    about this reader at all.
    """

    subject = f"{EMPLOYER} - Software Engineer - {EMPLOYER}"
    assert pipeline._role_from_trailing_segment(subject) is None


def test_the_same_subject_with_a_pipe_resolves() -> None:
    """The accepting twin: one character."""

    subject = f"{EMPLOYER} | Software Engineer - {EMPLOYER}"
    assert pipeline._role_from_trailing_segment(subject) == "Software Engineer"
    assert pipeline.role_from_message(subject, "") == "Software Engineer"


def test_a_trailing_segment_with_no_spaced_dash_reads_nothing() -> None:
    """No dash, no echo, no licence — the title is not delimited from anything."""

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") is None


def test_the_same_segment_with_the_spaced_dash_resolves() -> None:
    """The accepting twin: three characters."""

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") == "Software Engineer"


def test_an_echo_naming_a_different_company_refuses() -> None:
    """The dash is licensed by the LEAD employer, not by any capitalised word.

    An echo that names someone else means the dash is doing some other job in
    this subject, and #553 recorded what assuming otherwise costs.
    """

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer - Northwind (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_an_echo_naming_the_lead_employer_resolves() -> None:
    """The accepting twin: the same subject, the echo corrected."""

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == "Software Engineer"


# ── standing controls that must stay dead ───────────────────────────────────


@pytest.mark.parametrize(
    "candidate",
    ["Application Received", "Offer Letter", "Interview Confirmation"],
)
def test_lifecycle_boilerplate_never_becomes_a_role(candidate: str) -> None:
    subject = f"{EMPLOYER} | {BOILER} | {candidate} - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") is None


def test_the_reader_never_degrades_into_the_relaxed_pattern() -> None:
    """``'Grad'`` is the trace of the fix that was NOT made.

    The ``!=`` half of this is not the gate — it passes for a reader that always
    returns ``None``. The gate is the pin below it: relaxing
    ``_ROLE_PATTERNS[3]`` is what manufactures ``'Grad'``, so the pattern set is
    asserted verbatim and moves only deliberately.
    """

    assert pipeline.role_from_message(REPORTED, "") != "Grad"
    assert [p.pattern for p in pipeline._ROLE_PATTERNS] == [
        r"\b(?:for the|for a|for an|as a|as an|regarding the|to the|to a|to an)\s+"
        r"([A-Za-z][\w/&.\-]*(?:\s+[\w/&.\-]+){0,4}?)\s+"
        r"(?:role|position|opening|opportunity|internship|intern)\b",
        r"(?i:\bapplication for)(?i:\s+the)?\s+"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4})",
        r"^\s*(?i:new\s+)?"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4}?)\s+"
        r"(?i:role|position|opening|internship)\b",
        r"^\s*(?i:new\s+)?"
        r"([A-Z][\w/&.\-]*(?:\s+[A-Z0-9][\w/&.\-]*){0,4}?)\s+(?:at|@|[-–—])\s+[A-Z]",
    ]


def test_the_shapes_this_reader_leans_on_are_unchanged() -> None:
    """The three shared definitions this fix is forbidden to move.

    ``_SEGMENT_DELIMITER`` accepting a spaced dash is what #553 measured as
    harmful for a ROLE boundary and correct for an EMPLOYER one; the head-noun
    set is what tells one from the other. This reader is additive on top of
    both, so either changing is a different change than the one that was made.
    """

    assert pipeline._SEGMENT_DELIMITER.pattern == r"\||\s[-–—]\s"
    head_nouns = {
        "engineer", "developer", "designer", "scientist", "analyst",
        "architect", "manager", "director", "lead", "specialist",
        "consultant", "administrator", "technician", "researcher",
        "associate", "intern", "internship",
    }
    assert set(pipeline._ROLE_HEAD_NOUNS) == head_nouns


def test_the_lead_segment_reader_keeps_its_answers() -> None:
    """The chaining is additive: the leading-segment reader still answers first.

    Its shape has no trailing segment of this kind, so the two cannot collide
    today — but the ordering is what guarantees that, and it is free to assert.
    """

    subject = "Northwind Follow-Up for Backend Engineer | <CANDIDATE>"
    assert pipeline._role_from_lead_segment(subject) == "Backend Engineer"
    assert pipeline.role_from_message(subject, "") == "Backend Engineer"
