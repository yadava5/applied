"""The auto-file gate is a boundary, and 260 cards sit exactly on it (#814).

#814 asks for this while noting the shape: the corpus's 260 rescinded-offer
cards all file on the strength of one ``<`` comparison against
``AUTO_FILE_GATE``. Nothing tested the boundary itself.

One correction to that framing, established by writing the assertion out
exactly: the family does not sit **on** the gate. It sits one ULP ABOVE it, at
``0.8500000000000001`` — `0.80 + 0.05` in binary floating point. #814's figure
was read at four decimal places and the artifact hides there, and the
difference matters because a value above a ``>=`` boundary has slack on the
dangerous side where a value on it has none. See
``test_the_rescinded_offer_family_sits_one_ulp_above_the_boundary``. ``test_confidence_gate_lockstep.py`` pins that every COPY of the gate
holds the canonical value, which is a different claim: it would stay green if
the comparison flipped to ``<=`` and 260 cards stopped being filed.

WHY 0.85 IS WRITTEN OUT HERE INSTEAD OF IMPORTED. Every expectation below is a
literal. Reading the bound from ``pipeline.AUTO_FILE_GATE`` would compare the
constant to itself: the assertion passes for 0.85, for 0.86, for 0.0, and the
only thing it can still catch is a copy drifting — which is already covered.
A bound has to come from something that CONSTRAINS it, and here that is the
measured behaviour of the corpus family plus this file's own statement of what
the product promises. If the gate is deliberately moved, this file is supposed
to go red and be re-read; that is the point of it, not a maintenance cost.

WHAT MAKES THE BOUNDARY FRAGILE RATHER THAN MERELY EXACT. 0.85 is not a clamp
and not a coincidence. Measured: the same offer wording scores 0.80 from a
company domain and from no sender at all, and 0.85 from an ATS relay. The
family clears the gate only because a +0.05 sender bonus lands it precisely on
the value the comparison tests. Any epsilon, float32 pass, JSON round trip or
reordering of the bonus flips 260 of 260 silently and in one direction.
"""

import math

import pytest

from jobtracker.classifier.rules import ATS_DOMAINS, RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.cloud.pipeline import PipelineItem

#: The gate, written out. See the module docstring for why this is not
#: ``pipeline.AUTO_FILE_GATE``.
GATE = 0.85

#: The base an offer scores from its own words, with no sender bonus.
BASE = 0.80

#: What an ATS relay adds. ``GATE - BASE``, stated because it is the whole
#: reason the family is on the boundary rather than under it.
ATS_BONUS = 0.05

#: An ATS relay address, DERIVED rather than written out. Two reasons, and the
#: second is the better one. It keeps a routable domain out of the tree as a
#: published address (``docs/TEST_DATA_POLICY.md``), and it sources the sender
#: from the very list ``is_ats_sender`` consults — so if a domain is ever
#: dropped from ``ATS_DOMAINS``, this fixture stops claiming a bonus that the
#: product would no longer grant, instead of silently testing a dead branch.
ATS_SENDER = f"no-reply@{ATS_DOMAINS[0]}"

#: The counterpart: a company domain in a reserved TLD, which gets no bonus.
DIRECT_SENDER = "talent@northwind.example"

OFFER_SUBJECT = "Your offer from Northwind Systems"
OFFER_BODY = (
    "Hi Ayush, We are delighted to extend you an offer to join Northwind Systems "
    "as a Backend Engineer. We are thrilled at the prospect of you joining the team."
)


def _item(confidence: float) -> PipelineItem:
    """An offer from an ATS relay, at the confidence given and nothing else varied."""

    return PipelineItem(
        message_id="m-814",
        category="offer",
        sender_email=ATS_SENDER,
        subject=OFFER_SUBJECT,
        sender_name="Northwind Systems Talent",
        confidence=confidence,
    )


def test_the_constant_still_holds_the_value_this_file_is_written_against() -> None:
    """The one place the constant IS read, and it is a tripwire, not an expectation.

    Every other assertion here is a literal on purpose. This one exists so that
    a deliberate move of the gate fails HERE, with this file named, rather than
    silently re-pointing every literal below at a value nobody re-read.
    """

    assert pipeline.AUTO_FILE_GATE == GATE, (
        f"the auto-file gate moved to {pipeline.AUTO_FILE_GATE}. Every expectation "
        f"in this file is written against {GATE} and describes the old product "
        "until it is re-measured — #814's 260 cards sit exactly on this value."
    )


def test_exactly_the_gate_files() -> None:
    """At 0.85 the row is filed. This is the half a `<=` typo would break.

    `_qualifies_for_hard_row` refuses on `confidence < AUTO_FILE_GATE`, so the
    gate is inclusive from below. The corpus's whole rescinded-offer family
    lands on this exact value, which is why the case sitting ON the threshold
    is the one that matters rather than a comfortable 0.95.
    """

    assert pipeline._qualifies_for_hard_row(_item(GATE)) is not None, (
        "a lifecycle verdict at exactly the gate was refused a hard row. The "
        "gate is inclusive from below; 260 corpus cards sit on this value and "
        "all of them stop filing if this flips."
    )


