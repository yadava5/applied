"""THE RIGHT EDGE OF THE TRAILING SEGMENT, GRADED BY GENERATION (#626, PR 632).

The 44 hand-written cases in
``test_the_trailing_segment_names_the_role.py`` are what MISSED the defect this
module exists to prevent, so more hand-written cases is not the bar. An
independent cross-check of the first version of ``_role_from_trailing_segment``
found 26 of 48 adversarial subjects in the targeted shape coming back with a
title nobody would want on a card — every one of them because the two refusal
branches probed ``role.split()[-1]``, the last WORD, and a second word on the
right walked past both:

    … | Software Engineer (Remote, US) - Brackenhill  ->  'Software Engineer (Remote, US)'
    … | Software Engineer - Brackenhill (Remote, US)  ->  'Software Engineer'
    … | Engineering Manager Interview - Brackenhill              ->  None
    … | Engineering Manager Interview Invitation - Brackenhill   ->  the whole string

A wrong title is strictly worse than a blank one: it becomes the card's
displayed title AND its ``role_token``, which then captures that application's
future mail. Two properties are asserted here over a GENERATED grid, plus the
floor that stops both of them being vacuous.

**P1, PLACEMENT CONVERGENCE.** ``<Role> (<Tail>) - <Employer>`` and
``<Role> - <Employer> (<Tail>)`` are one posting written the two ways an ATS
writes it. They must never both resolve to DIFFERENT tokens, and the tail
placement must equal ``token(R)``. Asserted through
:func:`normalize_role_token` — the same accessor production keys applications
on — because the split is a TOKEN phenomenon and two strings that differ can
still be one key.

**P2, LIFECYCLE NON-REVIVAL.** A lifecycle phrase does not become a job title
because a noun was appended to it. One case per member of the nine
``_SUBJECT_LIFECYCLE_TAIL`` stems, in both the space-joined and the
comma-introduced position, each paired with a WORD-COUNT-MATCHED twin that must
resolve — a refusal whose twin also refuses proves nothing, because the fixture
may have died on an earlier guard and never reached the branch under test.

**THE VACUITY FLOOR** is the single most important assertion in the file. P1 and
P2 are both trivially green for a reader that always returns ``None``, which is
the reader this change must not ship.

INVENTED VOCABULARY IS THE ANTI-ENUMERATION DEVICE. "Quorvale", "Brenmark",
"Quorvex" and "Sennhalt" are not words. No implementation list can contain them,
so an implementation can only pass the cells that use them by being structural.

Every fixture here is invented. No mailbox content appears in this file.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

EMPLOYER = "Brackenhill"
BOILER = "Thank you for applying!"

#: Words that exist nowhere — not in this module's sets, not in any ATS.
INVENTED = ["Quorvex", "Brenmark", "Quorvale", "Sennhalt"]


def subject(candidate: str, tail: str = "") -> str:
    """``<Employer> | <Boilerplate> | <Candidate> - <Employer>[ (<Tail>)]``."""

    suffix = f" ({tail})" if tail else ""
    return f"{EMPLOYER} | {BOILER} | {candidate} - {EMPLOYER}{suffix}"


def read(candidate: str, tail: str = "") -> str | None:
    return pipeline.role_from_message(subject(candidate, tail), "")


def token(role: str | None) -> str | None:
    return pipeline.normalize_role_token(role)


# ── the roles the grid is built from ────────────────────────────────────────
#
# CLOSED: the last word IS the title's head noun, or a level token that this
# module treats as continuing it. The post-head region is empty, so structure
# alone decides the right edge and P1 holds unconditionally.
CLOSED_ROLES = [
    "Platform Engineer",                                                        # 2
    "Senior Backend Engineer",                                                  # 3
    "Software Engineer II",                                                     # 3, a level
    "Distributed Systems Platform Engineer",                                    # 4
    "Senior Staff Machine Learning Engineer",                                   # 5
    "Principal Site Reliability Platform Systems Engineer",                     # 6
    "Senior Principal Site Reliability Platform Systems Engineer",              # 7
    "Senior Principal Staff Site Reliability Platform Systems Engineer",        # 8
    "Senior Principal Staff Site Reliability Distributed Platform Systems Engineer",  # 9
]

# INTRODUCED: the title continues past its head noun through a comma, a dash or
# an ampersand — the shape the reported bug's own title has. Structure LICENSES
# that continuation (it has to; refusing it would refuse #626 itself), so an
# invented proper noun space-joined onto the end is invisible to it. That is the
# residual, and it is pinned rather than hidden — see
# ``test_a_comma_introduced_place_name_is_a_known_residual`` below.
INTRODUCED_ROLES = [
    "Software Engineer - Storage",                                              # dash
    "Senior Software Engineer, Platform",                                       # comma
    "Data Scientist, Search & Ranking",                                         # comma + &
    "Software Engineer I, Entry-Level",                                         # level+comma
    "Software Engineer, Distributed Systems Platform, New Grad",                # the report
]

ROLES = CLOSED_ROLES + INTRODUCED_ROLES

#: Two kinds of tail, and the difference between them is the whole test. The
#: first three are what a work-arrangement VOCABULARY knows; the last two are
#: proper nouns no list can contain, and they are what tells a structural rule
#: from a lexical one.
NAMED_TAILS = ["Remote", "Hybrid", "Remote, US"]
INVENTED_TAILS = ["Quorvale", "Brenmark"]
TAILS = NAMED_TAILS + INVENTED_TAILS

#: One exemplar per alternation branch of ``_SUBJECT_LIFECYCLE_TAIL``. A set
#: needs a control per member: nine branches, nine exemplars, so swapping any
#: one of them out reds a named cell rather than being absorbed by its
#: neighbours.
LIFECYCLE_STEMS = [
    "Follow-Up",
    "Application",
    "Interview",
    "Offer",
    "Assessment",
    "Update",
    "Opportunity",
    "Career",
    "Recruiting",
]

#: What gets appended to the stem. "" is the bare stem the old last-word probe
#: caught; "Invitation" is the real word that revived it; the invented ones are
#: what proves no list is doing the work. NONE of these may be a title head
#: noun — a trailing head noun legitimately RE-HEADS the phrase, and "Interview
#: Engineer" is a real title.
APPENDED = ["", "Invitation", "Quorvex", "Quorvex Brenmark"]

#: The nine members of ``_WORK_ARRANGEMENT_WORDS``, each in every spelling the
#: normalised region scan is supposed to reach. "On Site"/"On-Site" and "In
#: Office"/"In-Office" are the pair the previous last-word probe could only ever
#: reach through the hyphen fold, because ``role.split()[-1]`` cannot contain a
#: space.
ARRANGEMENT_SPELLINGS = [
    "Remote",
    "Hybrid",
    "Onsite",
    "On-Site",
    "On Site",
    "In-Office",
    "In Office",
    "Virtual",
    "Telecommute",
]

#: THE ONE CELL THE GRID DOES NOT ASSERT, named rather than filtered silently.
#: A nine-word role with a two-word tail is eleven words, and ``_ROLE_SPAN``
#: caps a title at ten — so ``_TITLE_SHAPED`` refuses it before either branch
#: this file grades is reached. It would still come back ``None`` and would
#: still look like a pass, which is the whole problem with letting a guard you
#: are not testing answer for you. ``test_the_excluded_cell_is_excluded_for_the
#: _stated_reason`` proves the exclusion is that cap and not an oversight.
PAST_THE_SPAN_CAP = [
    ("Senior Principal Staff Site Reliability Distributed Platform Systems Engineer",
     "Remote, US"),
]

#: Roles short enough that a two-word arrangement still fits inside
#: ``_ROLE_SPAN``'s ten-word cap. Stated rather than assumed: an eleven-word
#: candidate is refused by ``_TITLE_SHAPED`` before any of this reaches the
#: branch under test, and a refusal from the wrong guard is not evidence.
ARRANGEMENT_ROLES = [
    "Platform Engineer",
    "Senior Backend Engineer",
    "Senior Software Engineer, Platform",
]


def _cells() -> list[tuple[str, str, str | None]]:
    """(label, candidate, expected) for every generated cell.

    ``expected`` of ``None`` means the reader must refuse; a string means it
    must hand back exactly that. Only cells whose candidate is still
    ``_TITLE_SHAPED`` are generated: a candidate past the ten-word cap is
    refused by a guard that runs BEFORE the two branches this file grades, and
    including it would manufacture a pass.
    """

    cells: list[tuple[str, str, str | None]] = []

    # P1 — the bare role is the anchor every placement is compared against.
    for role in ROLES:
        cells.append(("p1-bare", role, role))

    # P1 — a parenthetical on the ROLE side always refuses, for every role and
    # every tail, invented or not. Structural: no vocabulary is consulted.
    for role in ROLES:
        for tail in TAILS:
            cells.append(("p1-paren-role", f"{role} ({tail})", None))

    # P1 — the same tail on the EMPLOYER side is stripped, so the posting keeps
    # its own title. This half is what makes the refusal above a convergence
    # rather than a blanket denial.
    #   (asserted separately in test_the_two_placements_converge, which needs
    #    the tail argument this cell shape has no room for)

    # P1 — space-joined onto a CLOSED role: refused by structure alone.
    for role in CLOSED_ROLES:
        for tail in TAILS:
            if (role, tail) in PAST_THE_SPAN_CAP:
                continue
            candidate = f"{role} {tail}"
            assert pipeline._TITLE_SHAPED.match(candidate), candidate
            cells.append(("p1-space-closed", candidate, None))

    # P1 — space-joined onto an INTRODUCED role: structure licenses the
    # continuation, so only the named tails are refused, by the arrangement
    # scan. The invented tails are the residual and are pinned in their own
    # strict xfail rather than asserted here.
    for role in INTRODUCED_ROLES:
        for tail in NAMED_TAILS:
            candidate = f"{role} {tail}"
            assert pipeline._TITLE_SHAPED.match(candidate), candidate
            cells.append(("p1-space-introduced", candidate, None))

    # P2 — every stem, every appended run, both positions, plus the
    # word-count-matched twin that must resolve.
    for role in ARRANGEMENT_ROLES:
        for stem in LIFECYCLE_STEMS:
            for appended in APPENDED:
                run = f"{stem} {appended}".strip()
                for label, candidate in (
                    ("p2-space", f"{role} {run}"),
                    ("p2-comma", f"{role}, {run}"),
                ):
                    assert pipeline._TITLE_SHAPED.match(candidate), candidate
                    cells.append((label, candidate, None))
                twin = f"{role}, " + " ".join(INVENTED[: len(run.split())])
                cells.append(("p2-twin", twin, twin))

    # P2's companion — one control per member of the arrangement set, in the
    # COMMA-INTRODUCED position. Space-joined they would be refused twice over
    # (by structure and by the scan), which would make every member's mutation
    # green and the whole set untestable.
    for role in ARRANGEMENT_ROLES:
        for spelling in ARRANGEMENT_SPELLINGS:
            candidate = f"{role}, New Grad {spelling}"
            assert pipeline._TITLE_SHAPED.match(candidate), candidate
            cells.append(("arrangement", candidate, None))
        control = f"{role}, New Grad Quorvex"
        cells.append(("arrangement-twin", control, control))

    return cells


CELLS = _cells()

#: THE VACUITY FLOOR, as a literal. P1 and P2 are both green for a reader that
#: returns ``None`` for everything; this is the assertion that says the grid
#: exercised a reader that reads. The number is deliberately a constant and not
#: ``len([...])`` computed from the grid — a floor derived from the thing it
#: measures goes vacuous exactly when the grid does.
MINIMUM_RESOLUTIONS = 100


def test_the_grid_is_not_vacuous() -> None:
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

    Every other test here is a refusal or a convergence, and both are satisfied
    by a reader that never resolves anything at all. This one is not.
    """

    resolving = [cell for cell in CELLS if cell[2] is not None]
    assert len(resolving) >= MINIMUM_RESOLUTIONS, len(resolving)
    for _label, candidate, expected in resolving:
        assert read(candidate) == expected, candidate


