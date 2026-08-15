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

Since #316 the parametrized sweep over ``STANDARD_REJECTION_SENTENCES`` asserts
``AUTO_FILE_GATE`` rather than ``REVIEW_FLOOR``, body-only and with no ATS
sender. It asserted the floor until then and was green on eight sentences the
product can recognise and never file; see that test's own docstring.
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
    # WAS-MISS: the verb that takes "with" rather than "forward". Every
    # `forward` pattern in the list missed it, so Lever's standard rejection
    # scored on `regret to inform` alone. This is the owner's Palantir mail.
    "We regret to inform you that we will not be proceeding with your candidacy for this role.",
    "We will not be continuing with your application at this time.",
    # --- shapes that already worked; here so a rewrite cannot lose them ------
    "We will not be moving forward with your application.",
    "We have decided to move forward with other candidates.",
    "You were not selected for this position.",
    "Unfortunately, we are not moving forward with your application.",
    "We regret to inform you that we have decided not to proceed.",
    "The position has been filled.",
]


@pytest.mark.parametrize("body", STANDARD_REJECTION_SENTENCES)
def test_standard_rejection_sentences_reach_the_gate_production_acts_at(
    body: str,
) -> None:
    """The bar is what the PRODUCT does, not what the classifier can recognise.

    This asserted ``REVIEW_FLOOR`` (0.70) until #316. Production acts at
    ``AUTO_FILE_GATE`` (0.85): below it a verdict is held for a human and no
    application is ever filed from it. So the assertion sat under the level at
    which the product does anything, and was green the whole time on 8 of these
    16 sentences — recognised, and unfileable. A check that passes at a
    threshold the product does not use is a check that cannot fail.

    Two deliberate choices in how it is now measured, and both are the
    difference between a gate and a formality:

    * **No sender.** ``ANTHROPIC_SENDER`` is an ATS domain and carries a +0.05
      bonus, so with it a 0.80 rung clears 0.85 and a regression from the 0.90
      rung would pass unnoticed. Body only, no bonus — the same way #316
      measured. ``test_the_palantir_rejection_clears_the_auto_file_gate`` above
      still covers the delivered-from-an-ATS case.
    * **Body, not subject.** Every one of these clears the gate from a SUBJECT
      already (a strong subject match is +6 on its own). Rejections do not put
      their decision in the subject — they title themselves "Thank you from
      <Company>" — so the subject reading is the one that never mattered.

    Mutation: dropping the ``\\byou (have|were)…not (been )?selected`` twin →
    2 of the 16 fail at 0.70 ("You have not been selected." and "You were not
    selected for this position."), which is the review queue.
    """

    result = CLASSIFIER.classify("", body, None)

    assert result.category is EmailCategory.REJECTION, result.matched_patterns
    # AUTO_FILE_GATE. Below this the verdict reaches a human and nothing else:
    # no row is filed, no application is settled, and the classifier's correct
    # answer costs the user a click it should never have had to make.
    assert result.confidence >= pipeline.AUTO_FILE_GATE, result.scores


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


# ---------------------------------------------------------------------------
# The second production rejection: Palantir, via Lever.
#
# The Anthropic mail above proved a rejection could be BEATEN by an ambiguous
# subject. This one proves the quieter half of the same problem — the classifier
# read it correctly and still could not act on it.
#
# A strong SUBJECT match scores +6 and a strong BODY match scores +3. Rejections
# put their verdict in the body and title themselves "Thank you from <Company>";
# acknowledgements put theirs in the subject ("Thank you for applying to X").
# So an acknowledgement reaches 0.90 from its subject line alone while a
# rejection carrying one decisive sentence lands on 0.70 — under AUTO_FILE_GATE,
# held for a human. On the owner's 52 stored messages the classifier had never
# once filed a rejection without one, and this asymmetry is why.
# ---------------------------------------------------------------------------
PALANTIR_SENDER = "no-reply@hire.lever.co"
PALANTIR_SUBJECT = (
    "Thank you from Palantir Technologies - Ayush Yadav - Software Engineer, New Grad"
)
# Email 114, exactly as stored: Gmail's snippet, truncated where Gmail truncates.
PALANTIR_SNIPPET = (
    "Dear Ayush, Thank you for your interest in Palantir. After careful "
    "consideration, we regret to inform you that we will not be proceeding "
    "with your candidacy for this role at this time. Please note that"
)


