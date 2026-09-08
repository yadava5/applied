"""THIS FILE'S WHOLE SUBJECT IS A DELETION — #928.

``applied.strong`` shipped ``be in touch (soon|shortly|if)`` and the third arm
could never fire. Every pattern is matched against
:func:`jobtracker.classifier.rules.asserted_text`, which masks from a
conditional marker to the end of its sentence, and ``if`` is the FIRST marker in
``_CONDITIONAL``. The token the alternation needed was removed before any
pattern saw the text. The arm is now gone and this module is the control for
its going.

HOW YOU PROVE A DELETION. You cannot assert on what is absent, so the claim is
made from the other side: **the two surviving arms still fire, unchanged**, and
the phrasing the deleted arm was written for still reaches nothing. If the
deletion had taken more than the dead arm with it, `soon` and `shortly` are
where it would show.

AND THE DELETION IS DELIBERATELY UNOBSERVABLE HERE. Put ``|if`` back and every
test below stays green — that is not a gap, it is the claim restated: the arm
changes nothing at the classifier boundary, in either direction. What this
module CAN see is the arm being reinstated somewhere that reads the UNMASKED
body, because ``test_a_conditional_promise_reaches_no_pattern_at_all`` pins the
matched list at empty. That is the change the mask exists to refuse and it is
the one worth catching.

WHY A CONDITIONAL PROMISE IS NOT A CONFIRMATION, since that is the judgement
the deletion encodes rather than a fact about regexes. "We will be in touch if
there is a fit" promises a message the sender may never send. It asserts
nothing about an application EXISTING, which is the only thing ``applied``'s
strong list is allowed to claim; ``asserted_text`` masking it is the CORRECT
behaviour and not an obstacle to route around.

ONE PHRASING DELIBERATELY NOT USED. "Thank you for applying. We will be in
touch if there is a fit." does reach ``applied`` — on
``thank(s| you) for applying``, a different pattern entirely. A fixture
carrying it would credit this arm with a match it never made, so the
conditional bodies below carry no other ``applied`` trigger at all and the
tests assert the matched list is EMPTY rather than merely lacking one entry.

Every body here is invented. No mailbox content, per ``docs/TEST_DATA_POLICY``.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import asserted_text, get_rules_classifier
from jobtracker.database.models import EmailCategory

CLASSIFIER = get_rules_classifier()

#: Not an ATS domain: ``ATS_DOMAINS`` adds +0.05 to a lifecycle verdict and
#: would put a bonus between these fixtures and the confidence they pin.
SENDER = "careers@cedarhollow.example"

#: Matches no ``applied`` subject pattern, so every point below is earned in the
#: body. Measured: the winning score is 3, which is one strong BODY match and
#: nothing else — a subject hit would be worth 6.
SUBJECT = "Your application"

#: The two arms that survive. One sentence of neutral courtesy ahead of each,
#: so the pattern is not the entire message.
SURVIVING_BODIES = {
    "soon": "Thanks for your note. We will be in touch soon.",
    "shortly": "Thanks for your note. We will be in touch shortly.",
}

#: The phrasing the deleted arm was written for, in two shapes: the marker
#: mid-sentence after real prose, and the marker in a bare sentence. Neither
#: carries any other ``applied`` trigger.
CONDITIONAL_BODIES = {
    "after prose": (
        "We review every application carefully and will be in touch if there "
        "is a fit."
    ),
    "bare sentence": "We will be in touch if there is a fit.",
}


@pytest.mark.parametrize("arm", sorted(SURVIVING_BODIES))
def test_a_surviving_arm_still_scores_applied_on_this_pattern(arm: str) -> None:
    """``soon`` and ``shortly`` are where a deletion that took too much shows.

    THE PATTERN IS NAMED BY ``len == 1`` AND NOT BY ITS FULL TEXT, and that is
    on purpose — do not "tighten" this to an equality. The alternation's text
    is exactly what #928 changed, so pinning it would make this module red when
    the dead arm is restored, and "restoring the dead arm changes nothing" is
    the claim the module is here to support. What must be pinned is that the
    verdict comes from THIS rule and no other, which is what a single match of
    a strong ``be in touch`` pattern says.

    The narrowing that matters is caught anyway: delete the ``soon`` arm and
    this fixture matches nothing at all, landing on ``other`` 0.50 with an
    empty list rather than on a differently-spelled pattern.
    """

    result = CLASSIFIER.classify(SUBJECT, SURVIVING_BODIES[arm], SENDER)

    assert result.category is EmailCategory.APPLIED
    assert result.confidence == 0.70
    assert len(result.matched_patterns) == 1, result.matched_patterns
    tier, _, pattern = result.matched_patterns[0].partition(" ")
    assert tier == "[STRONG]"
    assert pattern.startswith("be in touch ")


@pytest.mark.parametrize("shape", sorted(CONDITIONAL_BODIES))
def test_a_conditional_promise_reaches_no_pattern_at_all(shape: str) -> None:
    """The conditional phrasing scores nothing, and it scored nothing before.

    EQUALITY ON THE LIST, not "``applied`` is absent" and not a substring of
    it. These bodies carry no other trigger, so ANY match here is a rule
    reading text the sender did not assert, whatever category it argues for.
    This is the assertion that would red if the deleted arm were reinstated
    against the unmasked body.
    """

    result = CLASSIFIER.classify(SUBJECT, CONDITIONAL_BODIES[shape], SENDER)

    assert result.matched_patterns == []
    assert result.category is EmailCategory.OTHER
    assert result.confidence == 0.50


def test_the_mask_removes_the_token_the_deleted_arm_needed() -> None:
    """The mechanism, pinned apart from the verdict.

    The classifier-level tests say the conditional phrasing scores nothing.
    This says WHY, and it is a different claim: by the time a pattern is
    searched, the word ``if`` and everything after it is not in the string. A
    later change could make the phrasing score nothing for some other reason
    and leave the two tests above green while this one reds, which is the
    separation worth having.
    """

    assert asserted_text("We will be in touch if there is a fit.") == (
        "We will be in touch "
    )
    assert asserted_text(CONDITIONAL_BODIES["after prose"]) == (
        "We review every application carefully and will be in touch "
    )


@pytest.mark.parametrize("arm", sorted(SURVIVING_BODIES))
def test_the_mask_leaves_a_surviving_arm_untouched(arm: str) -> None:
    """The control on the control: the mask is not eating these two.

    Without it, ``test_the_mask_removes_the_token_the_deleted_arm_needed``
    could be satisfied by a mask that truncates everything, and the pair would
    still read as a mechanism proved.
    """

    body = SURVIVING_BODIES[arm]
    assert asserted_text(body) == body