@pytest.mark.parametrize(
    "candidate,expected",
    [(candidate, expected) for _label, candidate, expected in CELLS],
    ids=[f"{label}:{candidate}" for label, candidate, _expected in CELLS],
)
def test_every_generated_cell(candidate: str, expected: str | None) -> None:
    assert read(candidate) == expected


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("tail", TAILS)
def test_the_two_placements_converge(role: str, tail: str) -> None:
    """P1, stated at the TOKEN level, which is the level the split happens at.

    ``role_token`` is half of an application's identity. Two spellings of one
    posting that produce two tokens produce two cards, and the second one
    captures the mail the first one was waiting for. So the assertion is not
    "the strings agree" — it is "there is at most one key".
    """

    on_role_side = read(f"{role} ({tail})")
    on_employer_side = read(role, tail)

    # The employer-side placement is the one that keeps the posting's title: the
    # parenthetical there belongs to the employer half of the segment.
    assert token(on_employer_side) == token(role)
    # ...and the role-side placement never mints a SECOND key for it.
    assert on_role_side is None or token(on_role_side) == token(on_employer_side)


@pytest.mark.parametrize("role", CLOSED_ROLES)
@pytest.mark.parametrize("tail", TAILS)
def test_the_space_joined_placement_converges_on_a_closed_role(
    role: str, tail: str
) -> None:
    """The same property with the brackets removed, where structure closes it.

    ``<Role> <Tail> - <Employer>`` is the placement the parenthetical strip
    cannot reach. On a role whose last word is its head noun, a space-joined
    tail is a bare word standing right of the head — refused with no vocabulary
    consulted, which is why an INVENTED proper noun is refused exactly as
    "Remote" is.
    """

    if (role, tail) in PAST_THE_SPAN_CAP:
        return
    candidate = f"{role} {tail}"
    assert pipeline._TITLE_SHAPED.match(candidate), candidate
    assert read(candidate) is None
    assert token(read(role, tail)) == token(role)


