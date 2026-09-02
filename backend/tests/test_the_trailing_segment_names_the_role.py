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

THE TWO REFUSAL BRANCHES WERE REWRITTEN AFTER THIS FILE FIRST SHIPPED, and the
reason is recorded here because these 44 cases are what missed it. An
independent cross-check found 26 of 48 adversarial subjects in this shape coming
back with a title nobody would want on a card, all from one root cause: both
branches probed ``role.split()[-1]``, so a second word on the right walked past
them. ``… (Remote, US)`` split one job into two identity keys and "Engineering
Manager Interview Invitation" became a card title.

Both probes are gone. A candidate ending in ANY parenthetical refuses, through
the same regex the employer side strips with; and the region right of the
title's head noun must be INTRODUCED — by a comma, a dash, a level or a
connective — rather than space-joined. The generated grid in
``test_the_trailing_segments_right_edge_is_structural.py`` is what grades them,
because hand-written cases are what failed here.

Every fixture here is INVENTED. "Brackenhill" and "Northwind" are not companies;
no real mailbox content appears in this file, in the reader, or in the commit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobtracker.cloud import pipeline

#: Any instant. The readers under test are pure text; the timestamp only
#: has to exist so a PipelineItem is well-formed and countable.
WHEN = datetime(2026, 9, 1, tzinfo=UTC)

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


@pytest.mark.parametrize(
    "candidate",
    [
        # The case this test was written with, and the only one the original
        # last-word probe caught.
        "Engineering Manager Interview",
        # ...and the four that revived it by putting ONE MORE WORD on the right.
        # An independent cross-check found these; they are the reason the probe
        # is gone and a positive structural rule stands in its place.
        "Engineering Manager Interview Invitation",
        "Software Engineer Interview Confirmation",
        "Software Engineer Offer Letter",
        "Software Engineer Interview Reminder",
        # Refused with NO vocabulary at all: none of "Event", "Newsletter" or
        # "Alert" is in any set in the module, and none of them needs to be.
        "Senior Engineer Hiring Event",
        "Engineer Newsletter",
        "Software Engineer Job Alert",
    ],
)
def test_a_lifecycle_tail_is_what_the_mail_is_about_not_what_the_job_is(
    candidate: str,
) -> None:
    """THE MOST MISSABLE REFUSAL IN THIS MODULE.

    "Engineering Manager Interview" is Title-Case, is title-SHAPED, and its head
    noun ("manager") is real, so ``_clean_role``, ``_TITLE_SHAPED`` and
    ``_ROLE_HEAD_NOUNS`` all accept it. Something has to refuse the tail, and it
    is the same cut ``_employer_from_subject_segment`` already makes on the
    employer half of an ATS subject.

    IT IS A RULE ABOUT POSITION, NOT A LIST OF WORDS, and that is what changed.
    The first version tested the last WORD against the nine
    ``_SUBJECT_LIFECYCLE_TAIL`` stems, so appending any noun revived it —
    "Engineering Manager Interview" refused and "Engineering Manager Interview
    Invitation" became a card title. What refuses all eight of these now is that
    the material stands SPACE-JOINED to the right of the title's head noun,
    where English puts what a compound is about rather than what it is. No set
    contains "Invitation", "Letter", "Reminder", "Event", "Newsletter" or
    "Alert", and widening one to reach them is what this rule exists to avoid:
    a wordlist's gaps fail open, and this rule's gaps fail closed.
    """

    subject = f"{EMPLOYER} | {BOILER} | {candidate} - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") is None


def test_the_nine_stems_still_earn_their_keep_where_structure_cannot_see() -> None:
    """...and why the stems are KEPT rather than deleted with the probe.

    A comma introduces a title's own continuation — that is what #626's own
    title is made of, and refusing it would refuse the bug this reader exists to
    fix. So a lifecycle segment written after a comma is invisible to the
    structural rule, and the nine stems are scanned over the whole post-head
    region to catch it. They are NOT widened; this is the only position they
    still work in.
    """

    hidden = f"{EMPLOYER} | {BOILER} | Software Engineer, Final Interview - {EMPLOYER}"
    assert pipeline.role_from_message(hidden, "") is None
    # Directional: the same shape with an invented word in the stem's place is a
    # title and resolves, so the refusal above is the stem and not the comma.
    twin = f"{EMPLOYER} | {BOILER} | Software Engineer, Final Quorvex - {EMPLOYER}"
    assert pipeline.role_from_message(twin, "") == "Software Engineer, Final Quorvex"


