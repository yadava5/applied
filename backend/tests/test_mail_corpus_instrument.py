"""Structural invariants for the mail classification corpus.

READ THIS BEFORE ADDING AN ASSERTION HERE.

Every check in this file is about the CORPUS — its size, its coverage, its
determinism, its honesty about where its text came from. Not one of them is
about how well the classifier scores, and none may be added. The corpus is an
instrument; the honest pass rate is not yet known, and an accuracy threshold
chosen to match today's output is a gate that cannot fail — which is the exact
defect shape this corpus was built to hunt. Thresholds get asserted in a later
change, from numbers that exist.

What these checks are worth: a corpus that silently shrinks, loses a defect
class, drifts to one sender type, or stops being deterministic reports numbers
that look fine and mean nothing.
"""

from __future__ import annotations

import base64

import pytest

from tests.corpus.mail import (
    ATS_SENDERS,
    CALENDAR_SENDERS,
    CATEGORIES,
    PROVENANCES,
    TOTAL,
    WEIGHTING,
    collapse,
    generate,
)
from tests.corpus.mail_report import derive, run

CASES = generate()


def test_corpus_is_the_declared_size_and_shape() -> None:
    assert len(CASES) == TOTAL == 404
    for category, want in WEIGHTING.items():
        got = sum(1 for c in CASES if c.expected == category)
        assert got == want, f"{category}: {got} cases, budgeted {want}"
    assert {c.expected for c in CASES} == set(CATEGORIES)


def test_generation_is_deterministic() -> None:
    """A corpus that differs between runs cannot be compared with itself."""

    a, b = generate(), generate()
    assert [(x.case_id, x.subject, x.sender, x.snippet) for x in a] == [
        (y.case_id, y.subject, y.sender, y.snippet) for y in b
    ]
    assert [x.payload for x in a] == [y.payload for y in b]


def test_no_two_cases_are_the_same_message() -> None:
    seen = {(c.subject, str(c.payload), c.snippet) for c in CASES}
    assert len(seen) == len(CASES)


def test_every_confusion_pair_is_present_and_none_rests_on_flavour() -> None:
    """P1-P13 must all exist, and none may be built from INFERRED text alone.

    An INFERRED-only pair would let a number derived from invented flavour be
    cited later as evidence about real mail.

    P12 and P13 landed on 2026-08-21 with the ``P12-conditional`` axis. P12 is
    the conditional/asserted pair for "you were not selected"; P13 is the same
    marketing footer under a confirmation and under a real rejection. Both are
    COLLECTED — the shape came from real mail that cost the owner four
    applications, reproduced under an invented employer.
    """

    by_pair: dict[str, set[str]] = {}
    for case in CASES:
        if case.pair:
            by_pair.setdefault(case.pair, set()).add(case.provenance)
    assert sorted(by_pair, key=lambda p: int(p[1:])) == [f"P{i}" for i in range(1, 14)]
    for pair, provenances in by_pair.items():
        assert provenances - {"INFERRED"}, f"{pair} rests on INFERRED text alone"


def test_provenance_is_declared_and_mostly_spec_grounded() -> None:
    assert {c.provenance for c in CASES} <= set(PROVENANCES)
    grounded = sum(1 for c in CASES if c.provenance != "INFERRED")
    assert grounded > len(CASES) / 2, "corpus has drifted toward invented flavour"


@pytest.mark.parametrize(
    "defect",
    [
        "truncation:snippet-30",
        "truncation:snippet-150",
        "truncation:snippet-300",
        "truncation:body-600",
        "truncation:body-4500",
        "encoding:quoted-printable",
        "encoding:qp-soft-break-in-verdict",
        "encoding:base64-not-decoded",
        "subject:encoded-word-Q",
        "subject:encoded-word-B",
        "subject:encoded-word-folded",
        "subject:empty",
        "subject:whitespace-only",
        "subject:overlong-verdict-at-480",
        "subject:overlong-verdict-at-520",
        "subject:bare-req-id",
        "subject:emoji",
        "subject:external-prefix",
        "subject:stacked-re",
        "subject:aw-de",
        "subject:japanese",
        "html:only",
        "html:table",
        "html:tracking-pixel",
        "html:hidden-preheader-contradicts",
        "html:style-block",
        "calendar:request",
        "calendar:reschedule",
        "calendar:cancel",
        "calendar:reply",
        "calendar:rsvp-echo",
        "calendar:no-plain-sibling",
        "locale:es",
        "locale:de",
        "locale:fr",
        "locale:ja",
        "locale:bilingual-en-fr",
        "locale:rtl-ar",
        "thread:quote-disagrees",
        "wrapper:mobile-signature",
    ],
)
def test_defect_class_is_covered(defect: str) -> None:
    assert any(defect in c.defects for c in CASES), f"no case carries {defect}"


def test_sender_mix_does_not_lean_on_the_ats_bonus() -> None:
    """25-30% of ATS-origin mail must come from a COMPANY domain.

    Customers rebrand their ATS to ``no-reply@theircompany.com``, so the sender
    signal is present-or-absent and never reliably negative. A corpus that is
    100% relay silently measures the +0.05 bonus instead of the text.
    """

    ats = [c for c in CASES if c.ats_origin]
    company = [c for c in ats if c.sender not in set(ATS_SENDERS)]
    share = len(company) / len(ats)
    assert 0.25 <= share <= 0.30, f"company-domain share is {share:.1%}"


def test_offers_mostly_come_from_a_human_on_the_company_domain() -> None:
    """Which is exactly what denies them the ATS confidence bonus."""

    offers = [c for c in CASES if c.expected == "offer"]
    relays = [c for c in offers if c.sender in set(ATS_SENDERS)]
    assert len(relays) / len(offers) < 0.25


