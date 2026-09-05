"""``complete`` was unanchored, so a candidate's REPORT read as an employer's
INVITE. #820.

    complete.{0,30}(assessment|challenge|test)

``complete`` is a substring of ``completed``, so "I have completed the
assessment" fired the pattern that exists for "Please complete the assessment".
The tense carries the entire distinction between the two speakers and the rule
could not see it.

WHY THAT MATTERED MORE THAN ONE WRONG LABEL. With the phrase in the subject a
subject hit is doubled, so the report reached **9 points — confidence 0.90**,
which is ``hybrid.classify``'s earliest return. The learned layers never saw the
message and could not correct a verdict the rules layer had no evidence for.
That is #775's routing shape arriving through a second pattern.

THE FIX IS THE ONE ITS SIBLING ALREADY USES. #758 added the imperative twin
anchored — ``\\bcomplete\\b.{0,30}take.?home…`` — for exactly this reason, and
its docstring says so. This applies the same ``\\b`` to the older pattern.

WHAT THE PAIR BELOW IS FOR. A rule that suppressed "assessment" near the word
"completed" is one bad generalisation away from suppressing real invitations,
and an employer writes "complete" constantly. So the invite is asserted to KEEP
its score at both subject strengths, not merely to survive.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.hybrid import RULES_SHORT_CIRCUIT
from jobtracker.classifier.rules import PATTERNS, EmailCategory, RulesClassifier

#: The candidate reporting their own finished work. Nothing here invites anyone.
REPORT_BODY = "I have completed the assessment you sent and am waiting to hear back."

#: The employer's imperative, which this pattern exists for and must keep.
INVITE_BODY = "Please complete the assessment by Friday."

SENDER = "someone@example.test"


@pytest.fixture
def classifier() -> RulesClassifier:
    return RulesClassifier()


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param("Update", id="neutral-subject"),
        # The ordinary way a candidate writes this mail, and the one that used
        # to reach the short circuit.
        pytest.param("Completed the assessment", id="subject-names-it"),
    ],
)
def test_the_candidates_report_does_not_score_as_an_assessment(
    classifier: RulesClassifier, subject: str
) -> None:
    verdict = classifier.classify(subject, REPORT_BODY, SENDER)
    assert verdict.scores["assessment"] == 0, (
        f"the report scored {verdict.scores['assessment']} for assessment "
        f"({verdict.matched_patterns}); an unanchored `complete` matches inside "
        "`completed`"
    )
    assert verdict.confidence < RULES_SHORT_CIRCUIT, (
        f"answered {verdict.category.value} at {verdict.confidence}, which "
        "returns from hybrid.classify before the learned layers run"
    )


@pytest.mark.parametrize(
    "subject,expected_score",
    [
        pytest.param("Update", 3, id="neutral-subject"),
        # A subject hit is doubled, so this is the shape that legitimately owns
        # the short circuit — and must keep owning it.
        pytest.param("Assessment invitation", 9, id="subject-names-it"),
    ],
)
def test_the_employers_invite_keeps_the_score_the_pattern_exists_for(
    classifier: RulesClassifier, subject: str, expected_score: int
) -> None:
    verdict = classifier.classify(subject, INVITE_BODY, SENDER)
    assert verdict.category is EmailCategory.ASSESSMENT
    assert verdict.scores["assessment"] == expected_score, verdict.matched_patterns


def test_the_employers_invite_still_owns_the_short_circuit() -> None:
    """The other direction, stated separately because it is the cost side.

    Narrowing a pattern is only free if the case it was written for keeps its
    routing. Asserting the category alone would pass a change that dropped this
    message from 0.90 to 0.70 and handed it to a layer that has no examples of
    it.
    """

    verdict = RulesClassifier().classify(
        "Assessment invitation", INVITE_BODY, SENDER
    )
    assert verdict.confidence >= RULES_SHORT_CIRCUIT, verdict.matched_patterns


def test_removing_the_word_boundary_brings_the_report_back() -> None:
    """SHOWN TO FAIL. Mutates ``PATTERNS`` itself, not a copy.

    The ``strong`` accessor hands back a list; mutating the copy would leave the
    engine untouched and this test would pass for the wrong reason. Restored in
    ``finally`` so ordering cannot leak it into another module.
    """

    strong = PATTERNS[EmailCategory.ASSESSMENT].strong
    anchored = r"\bcomplete\b.{0,30}(assessment|challenge|test)"
    assert anchored in strong, "the pattern this control mutates is gone"

    saved = list(strong)
    try:
        strong[strong.index(anchored)] = "complete.{0,30}(assessment|challenge|test)"
        verdict = RulesClassifier().classify(
            "Completed the assessment", REPORT_BODY, SENDER
        )
    finally:
        strong[:] = saved

    # SIX, measured, not nine. The subject hit is what carries it: the invite
    # with a naming subject scores 9 and this scores 6, and I wrote 9 here first
    # by conflating the two. Six still clears the short circuit, which is the
    # property under test — the point is not the magnitude but that an
    # unanchored `complete` puts the READER's own message beyond correction.
    assert verdict.scores["assessment"] == 6, verdict.matched_patterns
    assert verdict.confidence >= RULES_SHORT_CIRCUIT, (
        "without the word boundary the candidate's report should reach the "
        f"short circuit; got {verdict.confidence}"
    )
    # And the anchor is back.
    assert RulesClassifier().classify(
        "Completed the assessment", REPORT_BODY, SENDER
    ).scores["assessment"] == 0
