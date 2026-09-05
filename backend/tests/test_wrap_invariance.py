"""#430, THE OTHER HALF: WRAPPING A BODY MUST NOT CHANGE A VERDICT.

``cloud/gmail_client.extract_body_text`` no longer collapses newlines, because
``rules._QUOTE_BOUNDARY`` is ``^``-anchored under ``re.MULTILINE`` and a
one-line body made ``strip_quoted_history`` dead code on the request path. That
fix hands the rules layer a shape it had never been asked to read: real
``text/plain`` from an ATS is hard-wrapped at 72-78 columns, so a sentence now
arrives split across lines.

85 of the shipped patterns carry a bounded gap of the form ``.{0,N}``. ``.``
does not match ``\\n`` and nothing sets ``re.DOTALL``, so every one of them
stops bridging a wrap point the moment one exists. Measured before
``reflow_paragraphs`` existed: with every body wrapped at 72 columns, auto-files
fell from 244 to 212 -- 32 cards that used to settle themselves waiting for a
human, almost all of them still CORRECT, just demoted under the 0.85 gate. The
regression sits on the path production PREFERS, since ``extract_body_text``
takes ``text/plain`` whenever a part offers one.

``reflow_paragraphs`` spends the newlines on the quote boundary and gives them
back before the patterns run. These are the gates on that.

THE SEQUENCING TRAP, and it is why the extractor change and the reflow have to
ship together. Against the OLD extractor gate 1 is VACUOUSLY GREEN: that
extractor collapsed everything, so the wrap changed its output for 0 of 404
cases and any wrap-invariance assertion passed without testing anything. It
only becomes a real gate once the line structure survives -- measured, the wrap
now changes the derived string for 354 of 404. A gate that cannot fail is the
defect this file exists to avoid, so the mutation below is not optional
decoration; it is the proof.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.classifier import rules as rules_module
from jobtracker.classifier.rules import get_rules_classifier, reflow_paragraphs
from jobtracker.cloud.pipeline import AUTO_FILE_GATE

from .corpus.mail import generate, generate_wrapped
from .corpus.mail_report import derive, run

#: Measured on this corpus at the commit that introduced the reflow. Floors,
#: not targets: they may only be raised. Sourced from the run, then checked in
#: -- if the pair cannot reach them the number gets reported, not the floor
#: adjusted.
CORRECT_FLOOR = 342  # what the OLD extractor scored; the pair must not regress
AUTO_FILED_WRONG_CEILING = 5


def _vectors(wrapped: bool) -> dict[str, tuple[str, float]]:
    """Per case, the two things a person actually receives."""

    return {o.case_id: (o.actual, o.confidence) for o in run(wrapped=wrapped)}


# ── gate 1: wrap-invariance ──────────────────────────────────────────────────


def test_the_wrap_reaches_the_classifier_at_all() -> None:
    """THE CONTROL ON THE GATE BELOW, and it has to come first.

    If wrapping changed nothing about the string the classifier reads, gate 1
    would pass for the same reason it passed against the old extractor: because
    it was comparing a thing to itself. This asserts the instrument has a
    subject before the gate asserts a verdict about it.
    """

    changed = sum(
        1 for u, w in zip(generate(), generate_wrapped(), strict=True) if derive(u) != derive(w)
    )
    assert changed > 300, (
        f"the 72-column wrap changes the derived string for only {changed} "
        "cases. Either the wrap is not reaching text/plain parts or the "
        "extractor is collapsing newlines again -- in both cases the "
        "invariance gate below is vacuous."
    )


def test_the_corpus_reads_the_same_wrapped_and_unwrapped() -> None:
    """GATE 1. Per-case verdict AND confidence, never the counts.

    Counts are asserted separately in gate 3 and they are the weaker claim:
    two cases swapping verdicts leaves every total identical, and a pair of
    agreeing counters hiding a pair of disagreeing cases is a defect this
    estate has shipped before.

    ``matched_patterns`` is deliberately NOT compared. Wrapping moves where the
    4000-character cap lands on a long body, so the pattern list can differ by
    a tail match without the verdict moving; asserting on it would produce a
    red that is not a defect.
    """

    unwrapped, wrapped = _vectors(False), _vectors(True)
    assert unwrapped.keys() == wrapped.keys()
    disagreeing = {k: (unwrapped[k], wrapped[k]) for k in unwrapped if unwrapped[k] != wrapped[k]}
    assert not disagreeing, (
        f"{len(disagreeing)} cases read differently once their body is wrapped "
        f"the way a mailer sends it: {dict(list(disagreeing.items())[:8])}. A "
        "bounded .{0,N} gap died on a wrap point."
    )


def test_without_the_reflow_the_wrapped_corpus_craters(monkeypatch) -> None:
    """THE MUTATION. A gate nobody has watched fail is not a gate.

    Disables only ``reflow_paragraphs`` -- the extractor still preserves line
    structure, the quote strip still runs, no pattern is touched -- and the
    wrapped corpus must come apart. If this passes, gate 1 above is measuring
    nothing and the reflow could be deleted without a red.
    """

    monkeypatch.setattr(rules_module, "reflow_paragraphs", lambda text: text)
    unwrapped, wrapped = _vectors(False), _vectors(True)
    disagreeing = [k for k in unwrapped if unwrapped[k] != wrapped[k]]
    assert len(disagreeing) > 25, (
        f"with the reflow disabled only {len(disagreeing)} cases moved under "
        "wrapping. The gate above cannot fail, so it is not protecting "
        "anything."
    )
    filed_u = sum(1 for o in run(wrapped=False) if o.auto_filed)
    filed_w = sum(1 for o in run(wrapped=True) if o.auto_filed)
    assert filed_w < filed_u - 20, (
        f"auto-files went {filed_u} -> {filed_w} with the reflow off; the "
        "measured collapse was 243 -> 212 and this control expects to see it."
    )


# ── gate 2: a bounded gap must not cross a paragraph ─────────────────────────

#: A real shipped pattern, fetched from the compiled classifier rather than
#: retyped, so this gate tracks the rule instead of a copy of it.
_GAP_PATTERN = r"next step.{0,30}(assessment|test)"

TRIGGER = "We were impressed and would like to move to the next step."
COMPLETION = "Assessment instructions are in the attached document."


def _shipped_gap_pattern() -> re.Pattern[str]:
    clf = get_rules_classifier()
    for kind in ("strong", "weak"):
        for pattern in clf._compiled_patterns["assessment"].get(kind, ()):
            if pattern.pattern == _GAP_PATTERN:
                return pattern
    raise AssertionError(
        f"{_GAP_PATTERN!r} is no longer in the assessment rules. This gate was "
        "written around it; re-point it at another bounded gap rather than "
        "deleting the gate -- 85 patterns carry one."
    )


def test_a_bounded_gap_does_not_reach_across_a_paragraph() -> None:
    """GATE 2, the negative. A paragraph break is a real boundary.

    This is what ``reflow_paragraphs`` BUYS by keeping ``\\n\\n``: after it,
    ``.`` refusing to cross a newline means "does not cross a PARAGRAPH", which
    is the reading every bounded gap assumed when it was written against a
    single-line body. A blanket ``re.DOTALL`` would delete this property and
    let ``next step.{0,20}interview`` match across "...as a next
    step.\\n\\nInterview prep newsletter...", manufacturing wrong auto-files the
    old shape never produced.
    """

    across = reflow_paragraphs(f"{TRIGGER}\n\n{COMPLETION}")
    assert "\n\n" in across, "the reflow must keep the paragraph break itself"
    assert _shipped_gap_pattern().search(across) is None, (
        f"the gap bridged a paragraph boundary: {across!r}"
    )


def test_the_same_words_inside_one_paragraph_do_match() -> None:
    """GATE 2's DIRECTION. Without this the negative above proves nothing --
    a pattern that never matches anything would also pass it."""

    within = reflow_paragraphs(f"{TRIGGER}\n{COMPLETION}")
    assert "\n" not in within, "a single newline is interior to a paragraph"
    assert _shipped_gap_pattern().search(within) is not None, (
        f"the gap failed to bridge a WRAP point inside one paragraph: "
        f"{within!r}. That is the regression this whole change exists to stop."
    )


def test_a_dotall_build_would_cross_the_paragraph() -> None:
    """The case sitting ON the boundary, so the negative has a direction.

    Same text, same pattern, one flag different. This is the alternative that
    was refused, shown doing the thing it was refused for.
    """

    across = reflow_paragraphs(f"{TRIGGER}\n\n{COMPLETION}")
    dotall = re.compile(_shipped_gap_pattern().pattern, re.IGNORECASE | re.DOTALL)
    assert dotall.search(across) is not None, (
        "under re.DOTALL the gap DOES cross the paragraph. If this ever stops "
        "being true the negative above has lost its direction and passes for "
        "the wrong reason."
    )


# ── gate 3: the corpus floor ─────────────────────────────────────────────────


def test_the_pair_does_not_regress_the_corpus() -> None:
    """GATE 3. Weaker than gate 1 and kept because it says something else:
    gate 1 says the two runs AGREE, this says what they agree on is good."""

    outcomes = run()
    correct = sum(1 for o in outcomes if o.bucket == "correct")
    filed_wrong = sum(1 for o in outcomes if o.auto_filed and o.bucket != "correct")
    assert correct >= CORRECT_FLOOR, (
        f"{correct} correct, under the {CORRECT_FLOOR} the old extractor "
        "scored. Report the number; do not lower the floor."
    )
    assert filed_wrong <= AUTO_FILED_WRONG_CEILING, (
        f"{filed_wrong} cases were auto-filed with the wrong verdict, over the "
        f"{AUTO_FILED_WRONG_CEILING} measured. A confident wrong answer is the "
        "worst thing this classifier can do."
    )


def test_wrapping_does_not_cost_a_single_auto_file() -> None:
    """The number the regression was loudest in: 244 -> 212 before the reflow.

    Implied by gate 1 and stated anyway, because this is the figure a person
    feels -- a card that used to settle itself and now waits.
    """

    filed_u = sum(1 for o in run(wrapped=False) if o.auto_filed)
    filed_w = sum(1 for o in run(wrapped=True) if o.auto_filed)
    assert filed_u == filed_w, (
        f"auto-files went {filed_u} unwrapped -> {filed_w} wrapped. Every one "
        f"of the difference is a card a person now has to touch."
    )
    assert AUTO_FILE_GATE == 0.85, "the gate moved; these numbers were measured at 0.85"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("one line", "one line"),
        ("a\nb", "a b"),
        ("a\n\nb", "a\n\nb"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("a  \n  b", "a b"),
        ("  leading\ntrailing  ", "leading trailing"),
    ],
)
def test_reflow_is_exactly_what_it_says(text: str, expected: str) -> None:
    """Spelled out, because the function is three lines and easy to 'simplify'
    into one that eats the paragraph breaks too."""

    assert reflow_paragraphs(text) == expected


def test_reflow_is_idempotent() -> None:
    body = "first para line one\nline two\n\n\nsecond para"
    once = reflow_paragraphs(body)
    assert reflow_paragraphs(once) == once