@pytest.mark.parametrize("role,tail", PAST_THE_SPAN_CAP)
def test_the_excluded_cell_is_excluded_for_the_stated_reason(
    role: str, tail: str
) -> None:
    """The exclusion above is the ten-word cap, and here is the proof.

    Without this, ``PAST_THE_SPAN_CAP`` is a list of cells somebody decided not
    to run, and nothing distinguishes that from a cell that was quietly dropped
    because it failed. The cell IS refused — but by ``_TITLE_SHAPED``, one guard
    earlier than the branches this file grades, so its ``None`` is not evidence
    about them.
    """

    candidate = f"{role} {tail}"
    assert pipeline._TITLE_SHAPED.match(candidate) is None
    assert read(candidate) is None
    # ...and one word shorter, the same cell IS graded and still refuses.
    shorter = f"{' '.join(role.split()[1:])} {tail}"
    assert pipeline._TITLE_SHAPED.match(shorter)
    assert read(shorter) is None


@pytest.mark.parametrize("stem", LIFECYCLE_STEMS)
def test_no_stem_survives_a_word_being_appended_to_it(stem: str) -> None:
    """P2, one test per member, with the twin that makes it directional.

    The old branch tested ``role.split()[-1]`` against the same nine stems and
    was defeated by one noun: "Engineering Manager Interview" refused and
    "Engineering Manager Interview Invitation" did not. Every appended run below
    must refuse, and the word-count-matched twin must RESOLVE — if the twin also
    refuses, the fixture died on an earlier guard and this test proved nothing.
    """

    role = "Senior Backend Engineer"
    for appended in APPENDED:
        run = f"{stem} {appended}".strip()
        assert read(f"{role} {run}") is None, run
        assert read(f"{role}, {run}") is None, run
        twin = f"{role}, " + " ".join(INVENTED[: len(run.split())])
        assert read(twin) == twin, twin


