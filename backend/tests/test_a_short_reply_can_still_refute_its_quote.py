"""A REPLY TOO SHORT TO SPEAK OVER ITS QUOTE CAN STILL CONTRADICT IT.

Issue #417, the part of it that survived #441.

``strip_quoted_history`` drops the history a reply merely repeats, so a
withdrawal stops scoring the offer it withdraws. But it drops nothing when the
reply's own words are shorter than :data:`_MIN_ASSERTED_CHARS` — the floor that
keeps "fyi" over a forwarded rejection from being scored as silence. A
rescission is very often exactly that short. When it is, the whole body goes to
the scorer, the quoted "we are pleased to offer you the position" wins, and the
result clears the auto-file gate:

    own-text len   stripped?   verdict   conf   auto-filed
              22   False       OFFER     0.95   YES
              27   False       OFFER     0.95   YES
              39   False       OFFER     0.95   YES     <- floor is 40
              43   True        OTHER     0.50   no

"We must withdraw the offer." is 27 characters.

WHY THE OBVIOUS FIX IS THE WRONG ONE, and it is what shapes this file. Capping
confidence whenever the floor refused a strip regresses a common GOOD case: a
short reply above a quoted interview invitation ("Thursday works for me")
scores the quote and advances the card, which is the RIGHT outcome. Capping
that sends a correct auto-file to the review queue. So the span before the
boundary is consulted even when it is under the floor, and the verdict is
capped only when those words REFUTE the category the quote won with.

WHAT THIS FILE DOES NOT CLAIM. It never asserts that a withdrawal reads as a
rejection. It does not; there is no withdrawal category and no vocabulary for
one, and #10 forbids inventing one from three wordings written by the author of
the rules. The claim is only that the product stops asserting an offer nobody
holds, and asks instead — which is where ``test_a_reply_speaks_for_itself.py``
left the long-form shape.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import (
    _MIN_ASSERTED_CHARS,
    _REFUTED_CONFIDENCE,
    _SEMANTIC_REFUTATIONS,
    PATTERNS,
    get_rules_classifier,
    own_text_refutes,
    own_text_span,
    strip_quoted_history,
)
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR
from jobtracker.database.models import EmailCategory

ATS = "no-reply@greenhouse.io"

#: The offer this thread is about, as the sender's client quotes it back.
QUOTED_OFFER = (
    "\n\nOn Tuesday, Cedarhollow Systems Talent wrote:\n"
    "> Hi Ayush,\n"
    "> We are pleased to offer you the position of Backend Engineer at\n"
    "> Cedarhollow Systems. Your start date will be 1 September and your\n"
    "> annual salary $145,000. Please sign and return the offer letter.\n"
)

#: An interview invitation quoted back the same way. The directional control:
#: a short reply above THIS must keep auto-filing.
QUOTED_INVITE = (
    "\n\nOn Tuesday, Cedarhollow Systems Recruiting wrote:\n"
    "> Hi Ayush,\n"
    "> We would like to invite you to interview for the Backend Engineer\n"
    "> role. Would you be available on Thursday at 2pm for a 45 minute\n"
    "> technical interview? Please confirm your availability and we will\n"
    "> send a calendar invite.\n"
)

#: The pair that sits ON the floor, one character under and three characters
#: over. Lengths are asserted against the constant rather than written down, so
#: moving the floor moves the control with it instead of leaving it stranded.
UNDER_FLOOR = "We must regretfully withdraw the offer."
OVER_FLOOR = "We must regretfully withdraw the offer now."


@pytest.fixture()
def rules():
    return get_rules_classifier()


# ── the defect ───────────────────────────────────────────────────────────────


def test_a_short_withdrawal_over_a_quoted_offer_is_not_auto_filed(rules) -> None:
    """#417's live shape. OFFER at 0.95, filed without asking, before this.

    The mail says the offer is gone. The board said the user had one.
    """

    body = "We must withdraw the offer." + QUOTED_OFFER
    assert len(own_text_span(body) or "") < _MIN_ASSERTED_CHARS, (
        "the fixture stopped being a short reply, so it no longer exercises "
        "the floor and this test proves nothing"
    )

    result = rules.classify("Re: Your offer from Cedarhollow Systems", body, ATS)
    assert result.confidence < AUTO_FILE_GATE, (
        f"a withdrawal was auto-filed as {result.category.value} at "
        f"{result.confidence}. Its own words revoke the offer; the only reason "
        "the offer scored at all is that those words were 27 characters long."
    )


def test_the_capped_verdict_is_queued_and_not_binned(rules) -> None:
    """Below the gate, ABOVE the floor — a question, not a deletion.

    ``REVIEW_FLOOR`` is where the pipeline stops asking and starts dropping.
    A withdrawal dropped in silence is not better than one filed as an offer;
    it is the same board with less evidence. This is the whole argument for
    capping rather than flipping to ``other``, which lands at 0.50 and is
    under the floor.
    """

    body = "We must withdraw the offer." + QUOTED_OFFER
    result = rules.classify("Re: Your offer from Cedarhollow Systems", body, ATS)
    assert REVIEW_FLOOR <= result.confidence < AUTO_FILE_GATE, (
        f"the capped verdict landed at {result.confidence}, outside "
        f"[{REVIEW_FLOOR}, {AUTO_FILE_GATE}). Under the floor it is dropped "
        "without a trace; at or over the gate it is the bug."
    )
    assert result.confidence == _REFUTED_CONFIDENCE


def test_the_floor_no_longer_decides_whether_a_withdrawal_is_filed(rules) -> None:
    """THE THRESHOLD CONTROL: one case each side of the boundary, same answer.

    Before, these two differed only in the word "now" and got opposite
    treatment — 39 characters was auto-filed as an offer and 43 was not. The
    fix is not "the short one now abstains too"; it is that the length of the
    withdrawal stopped being the thing that decides.
    """

    assert len(UNDER_FLOOR) == _MIN_ASSERTED_CHARS - 1
    assert len(OVER_FLOOR) == _MIN_ASSERTED_CHARS + 3

    under = UNDER_FLOOR + QUOTED_OFFER
    over = OVER_FLOOR + QUOTED_OFFER
    assert strip_quoted_history(under) == under, "the short one must NOT strip"
    assert strip_quoted_history(over) == OVER_FLOOR, "the long one must strip"

    subject = "Re: Your offer from Cedarhollow Systems"
    for label, body in (("under", under), ("over", over)):
        result = rules.classify(subject, body, ATS)
        assert result.confidence < AUTO_FILE_GATE, (
            f"the {label}-floor withdrawal was auto-filed as "
            f"{result.category.value} at {result.confidence}. One word of "
            "length is not a reason to file one and question the other."
        )


# ── the control that makes the narrow rule necessary ─────────────────────────


def test_a_short_acceptance_over_a_quoted_invite_still_auto_files(rules) -> None:
    """THE DIRECTIONAL CONTROL. Fails if the fix is "cap the fallback".

    "Thursday works for me" says nothing the classifier can read, so the quote
    is scored and the card advances to interview. That is correct, common, and
    the reason #417 may not be fixed by distrusting the fallback: capping here
    sends a right answer to the review queue.
    """

    body = "Thursday works for me." + QUOTED_INVITE
    assert len(own_text_span(body) or "") < _MIN_ASSERTED_CHARS

    result = rules.classify("Re: Interview for Backend Engineer", body, ATS)
    assert result.category is EmailCategory.INTERVIEW
    assert result.confidence >= AUTO_FILE_GATE, (
        f"a short acceptance over a quoted invitation dropped to "
        f"{result.confidence}. The quote is the only thing either message says "
        "and reading it was right; this is the good case the fix must leave "
        "alone."
    )


def test_a_scheduling_problem_is_not_a_retraction(rules) -> None:
    """The same control with a NEGATIVE stance, which is the harder half.

    "no longer" in a reply above an invitation is about the Thursday, not
    about the interview. The retraction vocabulary is scoped to the
    opportunity — the role, the offer, the opening — precisely so a
    rescheduling note does not read as a withdrawal.
    """

    body = "Thursday no longer works for me." + QUOTED_INVITE
    assert len(own_text_span(body) or "") < _MIN_ASSERTED_CHARS

    result = rules.classify("Re: Interview for Backend Engineer", body, ATS)
    assert result.category is EmailCategory.INTERVIEW
    assert result.confidence >= AUTO_FILE_GATE, (
        f"a rescheduling reply dropped to {result.confidence}. The interview "
        "still exists; only the time is in question, and the card should "
        "advance."
    )


# ── what the floor is for, and must go on doing ──────────────────────────────


@pytest.mark.parametrize("filler", ["fyi", "see below", "?" * 20])
def test_a_reply_that_says_nothing_still_falls_back_to_its_quote(rules, filler: str) -> None:
    """The floor's reason, unchanged. Consulting the span is not lowering it.

    A bare forward has written no readable words. Scoring only those scores
    nothing, which abstains on a message whose verdict is sitting in the
    quote. Nothing here refutes anything, so nothing is capped.
    """

    assert len(filler) < _MIN_ASSERTED_CHARS
    body = filler + QUOTED_OFFER
    assert strip_quoted_history(body) == body
    assert own_text_refutes(filler, "offer") == []

    result = rules.classify("Fwd: Your offer from Cedarhollow", body, ATS)
    assert result.category is EmailCategory.OFFER
    assert result.confidence >= AUTO_FILE_GATE, (
        f"a forwarded offer scored {result.confidence}. The forwarder said "
        "nothing; the message is still an offer."
    )


def test_a_long_withdrawal_is_untouched_by_this_rule(rules) -> None:
    """The shape #441 already fixed stays fixed, and by the same route.

    Its own words are over the floor, so the quote is stripped and this rule
    never runs. Pinned so a later reader can see that the cap did not quietly
    become the reason the long form abstains.
    """

    own = (
        "Hi Ayush, Unfortunately we must withdraw the offer of employment "
        "extended to you last week. The role has been closed and we are not "
        "able to move forward."
    )
    body = own + QUOTED_OFFER
    assert strip_quoted_history(body) == own
    assert own_text_span(body) is not None
    assert len(own_text_span(body) or "") >= _MIN_ASSERTED_CHARS

    result = rules.classify("Re: Your offer from Cedarhollow Systems", body, ATS)
    assert result.confidence < AUTO_FILE_GATE


# ── the mechanism, stated on the text rather than on a verdict ───────────────


def test_the_span_is_readable_even_when_the_floor_refuses_it() -> None:
    """The one thing that was missing: nothing consulted the span.

    ``strip_quoted_history`` answers "which words get scored". This answers
    "which words did the sender write", and the two differ exactly on the
    messages #417 is about.
    """

    body = "We must withdraw the offer." + QUOTED_OFFER
    assert strip_quoted_history(body) == body, "the floor refuses this one"
    assert own_text_span(body) == "We must withdraw the offer."
    assert own_text_span("A message with no quote at all.") is None


def test_the_refutation_set_is_derived_from_the_patterns() -> None:
    """No second copy of the vocabulary, which is how the first one rotted.

    The semantic refutations are the category's own negatives minus the genre
    filters — the split the ``_NOISE_NEGATIVES`` comment already names. Deriving
    them means a pattern edited in ``PATTERNS`` is edited here too, and it
    keeps this change clear of the three surfaces that read the PATTERNS
    literals statically.
    """

    for category, patterns in PATTERNS.items():
        derived = {p.pattern for p in _SEMANTIC_REFUTATIONS[category.value]}
        assert derived <= set(patterns.negative), (
            f"{category.value} refutes with a pattern that is not one of its "
            "own negatives — the vocabulary has been forked"
        )
    assert "unfortunately" in {p.pattern for p in _SEMANTIC_REFUTATIONS["offer"]}, (
        "the refutations named in the _NOISE_NEGATIVES comment must be present"
    )


def test_a_retraction_refutes_forward_progress_and_not_a_rejection() -> None:
    """A withdrawal un-makes an offer. It does not un-make a rejection.

    ``rejection`` is excluded on purpose: "we have withdrawn your application
    from consideration" is a rejection stated in retraction words, and capping
    it would send the one category the classifier is already too shy about
    back to the queue.
    """

    own = "We must withdraw the offer."
    assert own_text_refutes(own, "offer")
    assert own_text_refutes(own, "interview")
    assert own_text_refutes(own, "rejection") == []
    assert own_text_refutes(own, "other") == []


@pytest.mark.parametrize(
    "own",
    [
        "We must withdraw the offer.",
        "The offer has been rescinded.",
        "We are revoking the offer.",
        "The role is no longer available.",
        "The position has been closed.",
        "There is a hiring freeze.",
    ],
)
def test_the_retraction_vocabulary_is_a_family_and_not_a_keyword(own: str) -> None:
    """#10: not a patch that only recognises the word "rescind".

    Six wordings, one for each branch of the alternation, so a branch deleted
    from the pattern takes a case with it rather than hiding behind the others.
    """

    assert len(own) < _MIN_ASSERTED_CHARS
    assert own_text_refutes(own, "offer"), f"{own!r} did not read as a retraction"


@pytest.mark.parametrize(
    "own",
    [
        "Thursday works for me.",
        "Thursday no longer works for me.",
        "Sounds good, see you then.",
        "Thanks, I accept the offer!",
    ],
)
def test_an_ordinary_short_reply_refutes_nothing(own: str) -> None:
    """The negative side of the same set. Without it the pattern could be
    ``.``  and every case above would still pass."""

    assert len(own) < _MIN_ASSERTED_CHARS
    assert own_text_refutes(own, "offer") == []
    assert own_text_refutes(own, "interview") == []
