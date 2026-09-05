"""Which LAYER answers, not merely what it answers. #775, requirement 2.

    "Assert which layer answers this item, not only what it answers."

`test_the_bare_noun_sits_under_its_siblings_758.py` gets close: it asserts the
target's rules-only confidence sits under `RULES_SHORT_CIRCUIT` and the
employer's invite sits at or over it. That is the right property measured
through a proxy, and the proxy has a gap — it runs the RULES classifier alone,
so it proves "hybrid's rules short-circuit will not fire", not "the learned
layer answered". Any other interception is invisible to it: the content filter,
an embeddings accept, or a new early return added above the short circuit.

This file closes that gap by asking `hybrid` itself and reading `result.method`.

WHY THE TWO CASES ARE A PAIR. Asserting only that the target reaches SetFit
would be satisfied by a cascade that never short-circuits at all, which would
be a different defect and a worse one — #119's pattern edit was defensible
precisely because an employer's imperative SHOULD be owned by the rules layer.
So the invite is asserted to stay `rules`, and its `setfit.calls == 0` is
asserted too: "SetFit agreed" and "SetFit was never asked" are different facts
and `method` alone cannot tell them apart.

Layers are injected through hybrid's own setters, which exist for this, so
neither `sentence-transformers` nor `setfit_model` is imported by this file and
it needs no checkpoint, no Docker and no network.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.hybrid import RULES_SHORT_CIRCUIT, HybridClassifier
from jobtracker.classifier.rules import PATTERNS, EmailCategory, RulesClassifier

#: The candidate's own report. Its body carries "take-home exercise", the
#: 18-character phrase that matched three ASSESSMENT patterns before #758.
TARGET_SUBJECT = "Follow-up after completing assessment"
TARGET_BODY = "I submitted the take-home exercise and wanted to check on timeline."

#: The employer's imperative. Same vocabulary, opposite speaker, and the rules
#: layer SHOULD own it — this is what #119 was protecting.
INVITE_SUBJECT = "Next step for your application"
INVITE_BODY = "Please complete the take-home exercise by Friday using the link below."


class _SilentEmbeddings:
    """Available, and declines to answer, so the cascade continues to layer 3.

    A layer that is *absent* and one that *abstains* reach SetFit by different
    routes, and only the abstaining one proves the ordering under test.
    """

    SIMILARITY_THRESHOLD = 0.85

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def has_known_examples(self) -> bool:
        return True

    async def classify(self, subject: str, body: str):
        self.calls += 1
        return None


class _AnsweringSetFit:
    """Layer 3, answering the way the real checkpoint does on this message.

    0.995 is not decoration: the real model answers this item `follow_up` at
    0.9951, measured on the committed checkpoint. Counting calls is what
    separates "SetFit agreed with the rules layer" from "SetFit never ran".
    """

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def classify(self, subject: str, body: str):
        self.calls += 1
        return (EmailCategory.FOLLOW_UP, 0.995)


def _classifier() -> tuple[HybridClassifier, _AnsweringSetFit]:
    classifier = HybridClassifier()
    # A FRESH rules layer, not the singleton `HybridClassifier.__init__` takes
    # from `get_rules_classifier()`. `RulesClassifier.__init__` PRECOMPILES
    # `PATTERNS` into `_compiled_patterns`, and the singleton is built the first
    # time anything asks for it — so a test that mutates `PATTERNS` and then goes
    # through the hybrid mutates nothing the engine will read, and its control
    # passes for the wrong reason. Measured: the third test below returned
    # `setfit` under a mutation that moves the rules layer 0.70 -> 0.90.
    classifier._rules = RulesClassifier()
    classifier._embeddings = _SilentEmbeddings()
    setfit = _AnsweringSetFit()
    classifier._setfit = setfit
    # If the cloud short-circuit is on, layer 3 does not exist and every case
    # below would pass by never running the code under test.
    assert not classifier._cloud_rules_only
    return classifier, setfit


@pytest.mark.asyncio
async def test_the_candidates_report_is_answered_by_the_learned_layer() -> None:
    """The property #775 asked for, stated directly rather than through 0.90."""

    classifier, setfit = _classifier()
    result = await classifier.classify(TARGET_SUBJECT, TARGET_BODY, "candidate@example.com")

    assert result.method == "setfit", (
        f"the candidate's own report was answered by {result.method!r} at "
        f"{result.confidence}. If that is 'rules', a pattern edit has put this "
        f"item back above the {RULES_SHORT_CIRCUIT} short circuit and the "
        f"learned layer can no longer correct it — which is #758."
    )
    assert setfit.calls == 1, "SetFit was never consulted"


@pytest.mark.asyncio
async def test_the_employers_invite_stays_owned_by_the_rules_layer() -> None:
    """The other direction, without which the test above is half a control.

    A cascade that stopped short-circuiting entirely would satisfy the first
    test and be a worse defect than the one it guards.
    """

    classifier, setfit = _classifier()
    result = await classifier.classify(INVITE_SUBJECT, INVITE_BODY, "recruiter@example.com")

    assert result.method == "rules", (
        f"the employer's imperative was answered by {result.method!r}; the "
        f"rules layer is supposed to own this one"
    )
    assert result.category is EmailCategory.ASSESSMENT
    assert setfit.calls == 0, (
        "SetFit ran on a message the rules layer should have short-circuited. "
        "`method == 'rules'` alone cannot see this: a layer that agreed and a "
        "layer that was never asked produce the same verdict."
    )


@pytest.mark.asyncio
async def test_restoring_the_redundant_branch_takes_the_item_back_from_setfit() -> None:
    """SHOWN TO FAIL, against the edit that actually caused #758.

    Re-adds the `exercise` branch #758 removed, which is what let one phrase
    match three ASSESSMENT patterns for a score of 9 — exactly the short
    circuit. Mutates `PATTERNS` itself, not a copy handed back by an accessor.
    """

    strong = PATTERNS[EmailCategory.ASSESSMENT].strong
    narrowed = "take.?home (assignment|project|task|round)"
    assert narrowed in strong, (
        "the pattern this control mutates is gone; it no longer reproduces "
        "#119 and this test proves nothing. Re-point it."
    )
    saved = list(strong)
    try:
        strong[strong.index(narrowed)] = "take.?home (assignment|project|exercise|task|round)"
        classifier, setfit = _classifier()
        result = await classifier.classify(
            TARGET_SUBJECT, TARGET_BODY, "candidate@example.com"
        )
    finally:
        strong[:] = saved

    assert result.method == "rules" and setfit.calls == 0, (
        "restoring the redundant branch should put this item back on the rules "
        f"short circuit; got method={result.method!r}, setfit calls={setfit.calls}"
    )