@pytest.mark.parametrize("spelling", ARRANGEMENT_SPELLINGS)
def test_every_arrangement_spelling_is_reachable(spelling: str) -> None:
    """The set's members, each in the position where ONLY the set refuses.

    Space-joined, structure would refuse these on its own and the set would be
    untestable — every member's mutation would come back green. Comma-introduced
    is where the set earns its keep, because the reported title's own shape is
    comma-introduced and an arrangement hides there perfectly.

    "On Site" and "In Office" are here because the previous last-word probe
    could only ever reach them through ``_normalize_token`` folding the hyphen
    in "On-Site"; a whitespace-split token cannot contain a space. The region
    scan reaches both spellings.
    """

    role = "Senior Backend Engineer"
    assert read(f"{role}, New Grad {spelling}") is None
    # Directional: the same shape with an invented word in its place resolves.
    assert read(f"{role}, New Grad Quorvex") == f"{role}, New Grad Quorvex"


def test_a_work_arrangement_left_of_the_head_noun_is_part_of_the_title() -> None:
    """The precision the region scan buys over scanning the whole candidate.

    "Remote Infrastructure Engineer" and "Hybrid Cloud Architect" are real
    posted titles. A scan of the whole string would refuse both; the post-head
    region for each is empty, so neither is ever looked at.
    """

    assert read("Remote Infrastructure Engineer") == "Remote Infrastructure Engineer"
    assert read("Hybrid Cloud Architect") == "Hybrid Cloud Architect"
    assert read("Virtual Reality Systems Engineer") == "Virtual Reality Systems Engineer"


