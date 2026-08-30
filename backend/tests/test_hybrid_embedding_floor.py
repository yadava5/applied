"""Layer 2's floor is the EMBEDDING classifier's threshold, not the auto-file gate.

``hybrid.classify`` accepts an embedding verdict when its similarity clears a
floor. That floor was hand-written as a bare ``0.85`` — the same digits as
``CONFIDENCE_AUTO`` twelve lines above it and as
``EmbeddingsClassifier.SIMILARITY_THRESHOLD``, and it is the LATTER quantity:
``EmbeddingsClassifier.classify`` returns ``find_most_similar(...,
threshold=self.SIMILARITY_THRESHOLD)`` unmodified, and ``find_most_similar``
answers ``None`` below its threshold. So while the two numbers agreed, the
comparison in ``hybrid`` was tautologically true and the literal did nothing —
right up until somebody lowered ``SIMILARITY_THRESHOLD``, at which point a stale
0.85 in a different module would have silently overridden it.

It must NOT be bound to ``CONFIDENCE_AUTO``. Three lines below the comparison,
the accepted verdict is returned with ``needs_review=emb_confidence <
CONFIDENCE_AUTO``. That line only means something if verdicts BELOW the auto-file
gate are returnable and get flagged; gating on the auto-file gate would make it
dead by construction and would drop every embedding verdict in the review band
instead of queueing it.

NOTHING IN THE SUITE COULD TELL THE DIFFERENCE. Mutating that literal from 0.85
to 0.95 left 115 tests green: no test anywhere distinguished hybrid's behaviour
in [0.85, 0.95). This module is that missing measurement, and it is
DIRECTIONAL — raising the floor, lowering it, or rebinding it to the wrong
constant each reds a different case here:

===========================  ===========  ===========  ===========  ===========
case                         as shipped   bare 0.85    0.95         CONF_AUTO
===========================  ===========  ===========  ===========  ===========
0.86, threshold 0.85         embeddings   embeddings   fallback     embeddings
0.84, threshold 0.85         fallback     fallback     fallback     fallback
0.82, threshold 0.80         embeddings   fallback     fallback     fallback
===========================  ===========  ===========  ===========  ===========

The third row is the one that catches a rebinding to ``CONFIDENCE_AUTO``: while
the two constants hold the same value, 0.86 and 0.84 answer identically whichever
one is named, so a pair alone would leave that mutation with zero reds. It is
also the direct statement of what the change bought — LOWERING THE EMBEDDING
THRESHOLD NOW TAKES EFFECT.

Every case asserts the fake was actually CONSULTED. Without that, "not
embeddings" is indistinguishable from "layer 2 was never reached", and the
negative half of the pair would prove nothing. ``classify`` has three earlier
exits that would do exactly that: the content guard at the top, the ``>= 0.90``
rules return, and the ``_cloud_rules_only`` short-circuit.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.hybrid import HybridClassifier
from jobtracker.database.models import EmailCategory

# Rules must answer BELOW 0.90 or ``classify`` returns at the rules layer and
# layer 2 is never reached; and the text must carry lifecycle content or
# ``allow_semantic_override`` is False for a rules verdict of OTHER. Measured,
# not assumed — ``test_the_fixture_reaches_layer_two`` pins both.
#
# "schedule an interview" is deliberately AVOIDED: it is a ``[NEGATIVE]``
# pattern in rules.py and scores 0.90, which exits early. So are
# "unsubscribe"/"sign-in"/"newsletter", which the content guard forces to OTHER
# before any layer runs.
SUBJECT = "Following up"
BODY = "Our team enjoyed reading about you. An interview slot is being arranged."
SENDER = "people@acme.example"


class _FakeEmbeddings:
    """The smallest object ``classify``'s layer 2 will talk to.

    Injected through the ``_embeddings`` SETTER (hybrid.py), which exists for
    exactly this. Injecting rather than monkeypatching also means the real
    ``embeddings`` module — and its numpy / sentence-transformers import — is
    never loaded by this file.
    """

    def __init__(
        self,
        verdict: tuple[EmailCategory, float] | None,
        *,
        threshold: float = 0.85,
    ) -> None:
        self.SIMILARITY_THRESHOLD = threshold
        self._verdict = verdict
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def has_known_examples(self) -> bool:
        return True

    async def classify(self, subject: str, body: str):
        self.calls += 1
        return self._verdict


class _FakeSetFit:
    """Layer 3, wired shut.

    Not optional: without it the 0.84 case falls through to layer 3, reads the
    real ``_setfit`` property and lazy-imports setfit_model. Raising in
    ``classify`` also makes it loud if the availability check ever stops being
    honoured.
    """

    def is_available(self) -> bool:
        return False

    def classify(self, subject: str, body: str):  # pragma: no cover - never called
        raise AssertionError("layer 3 ran; this fixture is meant to stop at layer 2")


def _classifier(embeddings: _FakeEmbeddings) -> HybridClassifier:
    classifier = HybridClassifier()
    classifier._embeddings = embeddings
    classifier._setfit = _FakeSetFit()
    # The cloud short-circuit returns before layer 2 exists. Default deployment
    # is "desktop", so this is an assertion about the fixture rather than a
    # setting we change — if it ever flips, every case below would pass by
    # never running the code under test.
    assert not classifier._cloud_rules_only
    return classifier


async def test_the_fixture_reaches_layer_two() -> None:
    """Positive control for the two cases below.

    They assert on ``result.method``, and a fixture that exits at the rules
    layer or the content guard would give a stable, wrong answer for both. This
    pins the one thing that makes them meaningful: the embeddings layer is
    consulted at all.
    """

    embeddings = _FakeEmbeddings((EmailCategory.INTERVIEW, 0.86))
    classifier = _classifier(embeddings)

    await classifier.classify(SUBJECT, BODY, SENDER)

    assert embeddings.calls == 1, (
        "layer 2 was never reached — classify() exited at the content guard, the "
        "rules layer, or the cloud short-circuit. Every assertion in this module "
        "is vacuous until this passes."
    )


async def test_a_verdict_at_the_floor_is_accepted() -> None:
    """0.86 against a 0.85 threshold: the embedding verdict is what is returned."""

    embeddings = _FakeEmbeddings((EmailCategory.INTERVIEW, 0.86))
    classifier = _classifier(embeddings)

    result = await classifier.classify(SUBJECT, BODY, SENDER)

    assert embeddings.calls == 1
    assert result.method == "embeddings", (
        f"a 0.86 similarity against a 0.85 threshold was refused (method="
        f"{result.method!r}). The floor in hybrid.classify has been raised above "
        f"the embedding classifier's own SIMILARITY_THRESHOLD."
    )
    assert result.category == EmailCategory.INTERVIEW


async def test_a_verdict_below_the_floor_is_not_accepted() -> None:
    """0.84 against a 0.85 threshold: layer 2 ran, and its answer was refused.

    In production ``EmbeddingsClassifier.classify`` would have returned ``None``
    here rather than a sub-threshold tuple — that is precisely why the floor was
    tautological. The fake returns one anyway so the comparison in ``hybrid`` is
    the thing under test rather than the thing being assumed.
    """

    embeddings = _FakeEmbeddings((EmailCategory.INTERVIEW, 0.84))
    classifier = _classifier(embeddings)

    result = await classifier.classify(SUBJECT, BODY, SENDER)

    assert embeddings.calls == 1, (
        "the verdict was refused because layer 2 never ran, not because 0.84 is "
        "below the floor. That is not the same test."
    )
    assert result.method != "embeddings", (
        "a 0.84 similarity was accepted against a 0.85 threshold. The floor in "
        "hybrid.classify has been lowered, removed, or is reading a constant "
        "that is not the embedding classifier's threshold."
    )


async def test_lowering_the_classifiers_threshold_takes_effect() -> None:
    """The whole point: the floor tracks ``SIMILARITY_THRESHOLD``, not a literal.

    0.82 clears a threshold of 0.80 and is accepted. Against any constant that
    is not read off the embeddings instance — a hand-written ``0.85``, or
    ``CONFIDENCE_AUTO``, which happens to hold the same value — the same verdict
    is refused. This is the only case here that can tell those two apart.
    """

    embeddings = _FakeEmbeddings((EmailCategory.INTERVIEW, 0.82), threshold=0.80)
    classifier = _classifier(embeddings)

    result = await classifier.classify(SUBJECT, BODY, SENDER)

    assert embeddings.calls == 1
    assert result.method == "embeddings", (
        f"the embeddings classifier lowered its own SIMILARITY_THRESHOLD to 0.80 "
        f"and hybrid.classify ignored it (method={result.method!r}). The floor is "
        f"a constant from somewhere else again — check that it reads "
        f"self._embeddings.SIMILARITY_THRESHOLD and NOT CONFIDENCE_AUTO, which "
        f"would also make the needs_review flag three lines below it dead."
    )


@pytest.mark.parametrize(
    ("confidence", "threshold"),
    [(0.86, 0.85), (0.84, 0.85), (0.82, 0.80)],
)
async def test_no_case_here_touches_the_real_embeddings_module(
    confidence: float, threshold: float
) -> None:
    """The injection must not defeat the lazy-import rule it relies on.

    ``hybrid`` keeps ``embeddings`` and ``setfit_model`` out of the cloud import
    graph by importing them inside ``_load_embeddings`` / ``_load_setfit``. The
    change under test reads ``self._embeddings.SIMILARITY_THRESHOLD``, which is
    safe because ``is_available()`` above it already resolved the property — but
    only if the instance is the injected one. If a case here ever triggered the
    real import, it would be paying for torch to answer a question about a float.
    """

    import sys

    before = "jobtracker.classifier.embeddings" in sys.modules

    embeddings = _FakeEmbeddings(
        (EmailCategory.INTERVIEW, confidence), threshold=threshold
    )
    await _classifier(embeddings).classify(SUBJECT, BODY, SENDER)

    if not before:
        assert "jobtracker.classifier.embeddings" not in sys.modules, (
            "the real embeddings module was imported; the fake was not used"
        )
