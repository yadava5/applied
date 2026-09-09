"""The #768 family grades attribution, and this file keeps it able to (#768).

A family of third-party mail alone goes green for a rule that suppresses the
whole lifecycle vocabulary near the word "referral". A family whose controls
carry no referral token goes green for that rule too, because nothing it holds
can fire against it. Both failures look exactly like coverage, so the
properties that make this family a measurement rather than a decoration are
asserted here instead of being described in a comment.

WHAT THE FAMILY CANNOT DO, stated because the next person will otherwise
assume it can: every wording in it is AUTHORED. ``corpus_independent/observed.py``
holds the transcribed-from-real-mail half of the corpus and not one of its
wordings mentions a referral or a reference. So this family proves the
classifier cannot see attribution, and it does NOT establish how often real
mail asks it to. See :mod:`tests.corpus_independent.generate`'s family
docstring and ``docs/CLASSIFIER_RULES_GOVERNANCE.md`` on invented vocabulary.
"""

import re

import pytest

from jobtracker.cloud import pipeline
from tests.corpus_independent.generate import (
    _REFERRAL_BEARING_OWN,
    _SOMEONE_ELSE_PAIRS,
    generate,
)
from tests.corpus_independent.harness import classify_all

FAMILY = "someone-elses-outcome"

#: Measured on main @ 2b49a2e7, and a FLOOR rather than an equality: the point
#: is that the third-party arm is reachable and wrong, not that it is wrong
#: exactly this often. An equality here would go red on any unrelated wording
#: change and get relaxed; a floor goes red only when the arm stops measuring.
#:
#: THESE TWO ARE DEFECT PINS, NOT INVARIANTS, and the difference decides what
#: to do when they go red. They record that the defect is STILL PRESENT. A
#: genuine fix is EXPECTED to turn them red, and the right response then is to
#: re-record them downward and say so — not to weaken them.
#: :func:`test_no_reader_owned_outcome_is_lost` is the opposite kind: it is an
#: invariant, it is zero, and a fix that reds it is a bad fix.
#:
#: Both kinds were exercised against a deliberately naive fix — suppress every
#: lifecycle verdict wherever "referr" appears. It turned the two pins red, as
#: a real fix would, AND it turned the invariant red with 40 of 80 genuine
#: reader outcomes dropping to ``other`` at 0.50. That is the whole reason the
#: pins are safe to state: on their own they would bless a fix that bought
#: third-party accuracy by deleting real outcomes.
THIRD_PARTY_WRONG_FLOOR = 40
AUTO_FILED_WRONG_FLOOR = 30

#: What the family does to the BOARD, measured against a pristine-tree run of
#: the same probe on main @ 2b49a2e7 rather than against the recorded table.
#:
#: ``noise_on_card`` 0 -> 30 and ``wrong_status`` 0 -> 30 — the SAME 30, the
#: auto-filed third-party messages, each landing on the reader's own live card
#: and settling it. ``cards`` 10058 -> 10178 (+120, one per group);
#: ``UPDATE-HELD`` 685 -> 712 (+27, the reader arms' mail that is legitimately
#: held rather than filed). ``splits``, ``merges``, ``role_wrong``,
#: ``company_wrong`` and ``wrong_review`` do not move at all, and ``LOST`` (60)
#: and ``ROLE-MISSING`` (63) are unchanged — both are PRE-EXISTING and were
#: read off the baseline run rather than assumed, which is the only reason
#: they can be reported as not-mine.


@pytest.fixture(scope="module")
def family():
    cases = generate()
    verdicts = classify_all(cases)
    return [v for v in verdicts if v.case.family == FAMILY]