def test_a_lifecycle_word_left_of_the_head_noun_is_part_of_the_title() -> None:
    """The accepting twin the position rule buys, which a whole-string scan loses.

    "Applications Engineer" is a real job title and "Application" is one of the
    nine stems. It survives because the stem stands LEFT of the head noun, where
    it modifies the job instead of naming what the mail is about. A scan of the
    whole candidate would refuse it; the post-head region for it is empty.
    """

    subject = f"{EMPLOYER} | {BOILER} | Applications Engineer - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == "Applications Engineer"


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


def test_the_employer_refusal_is_isolated_from_the_structural_rule() -> None:
    """The control that keeps the employer refusal MUTABLE.

    "Brackenhill Developer Tools" is now refused twice over — by the explicit
    candidate-equals-employer test AND by the structural rule, since "Tools"
    stands space-joined right of "Developer". A branch that two rules refuse is
    a branch no mutation can red, and an untestable guard is the same shape as a
    guard that is not there.

    So the isolating fixture ENDS on its head noun: "Brackenhill Developer" has
    an empty post-head region, passes ``_clean_role``, ``_TITLE_SHAPED`` and the
    head-noun test, and would file the company as the job title if the equality
    refusal were removed.
    """

    employer = "Brackenhill Developer"
    subject = f"{employer} | {BOILER} | {employer} - {employer} (Remote)"
    assert pipeline.role_from_message(subject, "") is None
    # Directional, and one word away: the same employer, a real title.
    other = f"{employer} | {BOILER} | Platform Engineer - {employer} (Remote)"
    assert pipeline.role_from_message(other, "") == "Platform Engineer"


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
    """The accepting twin: the id rides along, the title is still read.

    THIS IS WHY THE PAREN REFUSAL RUNS AFTER ``_clean_role``. That function
    deletes a requisition-id parenthetical and the employer-side strip deletes
    it too, so both placements converge on one token and there is no split to
    prevent. Testing the RAW candidate would refuse this for nothing.
    """

    subject = f"{EMPLOYER} | {BOILER} | Software Engineer II (Req ID: 10475660) - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") == "Software Engineer II"
    # The other placement of the same id, which is what "converge" means here.
    other = f"{EMPLOYER} | {BOILER} | Software Engineer II - {EMPLOYER} (Req ID: 10475660)"
    assert pipeline.role_from_message(other, "") == "Software Engineer II"


# ── refusal 4: a bare work-arrangement word outside the parentheses ──────────


@pytest.mark.parametrize(
    "tail",
    ["Remote", "Hybrid", "Onsite", "On-Site", "On Site", "In-Office", "In Office",
     "Virtual", "Telecommute"],
)
def test_a_bare_work_arrangement_tail_is_not_part_of_the_title(tail: str) -> None:
    """The parenthetical strip does not reach a location written without brackets.

    "…New Grad Remote" is exactly as Title-Case as "…New Grad", and the extra
    word changes the ``role_token``, which splits one application into two.

    WHY THE SET SURVIVED THE STRUCTURAL REWRITE. The reported title continues
    past its head noun through a comma, so ``_post_head_is_introduced`` licenses
    everything after "Engineer" — including a work arrangement space-joined onto
    the end of it. Structure closes this placement for a title that ENDS on its
    head noun and cannot close it for this one, which is the reported bug's own
    title. Deleting the set would have flipped every case below to resolving.

    All nine spellings, because the previous last-word probe could only reach
    the two-word members through ``_normalize_token`` folding the hyphen in
    "On-Site" — a whitespace-split token cannot contain a space, so "On Site"
    written as two words was unreachable. The region is normalised as a whole
    now, so both spellings of both members are live.
    """

    subject = f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} {tail} - {EMPLOYER}"
    assert pipeline.role_from_message(subject, "") is None


