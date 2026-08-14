"""A rejection that reads "Follow-Up" in the subject line.

The message is real: Gmail id ``19ff4d11faa3721d``, 2026-08-12 07:12:53Z, from
Anthropic via Greenhouse, and it is the single most standard rejection sentence
in existence wrapped in the single most ambiguous subject line. Against the
classifier as it stood it produced this:

    subject ONLY                       -> follow_up  0.90
    subject + the Gmail snippet        -> follow_up  0.90   <- what a scan sees
    the Gmail snippet ONLY             -> other      0.50

Two independent defects, compounding:

1. ``follow-?up`` was a STRONG pattern, so the bare compound noun in a subject
   was worth +6 — 0.90 confidence, auto-file, no review — and no amount of body
   evidence could out-vote it. The word appears in scheduling mail, recruiter
   nudges and rejections alike; it now scores as the weak evidence it is, and
   ``FOLLOW_UP`` carries a ``veto`` on stated hiring decisions so a rejection
   body wins outright rather than merely tying.
2. "we have decided not to move forward with your application" matched NOTHING.
   The pattern list had the participle three times over ("not moving forward")
   and the infinitive not at all. Its neighbours were audited at the same time;
   see ``STANDARD_REJECTION_SENTENCES``, every entry of which was verified to
   score zero or lose before this change.

The third defect is not a classifier bug and is not fixed here — see
``test_follow_up_verdicts_reach_no_persist_path`` at the bottom, which pins it
as characterisation.

Assertions are on the category a user would see plus the confidence BAND the
rest of the system keys off (0.90 = ``hybrid.py`` accepts the rules layer
outright and ``pipeline.AUTO_FILE_GATE`` files a row; 0.70 =
``pipeline.REVIEW_FLOOR``, the review queue) — not on which regex fired, so the
patterns stay free to be rewritten.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

# ---------------------------------------------------------------------------
# The production message, byte for byte.
# ---------------------------------------------------------------------------
ANTHROPIC_SENDER = "no-reply@us.greenhouse-mail.io"
ANTHROPIC_SUBJECT = "Anthropic Follow-Up for TPU Kernel Engineer | Ayush Yadav"
# Exactly what the Gmail API's `snippet` field carries. A cloud scan fetches
# metadata only, so this is ALL the classifier ever sees of the body.
ANTHROPIC_SNIPPET = (
    "Hi Ayush, Thank you so much for your interest in Anthropic and for the "
    "time and effort you have invested in our process. After consideration, "
    "we have decided not to move forward with your application"
)

# The confirmation for the same requisition, also real, also from Greenhouse.
# It is the over-correction canary: "delighted", "consider joining our team"
# and "submit an application" are exactly the words a clumsy rejection regex
# trips on.
CONFIRMATION_SUBJECT = "Thank you for applying to Anthropic"
CONFIRMATION_SNIPPET = (
    "We appreciate you taking the time to submit an application for the TPU "
    "Kernel Engineer position, and are delighted that you would consider "
    "joining our team!"
)


def test_the_production_rejection_is_a_rejection() -> None:
    """subject + snippet — what the scan actually classifies. Was follow_up/0.90."""
    result = CLASSIFIER.classify(
        ANTHROPIC_SUBJECT, ANTHROPIC_SNIPPET, ANTHROPIC_SENDER
    )

    assert result.category is EmailCategory.REJECTION, result.scores
    # 0.90 is not cosmetic. Below AUTO_FILE_GATE (0.85) the message goes to the
    # review queue instead of settling the application, and below 0.90
    # hybrid.py stops trusting the rules layer outright.
    assert result.confidence >= 0.90, result.scores


def test_the_rejection_sentence_alone_is_a_rejection() -> None:
    """snippet ONLY, no subject to help. Was other/0.50.

    This is the half of the fix that lives in the pattern list rather than in
    the veto: with no subject there is nothing for a veto to overturn, so the
    sentence has to score on its own.
    """
    result = CLASSIFIER.classify("", ANTHROPIC_SNIPPET, ANTHROPIC_SENDER)

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= 0.90, result.scores


def test_a_bare_follow_up_subject_is_not_worth_high_confidence() -> None:
    """subject ONLY, the ambiguous half on its own. Was follow_up/0.90.

    "Follow-Up" says a thread is being continued and nothing else. It may still
    be the best guess available — the category is unchanged — but 0.90 from one
    compound noun and no other evidence is an auto-file, and the mail that
    proved it wrong is the one at the top of this file.
    """
    result = CLASSIFIER.classify(ANTHROPIC_SUBJECT, "", ANTHROPIC_SENDER)

    assert result.category is EmailCategory.FOLLOW_UP, result.scores
    assert result.confidence < 0.85, result.scores


def test_a_rejection_body_beats_a_genuine_follow_up_subject() -> None:
    """What the veto tier is for, and it is not the same case as above.

    "Following up on your application" is a real strong subject match at +6 —
    demoting the bare compound noun does nothing to it. A rejection body scores
    +6 of its own, which merely TIES, and a tie is settled by enum declaration
    order at confidence 0.60. Vetoing hands the rejection the whole margin.
    """
    result = CLASSIFIER.classify(
        "Following up on your application to Anthropic",
        ANTHROPIC_SNIPPET,
        ANTHROPIC_SENDER,
    )

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= 0.90, result.scores
    assert result.scores["follow_up"] <= 0, result.matched_patterns
    assert any(p.startswith("[VETO]") for p in result.matched_patterns)


# ---------------------------------------------------------------------------
# The neighbourhood audit. Every sentence here was run against the classifier
# as it stood on 2026-08-12; the ones marked WAS-MISS scored zero for
# `rejection`, and "unable to offer you a position" scored +3 and was then
# cancelled to -2 by rejection's own `offer (you|letter|of employment)`
# negative. Nothing in this list is invented: each is boilerplate an ATS
# actually sends.
# ---------------------------------------------------------------------------
STANDARD_REJECTION_SENTENCES = [
    # WAS-MISS: the infinitive. The whole reason this file exists.
    "After consideration, we have decided not to move forward with your application.",
    "We have decided not to move forward with your candidacy at this time.",
    # WAS-MISS: `move(d)?` has no participle, so "moving forward with other
    # candidates whose qualifications..." — the commonest wording of all — scored 0.
    "We will be moving forward with other candidates whose qualifications more closely match the role.",
    # WAS-MISS: `decided to pursue other candidates` needed both the lead-in
    # and the noun "candidates".
    "We have decided to pursue other applicants.",
    # WAS-MISS: `not (been )?selected` needed a trailing position/role/interview.
    "You have not been selected.",
    # WAS-MISS twice over: "unable" is not "not able", and the strong match it
    # earns was then cancelled by rejection's own `offer you` negative.
    "We are unable to offer you a position at this time.",
    # WAS-MISS: "unable to proceed" alongside the covered "decided not to proceed".
    "We are unable to proceed with your candidacy.",
    # WAS-MISS: `won't be advancing` covered the contraction only.
    "We will not be advancing your candidacy at this time.",
    # --- shapes that already worked; here so a rewrite cannot lose them ------
    "We will not be moving forward with your application.",
    "We have decided to move forward with other candidates.",
    "You were not selected for this position.",
    "Unfortunately, we are not moving forward with your application.",
    "We regret to inform you that we have decided not to proceed.",
    "The position has been filled.",
]


@pytest.mark.parametrize("body", STANDARD_REJECTION_SENTENCES)
def test_standard_rejection_sentences_classify_as_rejection(body: str) -> None:
    result = CLASSIFIER.classify("", body, ANTHROPIC_SENDER)

    assert result.category is EmailCategory.REJECTION, result.matched_patterns
    # REVIEW_FLOOR. Below this a lifecycle verdict is dropped entirely: it
    # neither files a row nor reaches the review queue.
    assert result.confidence >= pipeline.REVIEW_FLOOR, result.scores


# ---------------------------------------------------------------------------
# Over-correction guards. The failure mode of a fix like this is not that it
# misses a rejection — it is that it starts seeing rejections everywhere.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Just following up on your application", ""),
        ("", "Just following up on your application — any news?"),
        ("Following up on my application status", "Any update would be appreciated."),
        ("Checking in on my application", "I remain very interested in the role."),
        ("Quick follow-up", "Wanted to check in on my application status."),
    ],
)
def test_a_genuine_nudge_is_still_a_follow_up(subject: str, body: str) -> None:
    """No rejection language anywhere: the category must not have moved."""
    result = CLASSIFIER.classify(subject, body, None)

    assert result.category is EmailCategory.FOLLOW_UP, result.scores


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        (
            "Follow-up: interview scheduling for TPU Kernel Engineer",
            "We would like to schedule an interview to discuss the role. "
            "Please pick a time that works for you.",
        ),
        (
            "Following up on our conversation",
            "Sharing a Calendly link to book your technical interview.",
        ),
    ],
)
def test_scheduling_mail_with_follow_up_in_the_subject_is_not_a_rejection(
    subject: str, body: str
) -> None:
    """The mail this fix could most plausibly have broken."""
    result = CLASSIFIER.classify(subject, body, None)

    assert result.category is EmailCategory.INTERVIEW, result.scores
    assert result.scores["rejection"] <= 0, result.matched_patterns


def test_the_real_confirmation_still_classifies_applied_at_090() -> None:
    """The template both of the owner's live Anthropic confirmations use.

    The confidence is asserted exactly, not as a floor. A rejection pattern
    that scored anything at all here would shrink `applied`'s runner-up margin
    and drop it from 0.90 to 0.80 with the category still reading right — a
    silent regression that a category-only assertion would wave through.

    Asserted in two halves since #166 fixed ``ATS_DOMAINS``. The LADDER rung is
    what the paragraph above is about, and it is only visible with the sender
    withheld; delivered from Greenhouse it carries the +0.05 ATS bonus on top.
    Splitting them keeps the margin regression detectable at 0.90 and stops a
    future change to the ATS domain list from being read as a scoring change.
    """
    ladder_only = CLASSIFIER.classify(CONFIRMATION_SUBJECT, CONFIRMATION_SNIPPET, None)
    assert ladder_only.confidence == pytest.approx(0.90), ladder_only.scores

    result = CLASSIFIER.classify(
        CONFIRMATION_SUBJECT, CONFIRMATION_SNIPPET, ANTHROPIC_SENDER
    )

    assert result.category is EmailCategory.APPLIED, result.scores
    # 0.90 + the ATS bonus. Greenhouse's relay only started earning that bonus
    # with #166, which added ``greenhouse-mail.io`` to ``ATS_DOMAINS``: the list
    # held only ``greenhouse.io``, and ``us.greenhouse-mail.io`` is not under it.
    # Since #260 the sender is matched as a domain (exact or proper subdomain)
    # rather than as a substring, and this address matches either way. Both
    # values are above AUTO_FILE_GATE, so what this message DOES is unchanged.
    assert result.confidence == pytest.approx(0.95), result.scores
    assert result.scores["rejection"] <= 0, result.matched_patterns


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        (
            "Your offer from Anthropic",
            "We are pleased to offer you the position of TPU Kernel Engineer.",
        ),
        ("Offer letter", "Please find attached your offer letter of employment."),
    ],
)
def test_a_real_offer_is_still_an_offer(subject: str, body: str) -> None:
    """The `offer you` negative was narrowed, so prove it still bites.

    Narrowing it with lookbehinds is what lets "unable to offer you a position"
    score as a rejection; if it had been deleted instead, an offer letter would
    start scoring as one too.
    """
    result = CLASSIFIER.classify(subject, body, None)

    assert result.category is EmailCategory.OFFER, result.scores
    assert result.scores["rejection"] < 0, result.matched_patterns


# ---------------------------------------------------------------------------
# What the fix means downstream, and the defect it does NOT fix.
# ---------------------------------------------------------------------------


def _item(category: str, confidence: float) -> pipeline.PipelineItem:
    return pipeline.PipelineItem(
        message_id="19ff4d11faa3721d",
        category=category,
        sender_email=ANTHROPIC_SENDER,
        subject=ANTHROPIC_SUBJECT,
        sender_name="Anthropic",
        received_at=datetime(2026, 8, 12, 7, 12, 53, tzinfo=UTC),
        confidence=confidence,
        thread_id="19ff4d11faa3721d",
        snippet=ANTHROPIC_SNIPPET,
    )


def test_the_production_rejection_now_files_an_anthropic_row() -> None:
    """End of the line: the verdict has to survive the scan pipeline too.

    A rejection at 0.90 clears AUTO_FILE_GATE and names its employer, so it
    becomes a real row with a terminal stage. That is the behaviour the owner
    was missing, and it is the reason the confidence assertions above are
    bands rather than "not zero".
    """
    verdict = CLASSIFIER.classify(
        ANTHROPIC_SUBJECT, ANTHROPIC_SNIPPET, ANTHROPIC_SENDER
    )
    rolled = pipeline.roll_up_applications(
        [_item(verdict.category.value, verdict.confidence)]
    )

    assert [(r.company_display, r.status) for r in rolled] == [("Anthropic", "rejected")]


def test_follow_up_verdicts_reach_no_persist_path() -> None:
    """CHARACTERISATION, not an endorsement. Measured 2026-08-12.

    This is why the message was absent from the ``emails`` table entirely
    rather than merely mis-staged, and it is a defect in its own right:
    ``follow_up`` is excluded from ``_qualifies_for_hard_row`` AND from
    ``collect_review_items``, and those two lists are the ONLY inputs
    ``cloud.applications._persist_message_refs`` is ever called with. So a
    ``follow_up`` verdict is discarded — no row, no queue entry, no stored
    message — whatever the scan window was.

    Deliberately NOT fixed here. Giving an entire category a persist path is a
    product decision about what the needs-classification queue is for, and it
    belongs in ``cloud/applications.py`` and ``cloud/pipeline.py``, not in the
    pattern list. Pinned as a test so the next person finds it stated rather
    than having to rediscover it from a missing row.
    """
    item = _item("follow_up", 0.90)

    assert pipeline._qualifies_for_hard_row(item) is None
    assert pipeline.roll_up_applications([item]) == []
    assert pipeline.collect_review_items([item]) == []