def test_the_pairs_differ_in_exactly_one_slot() -> None:
    """The case and its twin are one noun phrase apart, and nothing else.

    THE WHOLE ATTRIBUTION CLAIM RESTS ON THIS. If the subject or any other
    word moved with ``{obj}``, a difference in verdict would be evidence about
    two variables and about neither of them. Asserted by construction rather
    than by eye: substituting the reader's object into the case body must
    yield the twin body character for character.
    """

    for subject, body, third, reader, _category in _SOMEONE_ELSE_PAIRS:
        case_body = body.format(obj=third, r="R", d="D")
        twin_body = body.format(obj=reader, r="R", d="D")
        assert case_body != twin_body, f"the pair is not a pair: {subject!r}"
        assert case_body.replace(third, reader, 1) == twin_body, (
            f"more than the {{obj}} slot moves between the arms of {subject!r}"
        )


def test_every_control_that_must_bite_carries_the_token() -> None:
    """Arm three says "referral" and is still the reader's own outcome.

    A rule keyed on ``referr*`` cannot move a message that does not contain
    the token, so the twins in :data:`_SOMEONE_ELSE_PAIRS` cannot fail against
    one however badly it is written. These are the ones that can.
    """

    token = re.compile(r"referr", re.IGNORECASE)
    for subject, body, _category in _REFERRAL_BEARING_OWN:
        assert token.search(body), (
            f"{subject!r} is in the referral-bearing arm and says no such thing, "
            "so it cannot fail against a referral-keyed rule and is decoration"
        )


def test_the_third_party_arm_is_reachable_and_wrong(family) -> None:
    """The measurement returns positive, which is the thing to check first.

    A family whose defect arm scores CORRECT pins nothing. That is not
    hypothetical here: ``harness.classify_all`` buckets an ``expected="other"``
    case as correct whenever ``confidence < REVIEW_FLOOR``, so a third-party
    wording that fires nothing — or fires weakly — is green no matter how blind
    the classifier is. One candidate wording was discarded from the family for
    exactly that, and the three fixtures this issue was originally built on
    score 0.60 and would all have been green.
    """

    third_party = [v for v in family if v.case.identity is None]
    wrong = [v for v in third_party if v.bucket == "wrong"]
    assert len(wrong) >= THIRD_PARTY_WRONG_FLOOR, (
        f"only {len(wrong)} of {len(third_party)} third-party messages are graded "
        "wrong; the arm has stopped measuring attribution"
    )
    assert all(v.confidence >= pipeline.REVIEW_FLOOR for v in wrong), (
        "a wrong verdict under the review floor buckets CORRECT and pins nothing"
    )


def test_the_silence_is_what_hurts(family) -> None:
    """Wrong is bad; wrong ABOVE the auto-file gate is the reportable harm.

    These are the verdicts filed onto a card with nobody asked. Replayed
    through the real additive sync they settle the reader's own live
    application: the card reads ``rejected`` and the review queue is empty.
    """

    auto_filed_wrong = [
        v for v in family if v.case.identity is None and v.bucket == "wrong" and v.auto_filed
    ]
    assert len(auto_filed_wrong) >= AUTO_FILED_WRONG_FLOOR, (
        f"{len(auto_filed_wrong)} third-party verdicts sit above "
        f"{pipeline.AUTO_FILE_GATE}; the family no longer measures the silent half"
    )


def test_no_reader_owned_outcome_is_lost(family) -> None:
    """The direction a fix breaks. ZERO, and it must stay zero.

    Both reader arms: the one-slot twins and the referral-bearing controls.
    Any rule that buys third-party accuracy by suppressing the lifecycle
    vocabulary near "referral" turns this red, which is the only reason the
    third-party floors above are safe to state.
    """

    reader = [
        v
        for v in family
        if v.case.identity is not None and v.case.expected_category != "applied"
    ]
    lost = [v for v in reader if v.bucket != "correct"]
    assert not lost, (
        f"{len(lost)} of {len(reader)} genuine reader outcomes stopped scoring their "
        f"category: {[(v.case.subject, v.category, v.confidence) for v in lost[:4]]}"
    )