def test_the_palantir_rejection_clears_the_auto_file_gate() -> None:
    """subject + snippet — what the scan actually classifies. Was rejection/0.75.

    The CATEGORY was never wrong here, which is why this needs its own test: an
    assertion on the category alone passed both before and after. What was wrong
    is that "we will not be proceeding with your candidacy" — the sentence
    stating the decision — matched no pattern at all, leaving `regret to inform`
    to carry the message alone at +3. That is the 0.70 rung; the ATS bonus took
    it to 0.75; AUTO_FILE_GATE is 0.85.

    Mutation: removing BOTH halves of the new `(proceeding|continuing) with`
    pair → fails at 0.75. Removing either half alone still passes at 0.95,
    because this particular message also says "regret to inform" and only needs
    one more +3 from anywhere. The pair earns its second half on the sentence
    that has no such support — see
    ``test_a_bare_proceeding_with_sentence_reaches_the_trusted_rung``, which is
    where the general/noun-anchored pairing is actually load-bearing. Measured,
    not assumed: the first draft of this docstring claimed either half alone
    would fail here, and running the mutation showed it does not.
    """
    result = CLASSIFIER.classify(PALANTIR_SUBJECT, PALANTIR_SNIPPET, PALANTIR_SENDER)

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= pipeline.AUTO_FILE_GATE, result.scores


def test_the_palantir_sentence_alone_is_a_rejection() -> None:
    """snippet ONLY. The subject is "Thank you from …", which helps nothing.

    Asserted at 0.90 rather than at the gate: the whole point of pairing the
    patterns is that a BODY with no subject support still reaches the rung the
    hybrid layer trusts, and only the pair does that.
    """
    result = CLASSIFIER.classify("", PALANTIR_SNIPPET, PALANTIR_SENDER)

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= 0.90, result.scores


@pytest.mark.parametrize(
    "body",
    [
        "We will not be proceeding with your candidacy at this time.",
        "We will not be continuing with your application at this time.",
    ],
)
def test_a_bare_proceeding_with_sentence_reaches_the_trusted_rung(body: str) -> None:
    """The decision sentence with NO "regret"/"unfortunately" to lean on.

    This is where the general/noun-anchored pair is load-bearing, and the reason
    the new patterns were added as a pair rather than singly — the same
    reasoning the infinitive already carries in `rules.py`. One strong body
    match is +3, which is the 0.70 rung: enough to reach the review queue, never
    enough to file. Two is +6, which is 0.90, the rung `hybrid.py` trusts.

    Mutation: dropping either half → fails at 0.70 (measured, both arms).
    """
    result = CLASSIFIER.classify("", body, None)

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= 0.90, result.scores


def test_the_palantir_acknowledgement_is_untouched() -> None:
    """The over-correction canary for THIS change, and it is a real message.

    Email 86 is the owner's Palantir *acknowledgement*, from the same Lever
    relay, filed `applied` at 0.95. A `proceeding with` pattern loose enough to
    reach it would turn every "reviewing your application" mail into a
    rejection — the #10 failure mode, where a narrow patch fixes one message and
    regresses the class it belongs to.
    """
    result = CLASSIFIER.classify(
        "Your application has been received!",
        "Hi Ayush, Thank you for submitting your application to be a Software "
        "Engineer, New Grad at Palantir. Our team is reviewing your application "
        "and will be in touch if we think you're a potential match",
        PALANTIR_SENDER,
    )

    assert result.category is EmailCategory.APPLIED, result.scores
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
