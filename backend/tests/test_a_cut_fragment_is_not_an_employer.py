"""A FRAGMENT THIS MODULE CUT FOR ITSELF IS NOT AN EMPLOYER (#539, residual half).

#733 closed the headline of #539 — a candidate's own name filed as a company —
by requiring POSITIVE corporate evidence before a Title-Case run may name a
card. Four of that issue's six shapes went to None on the day it merged. Three
did not, and measured against the shipped resolver with no sender display name
and an ATS relay sender they each minted a company:

    "Phone Interview - <Employer>"           -> ('phone', 'Phone')
    "Final Interview Details | <Employer>"   -> ('final', 'Final')
    "Important Update | <Employer>"          -> ('important', 'Important')

THE MECHANISM, and why the multi-word fix did not reach them.
`_lead_segment_candidates` offers two readings of a leading segment: the
Title-Case run, and that run CUT at its first lifecycle word. "Phone Interview"
is refused for want of corporate evidence exactly as intended — and the cut it
leaves behind is "Phone", one word, which `_carries_corporate_evidence` cleared
unconditionally. The one-word door was open the whole time; the person-name fix
merely narrowed the multi-word one.

WHAT IS ASSERTED, BOTH DIRECTIONS. The refusals are the defect and the
resolutions are the reason the fix is not "refuse more": the exemption exists
for real one-word employers, so a rule that dropped it would satisfy every
refusal here and destroy the branch. Both halves are in this file, and the
candidate lists are asserted too, so a `None` below is a REFUSAL by the evidence
guard rather than a dead probe whose branch was never offered anything.

THE COST IS PINNED AS A COST, not as a desired refusal — see
`test_a_one_word_employer_in_front_of_a_lifecycle_word_is_the_price`. A corpus
that only asserts what it likes is a check that cannot fail.

WHAT THIS DOES NOT CLOSE, said here rather than left to be re-found. The
exemption is denied to a LATER reading of a segment, i.e. one whose longer
version this loop already turned down. A cut reached through the
lifecycle-object branch arrives as the ONLY reading, at index 0, and keeps the
exemption — which is what saves #512's "<Employer> Follow-Up for <Role>". So
"Phone Interview for <Role> | <Employer>" still offers ('phone', 'Phone') from
the segment reader. Separating that from the shape #512 reported needs a
lexicon, not a provenance test, and no assertion here claims otherwise.

Every employer, person and address in this file is invented; the sender uses an
RFC 2606 reserved TLD, per `docs/TEST_DATA_POLICY.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobtracker.cloud import pipeline as p

#: `.example` keeps the sender un-routable while leaving the brand intact:
#: `_domain_brand` reads the second-from-last label, so `us.greenhouse-mail.example`
#: yields `greenhouse-mail` exactly as the real relay domain does. Same constant
#: the sibling modules for #512 and #733 use.
ATS = "no-reply@us.greenhouse-mail.example"
BRAND = "greenhouse-mail"


def test_the_resolver_under_test_is_the_one_in_this_checkout() -> None:
    """A green suite run against a DIFFERENT tree is indistinguishable from a pass.

    These tests are usually run from a worktree that has no virtualenv of its
    own, so the interpreter comes from elsewhere and `PYTHONPATH` decides which
    `jobtracker` is imported. If it decides wrongly, every assertion below
    grades a file nobody edited.
    """

    repo = Path(__file__).resolve().parents[2]
    imported = p.__file__
    assert imported is not None
    assert Path(imported).resolve().is_relative_to(repo), (
        f"pipeline imported from {imported}, outside {repo}"
    )


def test_the_relay_brand_constant_matches_the_sender() -> None:
    """The branch under test is ATS-only, so a wrong brand is a dead suite."""

    assert p._domain_brand(ATS.split("@", 1)[1]) == BRAND
    assert BRAND in p.ATS_RELAY_DOMAINS


# ── the defect: a one-word cut of a refused run ──────────────────────────────


#: The three shapes measured as still minting after #733, plus two of the same
#: family. Every one is an ordinary ATS subject, not an adversarial string, and
#: every one resolved to a company named after an adjective before this fix.
CUT_FROM_A_REFUSED_RUN = [
    pytest.param("Phone Interview - Larkspur", "Phone", id="phone"),
    pytest.param("Final Interview Details | Larkspur", "Final", id="final"),
    pytest.param("Important Update | Larkspur", "Important", id="important"),
    pytest.param("Quick Update | Larkspur", "Quick", id="quick"),
    pytest.param("Video Interview - Kestrel", "Video", id="video"),
]


@pytest.mark.parametrize("subject,minted", CUT_FROM_A_REFUSED_RUN)
def test_a_one_word_cut_of_a_refused_run_is_not_an_employer(subject: str, minted: str) -> None:
    """This is the filing path: what it returns becomes a card on the board."""

    assert p.resolve_employer(ATS, subject, None) is None, (
        f"{subject!r} minted a company called {minted!r} out of a fragment left "
        "behind by cutting a run this module had just refused"
    )


@pytest.mark.parametrize("subject,minted", CUT_FROM_A_REFUSED_RUN)
def test_the_refusal_comes_from_the_evidence_guard_not_an_empty_branch(
    subject: str, minted: str
) -> None:
    """THE ANTI-DEAD-PROBE CONTROL for the assertions above.

    A `None` from `resolve_employer` proves nothing on its own — the segment
    branch may simply never have been offered a candidate. These subjects DO
    reach it, with the one-word fragment second in the list, which is precisely
    the position the exemption is now denied at.
    """

    candidates = p._lead_segment_candidates(subject)
    assert len(candidates) == 2, candidates
    assert candidates[1] == minted, candidates
    assert p._employer_from_subject_segment(subject, BRAND) is None


# ── the other direction: the exemption is still doing its job ────────────────


#: Each of these is answered BY THE SEGMENT READER — asserted below through
#: `_employer_from_subject_segment` as well as `resolve_employer`, so a control
#: cannot pass because an earlier step in the resolver happened to answer first.
STILL_RESOLVES = [
    # A one-word segment: the shape the exemption exists for. The whole segment
    # is the company, and no cut was taken.
    pytest.param("Kestrel | Application Received", ("kestrel", "Kestrel"), id="one-word-segment"),
    pytest.param(
        "Larkspur | Interview Request", ("larkspur", "Larkspur"), id="one-word-other-tail"
    ),
    # A cut, but a MULTI-WORD one that carries a corporate word.
    pytest.param(
        "Northwind Labs Application | <CANDIDATE>",
        ("northwind", "Northwind Labs"),
        id="multi-word-cut-corporate",
    ),
    # #512's shape. The run "<Employer> Follow-Up" is never offered, because the
    # segment has a remainder, so the cut arrives ALONE at index 0 and keeps the
    # exemption. This is the case that rules out "refuse every cut".
    pytest.param(
        "Larkspur Follow-Up for <ROLE> | <CANDIDATE>",
        ("larkspur", "Larkspur"),
        id="lifecycle-object-cut-first",
    ),
    pytest.param(
        "Kestrel Interview Invitation for <ROLE> | <CANDIDATE>",
        ("kestrel", "Kestrel"),
        id="lifecycle-object-longer-run",
    ),
    # A one-word cut in the DENIED position that earns its evidence another way.
    # The guard falls through to the word loop instead of returning False, so an
    # acronym still resolves — "must earn evidence some other way", not "may not".
    pytest.param("KVX Interview | <CANDIDATE>", ("kvx", "KVX"), id="denied-position-acronym"),
]


@pytest.mark.parametrize("subject,expected", STILL_RESOLVES)
def test_a_segment_that_really_names_an_employer_still_resolves(
    subject: str, expected: tuple[str, str]
) -> None:
    assert p._employer_from_subject_segment(subject, BRAND) == expected, (
        f"{subject!r} stopped resolving in the segment reader itself"
    )
    assert p.resolve_employer(ATS, subject, None) == expected


def test_the_sender_name_door_keeps_the_one_word_exemption() -> None:
    """The fix is scoped to the SUBJECT site, and this is what says so.

    `_carries_corporate_evidence` guards two doors. A display name is a shape
    the sender chose — "Larkspur" really is how a one-word employer signs its
    ATS mail — so nothing about a fragment cut out of a subject line has any
    bearing on it. A fix applied to the function instead of to the caller would
    take these two with it and would pass every assertion above.
    """

    assert p.resolve_employer(ATS, "Next steps", "Larkspur") == ("larkspur", "Larkspur")
    assert p.resolve_employer(ATS, "Next steps", "Kestrel Hiring Team") == (
        "kestrel",
        "Kestrel",
    )


# ── the price, recorded ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject",
    [
        "Larkspur Interview | <CANDIDATE>",
        "Kestrel Application Received | <CANDIDATE>",
    ],
)
def test_a_one_word_employer_in_front_of_a_lifecycle_word_is_the_price(
    subject: str,
) -> None:
    """A COST, pinned as a cost. These are not refusals anyone wanted.

    "<OneWordEmployer> <Lifecycle> | <Candidate>" is an ordinary ATS subject,
    and its employer is now the second reading of a segment whose first reading
    ("Larkspur Interview") carries no corporate evidence. Both resolved to their
    employer before this fix and resolve to nothing after it, so the message
    goes to the review queue instead of onto the board.

    That is the direction this path chooses everywhere — a queued row costs a
    click, a wrong card costs trust — and the same trade the #537 refusal of an
    ampersand employer already pays. It is written down here so that the price
    is visible in the gate rather than discovered on a board, and so that a
    later rule which recovers these has a failing test to announce it.
    """

    assert p.resolve_employer(ATS, subject, None) is None