def test_a_title_that_continues_past_its_head_noun_still_resolves() -> None:
    """The other half of the structural rule: introductions are not refusals.

    A rule that refused everything right of the head noun would refuse #626's
    own title. These are the four introductions that keep it resolving, and each
    one is asserted so that dropping any of them reds.
    """

    assert read("Software Engineer, Distributed Systems Platform, New Grad") == (
        "Software Engineer, Distributed Systems Platform, New Grad"
    )                                                          # comma
    assert read("Software Engineer - Storage") == "Software Engineer - Storage"  # dash
    assert read("Software Engineer II") == "Software Engineer II"                # level
    assert read("Software Engineer I, Entry-Level") == "Software Engineer I, Entry-Level"
    assert read("Engineer in Test") == "Engineer in Test"                        # INNER
    assert read("Director of Engineering") == "Director of Engineering"          # INNER


@pytest.mark.parametrize(
    "candidate",
    [
        "Software Engineer Intern",
        "Data Analyst Intern",
        "Research Scientist Intern",
        "Software Engineer Internship",
        "Product Design Manager Lead",
    ],
)
def test_a_trailing_head_noun_re_heads_the_phrase(candidate: str) -> None:
    """WHY THE REGION STARTS AT THE **LAST** HEAD NOUN AND NOT THE FIRST.

    "Software Engineer Intern" is a real posted title with two head nouns in it,
    and the second one is the head: the job is an internship, not an engineer.
    Measuring the region from the FIRST head noun would leave "Intern" standing
    space-joined to the right of "Engineer" and refuse all five of these.

    Found by mutation — reversing the scan in ``_last_head_noun_end`` left every
    other test in this file green, which means without this control the choice
    of first-versus-last was untested and free to drift.
    """

    assert read(candidate) == candidate
    # ...and the same shape with a NON-head noun on the end still refuses, so
    # this is a rule about head nouns and not a hole in the structural one.
    assert read(f"{candidate.rsplit(' ', 1)[0]} Quorvex") is None


