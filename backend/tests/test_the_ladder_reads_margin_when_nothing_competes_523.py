"""The ladder read absolute score before margin, and the sender broke the tie (#523).

WHAT THE ISSUE REPORTS. A textbook acknowledgement from an employer's own mail
system scores ``applied`` 5 with no other category above zero, lands on the
``winner >= 4 and margin >= 2`` rung at 0.80, gets no relay bonus, and waits in
the review queue. The same message over Greenhouse is ``0.80 + 0.05`` = 0.85 —
``pipeline.AUTO_FILE_GATE`` exactly — and files itself. Two identical verdicts on
opposite sides of the gate, separated by who sent the mail.

WHY THE FIXTURE IS A TRANSCRIPTION AND NOT A WORDING WRITTEN HERE.
``docs/CLASSIFIER_RULES_GOVERNANCE.md`` refuses a pattern family derived from
wordings the rule's author wrote, and DEC-013 declined a fix for #768 on exactly
that ground. The message below is ``observed.OBSERVED_CONFIRMATIONS[6]``,
provenance ``in-house, thread 19ff97772e932c0f`` — the transcription of the
production message #523 quotes. Its index is not trusted blind: the test asserts
the provenance of the template it picks, so re-ordering that tuple reds here
rather than silently grading a different letter.

WHAT THIS FILE CANNOT SHOW, said plainly rather than left to read as coverage.

  * **The ``runner_up_score <= 0`` guard's BEHAVIOUR is ungraded.** Every case
    in the 19,420-message corpus whose winner scores 4 or 5 has a runner-up of
    exactly 0, so mutating the guard to ``<= 3`` moves no verdict anywhere: not
    in the corpus, not in the four committed eval corpora, not on the owner's
    board. What does red on that mutation is
    ``test_the_documented_ladder_is_the_ladder_in_the_code``, because the
    docstring says ``<= 0`` and the code would say ``<= 3`` — the STATEMENT is
    gated and the behaviour is not, and those are different things. The guard is
    kept because without it a winner of 5 against a runner-up of 4 is a margin of
    1, which the ladder rates 0.70, and it must not reach 0.90.
  * **The ``applied`` scope is graded, and it was added because it had to be.**
    All 273 corpus cases the rung moves win ``applied``, and the first version of
    this change read that as licence to leave the rung category-agnostic. The
    corpus does not exercise the generalisation; the repository's own fixtures
    do. ``test_ingestion_hole_166.py`` classifies a real ``interview`` row with
    NO sender at 5/0 and asserts 0.80, under the gate, because that is #260's
    lookalike protection. Unscoped, this rung gave it 0.90 from any sender.
    Removing the scope reds that test and both of #775's.

The bound that IS graded is the other one — see
``test_the_rung_is_bounded_below_at_five``, whose population is #814's 260 cards.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jobtracker.classifier.rules import ATS_DOMAINS, RulesClassifier, winner_first
from jobtracker.cloud import pipeline

from tests.corpus_independent import observed
from tests.corpus_independent.generate import generate
from tests.corpus_independent.harness import as_classified

#: The relay half of the pair, read off the shipped list rather than typed, so a
#: rename there cannot leave a dead address here still passing as a relay.
RELAY_SENDER = f"no-reply@{ATS_DOMAINS[0]}"

#: The in-house half. Reserved TLD, per ``docs/TEST_DATA_POLICY.md``.
IN_HOUSE_SENDER = "careers@arcgrove.example"

FILL = {"display": "Arcgrove", "role": "Software Engineer", "req": "R-100001"}

#: The ladder as ``rules.py`` documents it, in the order the code tries it.
RULES_SOURCE = Path(pipeline.__file__).parent.parent / "classifier" / "rules.py"


@pytest.fixture(scope="module")
def classifier() -> RulesClassifier:
    return RulesClassifier()


@pytest.fixture(scope="module")
def graded(classifier):
    """Every corpus case with the two numbers the ladder reads."""

    out = []
    for case in generate():
        result = classifier.classify(case.subject, as_classified(case), case.sender)
        ordered = winner_first(result.scores)
        winner = ordered[0][1] if ordered else 0
        runner_up = ordered[1][1] if len(ordered) > 1 else 0
        out.append((case, result, winner, runner_up))
    return out


def _shape(result) -> tuple[int, int]:
    ordered = winner_first(result.scores)
    winner = ordered[0][1] if ordered else 0
    runner_up = ordered[1][1] if len(ordered) > 1 else 0
    return winner, runner_up


def _notion_template() -> tuple[str, str]:
    """The transcribed message #523 reports, found by its provenance."""

    matches = [
        t
        for t in observed.OBSERVED_CONFIRMATIONS
        if t[2].startswith("in-house, thread 19ff97772e932c0f")
    ]
    assert len(matches) == 1, (
        "the template this issue is about is identified by its provenance and "
        f"{len(matches)} templates carry it; observed.py was re-ordered or "
        "re-provenanced and this test is no longer grading that message"
    )
    subject, body, _ = matches[0]
    return subject.format(**FILL), body.format(**FILL)