def test_the_same_location_inside_the_parentheses_resolves() -> None:
    """The accepting twin: the brackets are the whole difference."""

    subject = f"{EMPLOYER} | {BOILER} | {REPORTED_TITLE} - {EMPLOYER} (Remote)"
    assert pipeline.role_from_message(subject, "") == REPORTED_TITLE


@pytest.mark.parametrize(
    "parenthetical",
    [
        # What a work-arrangement vocabulary knows.
        "Remote",
        # ...and what it does not, which is the whole point. The tail-side strip
        # is UNCONDITIONAL, so a vocabulary-gated role side leaves every place
        # name nobody listed minting a second token. Place names are an open set.
        "Remote, US",
        "Bengaluru",
        "Hybrid Optional",
        # An invented proper noun: no list anywhere can contain it.
        "Quorvale",
    ],
)
def test_a_parenthesised_arrangement_on_the_title_is_refused_as_well(
    parenthetical: str,
) -> None:
    """BOTH PLACEMENTS OR NEITHER — and it is STRUCTURAL, not lexical.

    "<Role> (X) - <Employer>" and "<Role> - <Employer> (X)" are one posting
    written the two ways an ATS writes it. The reader strips the second and
    would keep the first, handing back "Software Engineer (Remote)" against the
    other's "Software Engineer" — and ``normalize_role_token`` deletes the
    brackets but KEEPS THE WORD, so those are two ``role_token``s for one job.
    That is the split this whole module exists to prevent, reached from the
    other direction, so the odd spelling refuses to the review queue.

    THE FIRST VERSION OF THIS GUARD TESTED THE LAST WORD against a
    work-arrangement list and did not hold: "(Remote, US)" has two words in it,
    so the list never saw "Remote" and the split shipped. Fixing the DETECTOR
    while keeping the list would not have closed it either — "(Bengaluru)" is
    not a work arrangement and the tail side strips it anyway.

    So the rule is: ANY parenthetical on the role side refuses, through the very
    same ``_TRAILING_SEGMENT_PAREN`` the employer side strips with, which is
    what stops the two edges drifting apart in a later edit. STRIPPING instead
    of refusing was rejected outright and for a worse reason than the split:
    "Software Engineer (Platform)" and "Software Engineer (Security)" at one
    employer would collapse onto one token and start capturing each other's mail.
    """

    attached = (
        f"{EMPLOYER} | {BOILER} | Software Engineer ({parenthetical}) - {EMPLOYER}"
    )
    trailing = (
        f"{EMPLOYER} | {BOILER} | Software Engineer - {EMPLOYER} ({parenthetical})"
    )
    assert pipeline.role_from_message(attached, "") is None
    assert pipeline.role_from_message(trailing, "") == "Software Engineer"
    # ...and this is the reason, not a taste: the two spellings never join.
    assert pipeline.normalize_role_token(
        f"Software Engineer ({parenthetical})"
    ) != pipeline.normalize_role_token("Software Engineer")


