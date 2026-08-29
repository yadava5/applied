"""Issue #458 — eleven real rejections that reached nothing, and why.

``follow_up`` is dropped everywhere in this pipeline: it never files a card
(``_qualifies_for_hard_row`` refuses it by name), it never reaches the review
queue (the ATS floor was scoped to lifecycle categories, and ``follow_up`` is
excluded from those), and it never even produces a ``DroppedVerdict``, which is
scoped to lifecycle categories too. Three instruments, one blind spot.

The premise for all of that is one sentence, written in
``collect_review_items`` and repeated in ``test_ingestion_hole_166.py``: a
follow-up is **the reader's own chasing mail**, so queueing it asks them to
classify themselves. That premise is true of mail the reader sent. It is false
of mail an applicant tracking system relayed, and the difference is the whole
of this module.

WHAT THE PREMISE COSTS WHEN IT IS APPLIED TO A RELAY. Measured on the
17,260-message independent corpus, 2026-08-29:

    ``follow_up`` verdicts in the whole corpus              11
    ...relayed by a domain on ``rules.ATS_DOMAINS``         11
    ...whose ground truth is ``rejection``                  11

Every one is a transcribed ATS rejection (``tests/corpus_independent/
observed.py``) whose subject carries the sender's own word "Follow-Up" and
whose decision sentence sits one character past Gmail's ~186-character snippet
cut. Delivered whole, the same message is ``rejection`` at 0.95. Delivered as
the snippet, the rejection veto never fires, the weak ``follow-?up`` subject
pattern is all that is left, and the message leaves through the terminal drop
— no card, no queue entry, no counter, no log line.

WHY NOT A CONFIDENCE FIX. There already was one. ``follow-?up`` was demoted
from a strong pattern to a weak one, which moved this shape from 0.90 to 0.70
and changed nothing whatsoever, because the exclusion is CATEGORICAL. No score
escapes it. That is also why every assertion below that fixes a number fixes it
at three scores rather than one.

WHY NOT A WORDING. #458 records two phrase extensions that take the corpus to
633/633 with zero noise, and declines both: the corpus was written from the
classifier's own vocabulary, so transcribing a sender's sentence back into the
product rebuilds that closed loop one layer up. Nothing here reads the text.
The signal is the SENDER and the CATEGORY, and it survives any wording.

WHERE THE BOUND IS, said plainly rather than left to be discovered. This clause
is bounded by the classifier's ``follow_up`` detection, not by the sender: a
relayed message that is NOT about the reader — a job-alert digest, say — would
reach the queue if its own text scored ``follow_up``. Zero of the corpus's 400
``ats-relay-noise`` messages do (they score ``other``), and the five shapes
that family is built from are asserted below. The residual is real and it is
one-directional: it can only put a message in front of a person, never file
one, because ``_qualifies_for_hard_row`` is untouched.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import ATS_DOMAINS, RulesClassifier
from jobtracker.cloud import pipeline

CLASSIFIER = RulesClassifier()

GREENHOUSE = "no-reply@us.greenhouse-mail.io"

#: Employer and role are INVENTED, exactly as ``observed.py`` parameterises
#: them: the wording is a form letter and is the evidence, the employer is not
#: ours to publish.
DISPLAY = "Otterburyshore Dynamics"
ROLE = "Data Engineer"

SUBJECT = f"{DISPLAY} Follow-Up for {ROLE} | Ayush Yadav"
BODY = (
    f"Hi Ayush, Thank you so much for your interest in {DISPLAY} and for the "
    "time and effort you have invested in our process. After consideration, "
    "we have decided not to move forward with your application at this time."
)
#: Gmail's snippet: ~186 characters, and it stops on "not to move fo" — one
#: character before the phrase that would veto the follow-up reading.
SNIPPET = BODY[:186]


def _item(
    message_id: str,
    *,
    category: str,
    confidence: float,
    sender: str = GREENHOUSE,
    subject: str = SUBJECT,
    snippet: str = SNIPPET,
) -> pipeline.PipelineItem:
    return pipeline.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email=sender,
        subject=subject,
        sender_name=None,
        received_at=None,
        confidence=confidence,
        thread_id=None,
        snippet=snippet,
    )


def test_the_snippet_is_read_as_your_own_follow_up_and_the_body_is_not() -> None:
    """The mechanism, reproduced by execution rather than described.

    Both halves matter. The second says the message really is a rejection — so
    the first is a loss and not a judgement call — and it says the classifier
    is not what is wrong here: hand it the whole body and it is right at 0.95.
    What the product loses is entirely a function of how much text arrived.

    The snippet verdict sits EXACTLY on ``REVIEW_FLOOR``. That is not a
    coincidence worth hiding: it is why "raise the floor" and "lower the floor"
    are both answers to a different question, and it is asserted so that a
    drift in the rules shows up here as a changed shape rather than as a
    silently different reason for the same pass.
    """

    held = CLASSIFIER.classify(SUBJECT, SNIPPET, GREENHOUSE)
    assert held.category.value == "follow_up", held.scores
    assert held.confidence == pytest.approx(pipeline.REVIEW_FLOOR), (
        "the shape this module exists for sits exactly on the review floor; if "
        "this moves, re-read the module docstring before adjusting the number"
    )

    whole = CLASSIFIER.classify(SUBJECT, BODY, GREENHOUSE)
    assert whole.category.value == "rejection", whole.scores
    assert whole.confidence >= pipeline.AUTO_FILE_GATE


def test_a_relayed_follow_up_reaches_a_person() -> None:
    """#458 itself: the message gets a queue entry a human can act on.

    ``company_display`` is asserted for the same reason #447 asserts it — a
    queue row with no employer against it is a row nobody can do anything
    with, and the whole point of queueing this is that a person can settle it.
    """

    queued = pipeline.collect_review_items([_item("relayed", category="follow_up", confidence=0.70)])

    assert [r.message_id for r in queued] == ["relayed"], (
        "a real ATS rejection, read as the reader's own chasing mail because "
        "its subject says Follow-Up and its verdict sentence was truncated "
        "away. Before #458 it reached no card, no queue entry, no counter and "
        "no log line — indistinguishable from a mailbox that never received it"
    )
    assert queued[0].company_display == DISPLAY
    assert queued[0].category == "follow_up", (
        "the proposal is stored as the classifier gave it and the COMMITTED "
        "state stays needs_review; this clause changes who is asked, never "
        "what the product asserts"
    )


def test_every_relay_on_the_list_is_covered() -> None:
    """One case per member of ``ATS_DOMAINS``, not one example from it.

    The corpus draws its senders across six different relays and the real
    mailbox spans seven platforms, so a clause proven on Greenhouse alone is
    proven on a sixth of the population. Iterating the list also means a relay
    added later arrives with this coverage rather than without it.
    """

    assert len(ATS_DOMAINS) >= 15, "the list shrank; check what was removed"
    for domain in ATS_DOMAINS:
        sender = f"no-reply@{domain}"
        queued = pipeline.collect_review_items(
            [_item(f"relay-{domain}", category="follow_up", confidence=0.70, sender=sender)]
        )
        assert [r.message_id for r in queued] == [f"relay-{domain}"], domain


def test_a_follow_up_nobody_relayed_is_still_dropped() -> None:
    """The direction of the whole argument, asserted rather than assumed.

    ``follow_up`` means the reader's own chasing mail and that mail still
    drops. Four senders: the user's own address, a company's careers address, a
    person at the employer, and a job board that is not an ATS. The last one is
    the #260 shape — a lookalike host must not buy its way onto a closed list
    — and it is included here because this clause now routes on that list.
    """

    for sender in (
        "ayush@example.com",
        "careers@otterburyshore.example",
        "hiring-manager@otterburyshore.example",
        "no-reply@notifications.linkedin.com",
        "no-reply@greenhouse-mail.io.attacker.example",
    ):
        assert pipeline.collect_review_items(
            [_item(f"own-{sender}", category="follow_up", confidence=0.70, sender=sender)]
        ) == [], sender


def test_the_clause_reads_follow_up_and_not_some_other_category() -> None:
    """The same message, the same relay, one category apart.

    ``other`` from a relay is queued only when its text speaks about an
    application the reader made (#447), and this text does not — that is the
    whole of #458's original framing. So the pair below is a same-typed
    operand check on the category constant: read ``other`` where the clause
    says ``follow_up`` and this drops while the case above queues; read them
    the other way round and the reverse happens.
    """

    assert pipeline.references_an_application(SUBJECT, SNIPPET) is False, (
        "if this ever becomes True the message is queued by #447's clause and "
        "the pair below stops testing #458's"
    )
    assert pipeline.collect_review_items(
        [_item("as-other", category="other", confidence=0.50)]
    ) == [], (
        "an `other` verdict from a relay whose text references no application "
        "of the reader's must still drop — that is #447's control and this "
        "change must not have widened it"
    )


def test_no_confidence_rescues_it_and_none_files_it() -> None:
    """Three scores, one on the floor, one under it, one over the gate.

    The under-the-floor case is the pre-#458 ATS floor's own territory; the
    0.70 case is the shape that actually arrives; the 0.90 case is what the
    rules returned for this same shape BEFORE ``follow-?up`` was demoted to a
    weak pattern. All three queue, because the exclusion this replaces was
    categorical and a confidence-shaped fix would have missed at least one of
    them — the previous attempt missed all three.

    And none of them files anything. That is the guarantee that makes queueing
    safe: the message can only get a person asked.
    """

    for confidence in (0.50, pipeline.REVIEW_FLOOR, 0.90):
        item = _item(f"c-{confidence}", category="follow_up", confidence=confidence)
        assert [r.message_id for r in pipeline.collect_review_items([item])] == [
            f"c-{confidence}"
        ], confidence
        assert pipeline._qualifies_for_hard_row(item) is None, confidence
        assert pipeline.roll_up_applications([item]) == [], confidence


def test_the_queue_says_why_without_making_something_up() -> None:
    """The sentence the row carries, at each of the three scores.

    #507 is the standing scar here: the web used to INFER the hold reason from
    the confidence and told every row the same thing. These three are the real
    reasons and they are different sentences on purpose — under the floor the
    relay is what kept it, at 0.70 the classifier was unsure, and above the
    gate it was confident about a category that is never filed on its own.
    """

    def reason(confidence: float) -> str:
        return pipeline.hold_reason(
            confidence=confidence,
            subject=SUBJECT,
            sender_email=GREENHOUSE,
            snippet=SNIPPET,
            category="follow_up",
        )

    assert reason(0.50) == pipeline.HOLD_ATS_FLOOR
    assert reason(pipeline.REVIEW_FLOOR) == pipeline.HOLD_BELOW_GATE
    assert reason(0.90) == pipeline.HOLD_NOT_FILEABLE


def test_the_mail_a_relay_sends_that_is_not_yours_still_drops() -> None:
    """The control, run through the real classifier rather than asserted.

    These are the five shapes ``tests/corpus_independent`` builds its 400
    ``ats-relay-noise`` messages from — a job-alert digest, a talent-community
    blast, a profile nudge, a survey, a referral ask — all from a real relay,
    none about any application of the reader's. The corpus scores zero of the
    400 as ``follow_up``; this asserts the same thing at the shape level, on
    the verdict the classifier actually returns rather than on one written in
    by hand.

    Without this the clause reads "queue what a relay sends", which is the
    widening ``collect_review_items`` has declined twice.
    """

    shapes = (
        (
            f"New roles at {DISPLAY} this week",
            f"Hi Ayush, here are the latest openings at {DISPLAY}: {ROLE}, and "
            "several more on our careers page. Set up an alert to hear first.",
        ),
        (
            f"Join the {DISPLAY} talent community",
            f"Hi Ayush, we are building a community of engineers interested in "
            f"{DISPLAY}. Join to hear about openings like {ROLE} before they "
            "are posted publicly.",
        ),
        (
            f"Complete your {DISPLAY} candidate profile",
            "Hi Ayush, your candidate profile is missing a few details. Adding "
            f"them helps our recruiters find you for roles such as {ROLE}.",
        ),
        (
            f"A quick survey from {DISPLAY} recruiting",
            "Hi Ayush, we are asking engineers what matters most when choosing "
            "a team. Two minutes, and it helps us hire better.",
        ),
        (
            f"Know someone for {ROLE} at {DISPLAY}?",
            f"Hi Ayush, we are hiring a {ROLE} and referrals are how we find "
            "the best people. Pass this along to anyone who would be a fit.",
        ),
    )

    for subject, body in shapes:
        verdict = CLASSIFIER.classify(subject, body, GREENHOUSE)
        assert verdict.category.value != "follow_up", (subject, verdict.scores)
        item = _item(
            f"noise-{subject[:12]}",
            category=verdict.category.value,
            confidence=verdict.confidence,
            subject=subject,
            snippet=body,
        )
        assert pipeline.collect_review_items([item]) == [], subject