def test_a_requisition_id_parenthetical_converges_from_both_placements() -> None:
    """WHY THE PAREN REFUSAL RUNS AFTER ``_clean_role`` AND NOT BEFORE.

    ``_clean_role`` deletes a requisition-id parenthetical and the employer-side
    strip deletes it too, so both placements land on one token and the title
    keeps resolving. Testing the RAW candidate instead would refuse the
    employer's own id format for no gain — the split it exists to prevent cannot
    occur here, because both sides already converge.
    """

    assert read("Software Engineer II (Req ID: 10475660)") == "Software Engineer II"
    assert read("Software Engineer II", "Req ID: 10475660") == "Software Engineer II"


# ── residuals, pinned rather than omitted ───────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN RESIDUAL, disclosed rather than hidden. A comma introduces a "
        "title's own continuation, which is what #626's title is made of, so a "
        "comma-introduced PLACE NAME is structurally identical to a "
        "comma-introduced subteam. Nothing this module would accept tells "
        "', San Francisco' from ', Distributed Systems Platform' without world "
        "knowledge, and place names are an open set no vocabulary closes. "
        "Strict, so that closing it reds this test and forces the disclosure to "
        "be updated rather than quietly outliving the defect."
    ),
)
@pytest.mark.parametrize(
    "candidate",
    [
        "Software Engineer, San Francisco",
        "Software Engineer, Distributed Systems Platform, New Grad Quorvale",
        "Software Engineer - Storage Brenmark",
        "Senior Software Engineer, Platform Quorvale",
    ],
)
def test_a_comma_introduced_place_name_is_a_known_residual(candidate: str) -> None:
    assert read(candidate) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN RESIDUAL, and NOT what this PR set out to fix. Both new branches "
        "read the region to the RIGHT of the title's head noun, because that is "
        "where English puts what a compound is about. These four put the "
        "lifecycle material to the LEFT and end on the head noun, so the "
        "post-head region is empty and neither branch ever sees them. No "
        "pre-head scan can separate them from 'Applications Engineer', which "
        "must resolve. Reported on PR 632 rather than papered over."
    ),
)
@pytest.mark.parametrize(
    "candidate",
    [
        "Interview Invitation for Software Engineer",
        "Next Steps for Software Engineer",
        "Not Selected for Software Engineer",
        "Congratulations Software Engineer",
        "Sarah Chen, Engineering Manager",
        "Priya Raman, Senior Recruiter Engineer",
    ],
)
def test_a_lifecycle_phrase_left_of_the_head_noun_is_a_known_residual(
    candidate: str,
) -> None:
    assert read(candidate) is None


def test_the_shared_definitions_this_fix_is_forbidden_to_move() -> None:
    """The five names pinned by the first commit on this branch, re-pinned here.

    This change is right-edge hygiene inside one reader. If any of these moved,
    it would be a different change wearing this one's commit message.
    """

    assert pipeline._SEGMENT_DELIMITER.pattern == r"\||\s[-–—]\s"
    assert pipeline._ROLE_INNER == r"(?:of|and|in|for|the)"
    assert set(pipeline._ROLE_HEAD_NOUNS) == {
        "engineer", "developer", "designer", "scientist", "analyst",
        "architect", "manager", "director", "lead", "specialist",
        "consultant", "administrator", "technician", "researcher",
        "associate", "intern", "internship",
    }
    assert set(pipeline._WORK_ARRANGEMENT_WORDS) == {
        "remote", "hybrid", "onsite", "on site", "in office", "virtual",
        "telecommute",
    }
    # The role side refuses through the SAME object the employer side strips
    # with, which is what stops the two edges drifting apart in a later edit.
    assert pipeline._TRAILING_SEGMENT_PAREN.pattern == r"\s*\([^()]{0,80}\)\s*$"