def test_a_parenthesised_cohort_on_the_title_now_refuses_too() -> None:
    """THIS TEST FLIPPED, and the flip is the cost of Fix 1 stated out loud.

    It used to assert that "Software Engineer I (Graduation Date: Fall 2026)"
    KEEPS its cohort parenthetical, because ``_ROLE_PAREN`` exists for exactly
    that real posted title. Under the structural rule it refuses, and there is
    no way to keep it that does not reopen the split: telling a cohort from a
    location needs to know what "Bengaluru" is.

    IT IS RECALL NOT GAINED, NOT A REGRESSION. Every subject of this shape
    resolves to ``None`` on main — the reader that reads them at all is the one
    this branch adds — so nothing that used to work stops working. The message
    goes to the review queue, a person types the title once, and at most one
    token is ever minted for the job.

    The same title in the LEAD segment is untouched: this is right-edge hygiene
    inside one reader, not a change to ``_ROLE_PAREN``.
    """

    subject = (
        f"{EMPLOYER} | {BOILER} | Software Engineer I (Graduation Date: Fall 2026) - "
        f"{EMPLOYER}"
    )
    assert pipeline.role_from_message(subject, "") is None
    # The cohort without its brackets is a comma-introduced continuation, which
    # is title material and still resolves — so the refusal above is the
    # parenthesis and nothing else.
    plain = f"{EMPLOYER} | {BOILER} | Software Engineer I, Entry-Level - {EMPLOYER}"
    assert pipeline.role_from_message(plain, "") == "Software Engineer I, Entry-Level"
    # ``_ROLE_PAREN`` itself is unmoved: the span still accepts the cohort.
    assert pipeline._TITLE_SHAPED.match(
        "Software Engineer I (Graduation Date: Fall 2026)"
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


# =============================================================================
# A refusal reaches nobody — issue #657
# =============================================================================
#
# This reader's docstring said a refusal sends "the message… to the review
# queue, where a person decides. Fails closed, the direction this module takes
# everywhere." It does not. Nothing in the pipeline routes a message to the
# queue for naming no role: `collect_review_items` skips whatever
# `_qualifies_for_hard_row` accepts, and that asks about confidence and an
# employer only.
#
# WHAT THESE TESTS ARE. They pin what the product DOES, not what it should do.
# Whether a blank role ought to gate a review is #657's open half and a product
# decision nobody has made. Pinning it means the answer cannot change silently:
# if a later change makes a blank role a review trigger, these go red and are
# the place to record that decision — they are not a defence of today's
# behaviour, and the docstrings say so out loud rather than leaving the next
# reader to infer it from a green test.
#
# The employer half is deliberately NOT touched. Fixing the unobtainable
# licence means teaching `_lead_segment_candidates` to read a company out of an
# ATS boilerplate sentence, which is a change to the EMPLOYER reader and needs
# the #512/#525 measurements re-run — dropping the delimiter requirement there
# previously minted "Senior Software Engineer" as an employer.

#: The reported shape: the leading segment is a SENTENCE, so the lead reader
#: finds no company and the echo licence cannot be obtained at any tail.
SENTENCE_LEAD = (
    "Thank you for applying to Brackenhill | "
    "Firmware/Cloud Validation Engineer - New Grad (December 2026)"
)
#: Identical but for the leading segment, which is the bare company name. This
#: is the control that locates the blocker: same tail, same dash, same role.
BARE_COMPANY_LEAD = (
    "Brackenhill | Thank you for applying! | "
    "Firmware/Cloud Validation Engineer - Brackenhill (Remote)"
)


def test_the_licence_is_unobtainable_when_the_lead_is_a_sentence() -> None:
    """The blocker is upstream of the echo test, which is not where it reads.

    The obvious reading of a refusal here is "the tail names something other
    than the employer, so the echo failed". That is not what happens: the LEAD
    reader returns nothing for prose, so ``lead_tokens`` is empty and
    ``echo not in lead_tokens`` is true for every possible echo. No tail can
    satisfy it.

    The control is what proves it. One segment differs and the same title
    resolves.
    """

    assert pipeline._lead_segment_candidates(SENTENCE_LEAD) == []
    assert pipeline._lead_segment_candidates(BARE_COMPANY_LEAD) == ["Brackenhill"]

    assert pipeline.role_from_message(SENTENCE_LEAD, "") is None
    assert (
        pipeline.role_from_message(BARE_COMPANY_LEAD, "")
        == "Firmware/Cloud Validation Engineer"
    )


def test_a_refused_role_files_a_card_and_asks_nobody() -> None:
    """TODAY'S BEHAVIOUR, pinned as a fact rather than endorsed.

    The message the reader refused clears ``AUTO_FILE_GATE``, so
    ``_qualifies_for_hard_row`` accepts it and ``collect_review_items`` skips
    it. A card is filed with a blank role and no question is asked. That is the
    sentence "fails closed" described and the opposite of what it claimed.

    Asserted three ways, because any one alone is satisfiable for the wrong
    reason: the reader really refuses, the row really qualifies, and the queue
    really produces nothing. A test asserting only the empty queue would pass
    just as well on a message that never reached the pipeline.
    """

    item = pipeline.PipelineItem(
        message_id="m-657",
        category="applied",
        sender_email="no-reply@ats.example.test",
        subject=SENTENCE_LEAD,
        sender_name="Brackenhill Careers",
        received_at=WHEN,
        confidence=0.95,
    )

    assert pipeline.item_identity_parts(item) == (None, None), (
        "the premise moved: this subject now yields a role, so the rest of "
        "this test is measuring something else"
    )
    assert item.confidence >= pipeline.AUTO_FILE_GATE
    assert pipeline._qualifies_for_hard_row(item) is not None
    assert pipeline.collect_review_items([item]) == [], (
        "a blank role now reaches the review queue — that is #657's open half "
        "being decided, and this test is where the decision gets recorded"
    )


def _refused_role_item(message_id: str, category: str) -> "pipeline.PipelineItem":
    """The reported shape, at a confidence that clears the auto-file gate."""

    return pipeline.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email="no-reply@ats.example.test",
        subject=SENTENCE_LEAD,
        sender_name="Brackenhill Careers",
        received_at=WHEN,
        confidence=0.95,
    )