def test_no_real_employer_names() -> None:
    """The repository is not private and the owner's mailbox holds real
    applications, so no real company may appear as an EMPLOYER.

    Real *vendors* are a different matter and are deliberately present: the
    calendar sender ``calendar-notification@google.com`` and the ATS relay
    domains are VERIFIED facts about how this mail arrives, and inventing
    fictional ones would make the sender axis measure nothing. They are allowed
    only where they belong — on the calendar and relay cases.
    """

    real_employers = ("amazon", "meta ", "apple", "microsoft", "stripe", "roblox",
                      "verkada", "anthropic", "netflix", "uber", "openai", "datadog")
    for case in CASES:
        blob = (case.subject + " " + case.sender + " " + case.snippet).lower()
        for name in real_employers:
            assert name not in blob, f"{case.case_id} names {name}"
        if "google" in blob:
            assert case.sender in CALENDAR_SENDERS, (
                f"{case.case_id} mentions Google outside a calendar case"
            )


def test_placed_verdicts_land_where_the_case_says_they_do() -> None:
    """The label must describe the fixture, not the intention.

    Two separate things are asserted, and the second is the one that matters.

    1. ``verdict_offset`` agrees with the body — internal consistency.
    2. The ACHIEVED offset is within a few characters of the REQUESTED target.

    Check 1 alone is a tautology: the generator computes the offset from the
    body it just built, so recomputing it can never disagree. It was written
    that way first, a deliberate mutation of the padding helper (``+ 40``) was
    applied, and both checks passed — the exact cannot-fail shape this corpus
    exists to hunt, reproduced inside its own test file. Check 2 is what would
    have caught the real bug: whitespace collapse happens BEFORE the 4000-char
    cap and the first padding helper moved in ~130-character steps, so a case
    labelled "verdict at 150" actually placed it at 227 — outside the very
    snippet it existed to sit inside.
    """

    checked = 0
    targeted = 0
    for case in CASES:
        if case.verdict_offset is None or case.verdict_text is None:
            continue
        if case.verdict_in == "subject":
            window = case.subject
        elif "full_body" in case.extra:
            window = case.extra["full_body"]  # header-only: nothing decodes it
        else:
            window = base64.urlsafe_b64decode(case.payload["body"]["data"]).decode()
        assert collapse(window).index(collapse(case.verdict_text)) == case.verdict_offset, (
            f"{case.case_id}: label says {case.verdict_offset}, fixture says "
            f"{collapse(window).index(collapse(case.verdict_text))}"
        )
        checked += 1

        target = case.extra.get("verdict_target")
        if target is None:
            continue
        # +-a few characters: word-boundary padding cannot always land exactly,
        # and the tolerance is far tighter than any drift that would matter
        # (150 vs 227 was the real bug).
        assert target - 2 <= case.verdict_offset <= target + 4, (
            f"{case.case_id}: asked for offset {target}, fixture placed the verdict "
            f"at {case.verdict_offset} — the label and the fixture disagree"
        )
        targeted += 1

    # Positive controls on the checks themselves: a silent zero in either would
    # read as "all offsets correct" while meaning "no offset was ever examined".
    assert checked >= 25, f"only {checked} placed verdicts were checked"
    assert targeted >= 25, f"only {targeted} offsets were checked against a target"


def test_truncation_cases_are_actually_truncated() -> None:
    """The 4500 and snippet-300 placements must genuinely put the verdict out
    of reach, and the snippet-30 control must genuinely keep it in reach.

    Without the control the whole column could read "invisible" because the
    fixture is broken rather than because the budget is real.
    """

    outcomes = {o.case_id: o for o in run()}
    for case in CASES:
        o = outcomes[case.case_id]
        if "truncation:snippet-30" in case.defects:
            assert o.verdict_complete is True, f"{case.case_id} control is not visible"
        if "truncation:snippet-300" in case.defects:
            assert o.verdict_starts_visible is False, case.case_id
        if "truncation:body-4500" in case.defects:
            assert o.verdict_starts_visible is False, case.case_id
        if "truncation:body-600" in case.defects:
            assert o.verdict_complete is True, case.case_id


def test_calendar_only_messages_really_fall_back_to_the_snippet() -> None:
    """The structural claim the calendar axis rests on, asserted rather than
    assumed: ``extract_body_text`` handles text/plain and text/html and nothing
    else, so a text/calendar part with no plain sibling yields no body text."""

    calendar_only = [c for c in CASES if "calendar:no-plain-sibling" in c.defects]
    assert calendar_only
    for case in calendar_only:
        assert derive(case) == case.snippet


def test_header_only_messages_classify_on_a_gmail_sized_snippet() -> None:
    snippet_cases = [
        c for c in CASES if any(d.startswith("truncation:snippet") for d in c.defects)
    ]
    assert snippet_cases
    for case in snippet_cases:
        text = derive(case)
        assert text == case.snippet
        assert len(text) <= 186


def test_the_report_scores_every_case_into_exactly_one_bucket() -> None:
    outcomes = run()
    assert len(outcomes) == TOTAL
    assert {o.bucket for o in outcomes} <= {"correct", "wrong", "abstained"}
    assert len({o.case_id for o in outcomes}) == TOTAL
    # An abstention is a real state of the classifier, not a scoring artefact:
    # it must never be recorded above the auto-file gate.
    for o in outcomes:
        if o.bucket == "abstained":
            assert not o.auto_filed
            assert o.no_positive_evidence