def test_the_documented_ladder_is_the_ladder_in_the_code() -> None:
    """The prose above ``RulesClassifier`` against the code below it.

    Five rungs are written out in English in the class docstring and
    implemented in Python forty lines down, and nothing checked that the two
    agreed. This estate's recurring defect is a document describing a gate it no
    longer matches, so the comparison is made rather than trusted.

    BOTH COLUMNS, and the second one is why this test was rewritten. Comparing
    only the confidence literals looks like a gate and is blind to the mutation
    that matters: ``>= 5`` becoming ``>= 4`` leaves every ``confidence = 0.9x``
    in place, so a confidence-only check stays green while the docstring's
    "score >= 5" becomes false. The numbers inside each PREDICATE are compared
    too, as a set, which is what makes a bound change red here.
    """

    source = RULES_SOURCE.read_text()

    documented = []
    for match in re.finditer(r"^\s+- (score >= .*?): (0\.\d+)$", source, re.M):
        predicate, confidence = match.group(1), match.group(2)
        documented.append((frozenset(int(n) for n in re.findall(r"\d+", predicate)), confidence))

    body = source[source.index("        # Base confidence on score and margin") :]
    body = body[: body.index("        # Boost confidence for ATS emails")]
    coded = []
    for match in re.finditer(
        r"^\s+(?:el)?if (.+?):\n(?:\s+#.*\n)*\s+confidence = (0\.\d+)$", body, re.M
    ):
        condition, confidence = match.group(1), match.group(2)
        coded.append((frozenset(int(n) for n in re.findall(r"\b\d+\b", condition)), confidence))

    assert len(documented) == 5, (
        f"{len(documented)} rungs are written out in the docstring, expected 5"
    )
    assert len(coded) == 5, (
        f"the ladder parsed to {len(coded)} branches, expected 5. The comment "
        "markers this test slices between moved, so it is reading the wrong "
        "block rather than finding a disagreement."
    )
    assert documented == coded, (
        "the ladder in the docstring and the ladder in the code disagree.\n"
        f"  documented {[(sorted(n), c) for n, c in documented]}\n"
        f"  coded      {[(sorted(n), c) for n, c in coded]}\n"
        "A rung added, removed or re-bounded in one and not the other is a "
        "false claim about the product in the file that defines it."
    )


def test_the_message_this_issue_reports_no_longer_depends_on_its_sender(classifier):
    """THE ONE-SLOT PAIR, and the only thing it varies is the sender.

    Identical rendered subject and body; a relay address against the employer's
    own domain. Before the rung the in-house arm was 0.80 and waited for a
    person while the relay arm was 0.85 and filed itself.
    """

    subject, body = _notion_template()

    relay = classifier.classify(subject, body, RELAY_SENDER)
    in_house = classifier.classify(subject, body, IN_HOUSE_SENDER)

    # The shape the rung keys on, asserted rather than assumed: a pattern drift
    # that moved this wording to a winner of 6 would leave the rung unexercised
    # and every assertion below still green.
    assert _shape(relay) == (5, 0), f"the transcription scores {_shape(relay)}, not (5, 0)"
    assert _shape(in_house) == (5, 0)

    assert relay.category.value == "applied"
    assert in_house.category.value == "applied"

    assert in_house.confidence >= pipeline.AUTO_FILE_GATE, (
        f"the message #523 reports still scores {in_house.confidence} from the "
        "employer's own domain, under the auto-file gate"
    )
    assert relay.confidence >= pipeline.AUTO_FILE_GATE
    # The point of the issue: the sender no longer decides whether a person is
    # asked. It still moves the number, which is what a relay bonus is for.
    assert in_house.confidence == 0.90
    assert relay.confidence == 0.95