def test_just_under_the_gate_queues() -> None:
    """The other direction, at the closest float below rather than a round number.

    0.84 would pass against a gate of 0.845 and prove nothing about the
    boundary. `math.nextafter` gives the largest float strictly less than the
    gate, so this can only pass if the comparison really is at 0.85.
    """

    just_under = math.nextafter(GATE, 0.0)
    assert just_under < GATE
    assert pipeline._qualifies_for_hard_row(_item(just_under)) is None, (
        f"a verdict at {just_under!r}, strictly below the gate, was allowed to "
        "assert a hard status. That band is supposed to reach the review queue."
    )


def test_the_gate_is_reached_by_a_sender_bonus_not_by_the_words() -> None:
    """Why the boundary is fragile: the family clears it by exactly the bonus.

    The same offer wording, three senders. If the base ever rises to the gate on
    its own, or the bonus changes size, the family stops being a boundary case
    and this file's premise is gone — so both halves are asserted, not just the
    total.
    """

    rules = RulesClassifier()
    relayed = rules.classify(OFFER_SUBJECT, OFFER_BODY, ATS_SENDER)
    direct = rules.classify(OFFER_SUBJECT, OFFER_BODY, DIRECT_SENDER)
    unsent = rules.classify(OFFER_SUBJECT, OFFER_BODY, None)

    assert direct.confidence == pytest.approx(BASE), (
        f"the offer's own words now score {direct.confidence} from a company "
        f"domain, not {BASE}. The gate is no longer reached by the sender bonus."
    )
    assert unsent.confidence == pytest.approx(BASE), (
        "measured against a None sender as well, because a sender bonus in the "
        "fixture is a floor under the measurement and hides the thing measured"
    )
    assert relayed.confidence == pytest.approx(GATE), (
        f"the relayed offer scores {relayed.confidence}, not {GATE}"
    )
    assert relayed.confidence - direct.confidence == pytest.approx(ATS_BONUS), (
        "the ATS bonus is what puts this family exactly on the gate; if its size "
        "changed, 260 cards changed side with it"
    )


def test_the_rescinded_offer_family_sits_one_ulp_above_the_boundary() -> None:
    """Why the pair above is worth having — and a correction to #814's premise.

    #814 says "every one of the 260 offers files at exactly 0.85". Measured, it
    does not: every one scores **0.8500000000000001**, which is
    ``math.nextafter(0.85, 1.0)`` — one unit in the last place ABOVE the gate.
    The issue's own figure was read at four decimal places, which is where the
    artifact hides. It is `0.80 + 0.05` in binary floating point and nothing
    more mysterious than that.

    THE DISTINCTION IS NOT PEDANTRY, because it changes the risk the issue
    states. #814 warns that "any epsilon, float32 pass, JSON round-trip or
    refactor flips 260 of 260 silently". Two of those three were measured and do
    NOT flip it: a JSON round trip returns the identical double, and narrowing
    to float32 and back still compares at or above the gate. A value one ULP
    ABOVE a `>=` boundary has a whole ULP of slack on the dangerous side; a
    value exactly ON it has none.

    WHAT WOULD STILL MOVE ALL 260, and is what this file guards: the comparison
    becoming `<=` (mutated, reds `test_exactly_the_gate_files`), the gate moving
    (mutated, reds the tripwire), or the base or the ATS bonus changing size
    (reds `test_the_gate_is_reached_by_a_sender_bonus_not_by_the_words`).

    IT ALSO PINS AN ABSENCE. The queue band ``[0.70, GATE)`` is EMPTY across the
    family's 520 messages — 260 at the gate-plus-one-ULP and 260 at 0.50, with
    nothing between. No case in the corpus exercises the mid-confidence path for
    this shape, so a change affecting only held offers would be invisible here.
    That is a limit of the corpus, recorded rather than discovered later.
    """

    from tests.corpus_independent.generate import generate
    from tests.corpus_independent.harness import classify_all

    family = [
        v for v in classify_all(generate()) if v.case.family == "rescinded-offer"
    ]
    offers = [v for v in family if v.case.expected_category == "offer"]
    assert len(offers) == 260, f"the family's offer arm is {len(offers)}, not 260"

    one_ulp_above = math.nextafter(GATE, 1.0)
    stray = sorted({v.confidence for v in offers if v.confidence != one_ulp_above})
    assert not stray, (
        f"offers now score {stray} rather than {one_ulp_above!r}. The family has "
        "moved off the boundary, so the directional pair above no longer "
        "describes anything the corpus actually does."
    )
    # Stated separately from the equality, because THIS is the property that
    # decides the 260 cards and the equality above is only how it is reached.
    assert all(v.confidence >= GATE for v in offers)

    banded = [v for v in family if 0.70 <= v.confidence < GATE]
    assert not banded, (
        f"{len(banded)} of {len(family)} messages now sit in the queue band. That "
        "is NOT a regression — it is the gap this test records being filled, and "
        "the docstring above should be re-read and this assertion re-recorded."
    )