@pytest.mark.parametrize(
    "category, at_a_multi_card_employer, queued",
    [
        # A CONFIRMATION asserts an application. #641 gives an identity-less one
        # its own card at a multi-card employer rather than folding it, so it is
        # placed either way and nobody is asked either way.
        ("applied", False, False),
        ("applied", True, False),
        # An UPDATE reports on an application that already exists, so at an
        # employer holding several there is no single row to pick and asking is
        # the only honest move. This is the carve-out, and it is the ONLY route
        # by which a refused role reaches a person.
        ("rejection", False, False),
        ("rejection", True, True),
        ("interview", True, True),
        ("assessment", True, True),
    ],
)
def test_where_a_refused_role_does_and_does_not_reach_a_person(
    category: str, at_a_multi_card_employer: bool, queued: bool
) -> None:
    """The whole partition, because "asks nobody" is true of more of it than I first wrote.

    My first version of this test asserted that a multi-card employer rescues
    the reported message. It does not, and the reason is the interesting part:
    ``unplaceable_message_ids`` promotes mail that cannot be PLACED, and since
    #641 an identity-less CONFIRMATION at a multi-card employer is placeable —
    it mints its own card. So the shape #657 reports is silent at a
    single-application employer AND at a multi-card one. Only an UPDATE reaches
    the carve-out.

    That makes the false docstring wider than it looked. "Fails closed" was not
    merely optimistic about one case; the one route to a person does not carry
    the case the sentence was written under.

    All six rows share the same subject, sender and confidence, so the only
    moving parts are the category and the board. A parametrisation where the
    expected value never varied would prove nothing; here it varies twice, on
    two different axes.
    """

    item = _refused_role_item(f"m-657-{category}-{at_a_multi_card_employer}", category)

    # The employer token is `example`, from the RELAY DOMAIN, and asserting it
    # is half the point. The subject's leading segment is a sentence, so
    # `_lead_segment_candidates` finds nothing there either — the same failure
    # that costs the role also costs the subject its say in who the employer
    # is, and the sender's domain brand is what is left. A test that guessed
    # `brackenhill` would hand `known_multi` a token the pipeline never
    # produces and then assert an empty queue for a reason that has nothing to
    # do with the carve-out. Mine did, on the first run.
    token = pipeline.company_key(item.sender_email, item.subject, item.sender_name)
    assert token == "example"

    assert pipeline.item_identity_parts(item) == (None, None), (
        "the premise moved: this subject now yields a role"
    )
    assert pipeline._qualifies_for_hard_row(item) is not None

    known_multi = frozenset({token}) if at_a_multi_card_employer else frozenset()
    reached = [r.message_id for r in pipeline.collect_review_items([item], known_multi=known_multi)]
    assert bool(reached) is queued, (
        f"{category} at a {'multi' if at_a_multi_card_employer else 'single'}-card "
        f"employer: expected queued={queued}, got {reached}"
    )