def test_the_rung_is_bounded_below_at_five(graded, classifier) -> None:
    """THE FENCE IN FRONT OF #814, and its population is that issue's 260 cards.

    ``winner == 4 and runner-up <= 0`` is 567 corpus cases and 480 of them are
    ``offer`` and ``rescinded-offer`` — the cards that file one ULP over the
    gate today. Widening the rung to ``>= 4`` raises exactly those. So the bound
    is 5 because of what sits at 4, not because 5 is a round number.

    Read through a NON-RELAY sender so the +0.05 bonus is out of the arithmetic
    and the assertion is about the ladder rather than about the sender.
    """

    at_four = [
        (case, result)
        for case, result, winner, runner_up in graded
        if winner == 4 and runner_up <= 0
    ]
    assert len(at_four) > 400, (
        f"only {len(at_four)} cases sit at winner 4; this gate is worth its "
        "population and the population moved"
    )
    families = {case.family for case, _ in at_four}
    assert {"offer", "rescinded-offer"} <= families, (
        f"the #814 families are no longer in this population: {sorted(families)}"
    )

    for case, _ in at_four:
        probe = classifier.classify(case.subject, as_classified(case), IN_HOUSE_SENDER)
        assert probe.confidence == 0.80, (
            f"a winner-4 verdict ({case.family}, {case.message_id}) now reads "
            f"{probe.confidence} off the ladder. The rung reached one point "
            "lower than it may, and #814's 260 cards moved with it."
        )


def test_no_verdict_the_rung_raises_had_evidence_against_it(graded) -> None:
    """``runner_up <= 0`` must mean UNCONTESTED, not merely unopposed.

    A score of 5 is reachable as 6 + 3 + 1 − 5: two strong hits and a NEGATIVE
    against the winner. The ladder cannot see the composition, so this reads it
    off ``matched_patterns`` and attributes every negative to its owning
    category by parsing ``rules.py`` — not by a copied list, which would drift.

    Measured at the time of writing: 43 of the 249 carry negatives, and every
    one belongs to ``offer`` or ``pending_application``, which is WHY the
    runner-up is at or below zero rather than evidence against the winner.
    """

    source = RULES_SOURCE.read_text()
    owner: dict[str, set[str]] = {}
    category = tier = None
    for line in source.splitlines():
        found = re.search(r"EmailCategory\.([A-Z_]+): CategoryPatterns\(", line)
        if found:
            category, tier = found.group(1).lower(), None
        found = re.match(r"\s*(strong|weak|negative)=\[", line)
        if found:
            tier = found.group(1)
        found = re.match(r'\s*r?"(.*)",\s*$', line)
        if found and category and tier == "negative":
            owner.setdefault(found.group(1), set()).add(category)
    assert len(owner) > 20, (
        f"the negative-pattern census parsed {len(owner)} literals out of "
        "rules.py; the parse broke and this test would pass on anything"
    )

    contested = []
    on_the_rung = 0
    for case, result, winner, runner_up in graded:
        if not (winner == 5 and runner_up <= 0):
            continue
        on_the_rung += 1
        for pattern in result.matched_patterns:
            if not pattern.startswith("[NEGATIVE] "):
                continue
            if result.category.value in owner.get(pattern[len("[NEGATIVE] ") :], set()):
                contested.append((case.family, case.message_id, pattern))

    assert on_the_rung > 200, (
        f"{on_the_rung} cases sit on the rung; the population moved and the "
        "zero below is worth less than it was"
    )
    assert not contested, (
        f"{len(contested)} verdicts the rung raises to 0.90 carry a negative "
        f"against their OWN winning category: {contested[:5]}. The runner-up "
        "being at zero no longer means nothing argued against the winner."
    )
