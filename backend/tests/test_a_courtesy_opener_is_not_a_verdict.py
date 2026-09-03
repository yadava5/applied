"""Issue #658 — a rejection that opens by thanking you is still a rejection.

The defect
----------
``EmailCategory.REJECTION.negative`` carried two of ``EmailCategory.APPLIED``'s
own positives::

    thank you for applying
    application.{0,20}received

The second is ``APPLIED.strong[0]`` verbatim. Both are what job mail of EVERY
stage opens with, so the one category whose verdict always arrives under a
courtesy line paid -5 for the courtesy.

The arithmetic, on the standard ATS rejection "Thank you for applying for the
<Role> role at <Company>. We have decided not to move forward with your
application."::

    rejection   +3  not to (move|proceed|go) forward
                +3  not to (move|proceed|go) forward.{0,30}(application|candidacy)
                -5  thank you for applying              <- the courtesy opener
                ---
                 1

    applied     +3  thank(s| you) for applying
                ---
                 3

**Two STRONG matches on the verdict sentence lost to one on the greeting.**

Why the word "careful" decided it
---------------------------------
``after careful (consideration|review).{0,30}(not|decided|unfortunately)`` is
the only pattern that could pay the -5 back, so the verdict turned on a single
adjective::

    After careful consideration, we have decided not to…   rejection
    After thoughtful consideration, we have decided not to…  APPLIED
    After consideration, we have decided not to…             APPLIED
    We have decided not to move forward with your application.  APPLIED

Adding ``thoughtful`` beside ``careful`` would have turned this table green and
left the defect entirely intact for "After much consideration", "Following
consideration" and the bare verdict. That is why the fix is the deletion and
not an adjective, and it is why :func:`test_the_bare_verdict_needs_no_adjective`
below is the test that matters: the bare form names no adjective at all, so it
can only pass if the courtesy stopped being counted as evidence against the
verdict.

What this file would fail to catch if it only tested the table
--------------------------------------------------------------
Deleting a negative can only RAISE ``rejection``'s score, so rejection recall
cannot drop and a one-directional test would be green by construction. The
reachable cost is the other direction — an acknowledgement becoming a rejection
— and #451's tie-break sharpens it, because at equal score ``rejection`` (a
REPORT) now beats ``applied`` (an ASSERTION). So the acknowledgement controls
below are half the point of the file, not padding.

Why this file rather than the evaluation corpus
-----------------------------------------------
``data/evaluation/classifier_eval_v3.jsonl`` cannot see this defect. Measured
on the fix commit's parent: the rules gate scores macro F1 0.9896 both before
and after, every one of the eight per-class F1s identical.

The reason is structural rather than bad luck. Seven of the 96 rows carry
``thank(s| you) for applying`` or ``application.{0,20}received``, and **all
seven are labelled ``applied``**; none of the twelve ``rejection`` rows carries
either. So the set encodes the courtesy opener as evidence FOR ``applied`` and
contains no counter-example — the shape that would have caught this cannot
appear in it. A change no gate can see needs a test that can, and a 96-row set
blind to the product's worst failure mode is itself worth an issue.

The exposure is the auto-file, not the queue
--------------------------------------------
The issue reports 0.75, which is under ``pipeline.AUTO_FILE_GATE`` and so
merely a wrong label in the review queue. Add the OTHER standard opener and it
is worse: "We have received your application." gives ``applied`` its own +3, so
the rejection loses 6-to-1 at confidence 0.95 and files itself as an
acknowledgement with no human ever seeing it.
:func:`test_the_variant_that_auto_filed` pins that case at the gate.

Employer, role and sender are invented. The real message is not reproduced
here, per #593.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import PATTERNS, RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

# The invented analogue from the issue. An ATS relay, because that is where
# these arrive and because the +0.05 sender bonus is part of the arithmetic
# that carried the wrong verdict over the gate.
SENDER = "no-reply@ashbyhq.com"
SUBJECT = "Brackenhill Application Update"
OPENER = "Thank you for applying for the Member of Technical Staff role at Brackenhill."


def classify(body: str, subject: str = SUBJECT):
    return CLASSIFIER.classify(subject=subject, body=body, sender_email=SENDER)


# ---------------------------------------------------------------------------
# The verdict wins, whatever the greeting says
# ---------------------------------------------------------------------------


def test_the_bare_verdict_needs_no_adjective() -> None:
    """The headline case: no "consideration" clause anywhere in the message.

    This is the assertion an adjective could not have bought. The body's only
    rejection evidence is the infinitive twins on "not to move forward"; if the
    courtesy opener is still scored against the category, rejection is 1 and
    ``applied`` takes it at 3.
    """
    result = classify(f"{OPENER} We have decided not to move forward with your application.")

    assert result.category == EmailCategory.REJECTION
    assert result.confidence >= pipeline.AUTO_FILE_GATE


@pytest.mark.parametrize(
    "second_sentence",
    [
        # The issue's own four rows, minus the one that already worked.
        "After consideration, we have decided not to move forward with your application.",
        "After thoughtful consideration, we have decided not to move forward with your application.",
        "We have decided not to move forward with your application.",
        # The wordings an adjective list would still have missed. Named in the
        # issue as the reason `careful`+`thoughtful` is not a fix.
        "After much consideration, we have decided not to move forward with your application.",
        "Following consideration, we have decided not to move forward with your application.",
        # The one that always worked, kept as the control that the pattern it
        # depends on is untouched by this change.
        "After careful consideration, we have decided not to move forward with your application.",
    ],
)
def test_the_verdict_outranks_the_courtesy_whatever_the_wording(second_sentence: str) -> None:
    """No spelling of the decision sentence may be decided by its preamble.

    Parametrized over the adjective rather than asserted once, because the
    defect's signature was that exactly one member of this list passed. A test
    pinning only the bare form would go green on a fix that special-cased it.
    """
    result = classify(f"{OPENER} {second_sentence}")

    assert result.category == EmailCategory.REJECTION
    assert result.confidence >= pipeline.AUTO_FILE_GATE


def test_the_variant_that_auto_filed_is_no_longer_an_acknowledgement() -> None:
    """Both standard openers at once — the case that never reached a human.

    Before: ``applied`` 6 against ``rejection`` 1, 0.90 plus the ATS bonus =
    0.95, over ``AUTO_FILE_GATE``. The board gained an open application for a
    job that had already said no and nothing was queued.

    After: the verdict is right and the confidence is honest rather than high.
    ``applied`` still earns a legitimate 6 here — ``thank(s| you) for
    applying`` +3 and ``we (have |'ve )received your application`` +3 are both
    real acknowledgement patterns — so the two categories TIE at 6. #451's
    tie-break awards it to ``rejection`` (the report entails the assertion),
    but a tie is a zero margin, so confidence lands at 0.60 +0.05 = 0.65.

    CHARACTERISED, NOT ASSERTED AS GOOD. 0.65 is under ``REVIEW_FLOOR``, and
    the only reason this message is not DROPPED is ``pipeline.HOLD_ATS_FLOOR``
    (#166), which keeps sub-floor mail from a known relay in the review queue.
    So the fix converts a silent, confident, wrong auto-file into a correct
    verdict that asks a human — an improvement, and not a complete one.

    Closing the remaining half means demoting ``thank(s| you) for applying`` to
    ``weak``, which is what ``APPLIED.weak`` already did to its sibling
    ``thank(s| you) for your application`` on exactly this reasoning. That
    moves acknowledgements across the whole corpus and is deliberately not in
    this change; see the issue.
    """
    result = classify(
        f"{OPENER} We have received your application. "
        "We have decided not to move forward with your application."
    )

    # THE INVARIANT. This one must hold forever: the harm was a rejection
    # filing itself as an acknowledgement, and the category alone closes it.
    assert result.category == EmailCategory.REJECTION

    # CHARACTERISATION BELOW, AND IT IS ALLOWED TO MOVE UPWARD.
    #
    # If either assertion reds because confidence ROSE while the category above
    # is still REJECTION, that is the remaining half described in the docstring
    # landing, and the correct response is to UPDATE THESE TWO LINES -- never to
    # revert the change that raised it. A confident, correct rejection is a
    # better outcome than a queued one; only a confident WRONG verdict was ever
    # the defect. Greening a characterisation test by reverting an improvement
    # is a defect this repository has shipped before.
    _WHY = (
        "confidence moved. If category is still REJECTION and this number went "
        "UP, update this assertion -- the fix improved and the test is stale."
    )
    assert result.confidence < pipeline.AUTO_FILE_GATE, _WHY
    # Not destroyed either: the relay keeps sub-floor mail in the review queue.
    assert result.confidence < pipeline.REVIEW_FLOOR, _WHY
    assert pipeline.is_ats_sender(SENDER)


# ---------------------------------------------------------------------------
# The other direction: an acknowledgement is still an acknowledgement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "body"),
    [
        (
            "plain confirmation",
            f"{OPENER} We have received your application and our team is reviewing it. "
            "We will be in touch soon.",
        ),
        (
            "the opener alone",
            OPENER,
        ),
        (
            "confirmation that files the resume",
            f"{OPENER} We have received your application and will keep your resume on file.",
        ),
        (
            "confirmation naming the review",
            f"{OPENER} We are reviewing applications and will be in touch shortly.",
        ),
    ],
)
def test_an_acknowledgement_does_not_become_a_rejection(label: str, body: str) -> None:
    """The direction the fix could actually have cost something.

    Removing a negative can only raise ``rejection``, and #451 hands it ties
    against ``applied`` outright, so these are the rows a wrong version of this
    change would flip. "keep your resume on file" is deliberately included: it
    is a REJECTION strong pattern that genuine confirmations also use, which
    makes it the nearest thing in the corpus to a real collision.
    """
    result = classify(body)

    assert result.category == EmailCategory.APPLIED, label


@pytest.mark.parametrize(
    "sign_off",
    [
        "We will keep your resume on file.",
        "We wish you all the best in your job search.",
        "We encourage you to apply for future positions with us.",
    ],
)
def test_the_three_three_boundary_is_queued_and_not_filed(sign_off: str) -> None:
    """A case sitting exactly ON the line this change moves.

    The acknowledgement controls above all give ``applied`` a SECOND pattern,
    so they clear the boundary 6-to-3 and prove less than they look like they
    prove. These sit on it: the courtesy opener is ``applied`` +3, a rejection
    sign-off is ``rejection`` +3, and nothing else scores.

    Before this change the sign-off lost 3 to -2 and the message read
    ``applied`` at 0.75. Now it ties, and #451 awards a tie to the REPORT, so
    the verdict is ``rejection``.

    THAT FLIP IS THE HONEST COST OF THE FIX and it is pinned here rather than
    left for someone to find. The three sign-offs are all REJECTION ``strong``
    patterns — this file does not get to relitigate that — so a tie against a
    bare greeting resolving to ``rejection`` is the tie-break working, not
    failing. The claim being made is narrower and is what actually protects the
    user: **a 3-3 message is not confidently filed as anything.** At 0.65 it is
    under ``AUTO_FILE_GATE`` and under ``REVIEW_FLOOR``, reaching the queue only
    through ``HOLD_ATS_FLOOR``. Whichever way the verdict falls, a human is
    asked — which is the property that makes the flip affordable.
    """
    result = classify(f"{OPENER} {sign_off}")

    assert result.confidence < pipeline.AUTO_FILE_GATE
    assert result.scores["applied"] == result.scores["rejection"]


def test_a_later_stage_still_wins_under_the_same_opener() -> None:
    """The courtesy opener must not decide an invitation either.

    The same greeting prefixes interview invitations; this pins that the
    deletion did not simply hand every "thank you for applying" message to
    ``rejection``.
    """
    result = classify(f"{OPENER} We would like to invite you for an interview next week.")

    assert result.category == EmailCategory.INTERVIEW


# ---------------------------------------------------------------------------
# The patterns themselves, so a revert is loud
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reintroduced",
    ["thank you for applying", "application.{0,20}received"],
)
def test_an_acknowledgement_opener_is_not_a_rejection_negative(reintroduced: str) -> None:
    """Reintroducing either pattern must fail here and say why.

    The scoring tests above would catch it too, but only as "rejection came out
    applied", which is several inferential steps from the cause. This names the
    two literals so the next person reads the fix rather than rediscovering it.

    ``EmailCategory.INTERVIEW`` removed the same family in #348 for the same
    reason; the five negatives REJECTION keeps each name a different STAGE
    ("schedule an interview", "pleased to offer"), which is a real argument
    that a message is not a rejection. A greeting is not.
    """
    assert reintroduced not in PATTERNS[EmailCategory.REJECTION].negative
