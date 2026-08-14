"""Issue #166 — the Together AI rejection that never reached the board.

The report says a message was skipped from the middle of a sync window that a
sync demonstrably covered, and names three suspects: the Gmail query, a page
boundary, and the shape of the incremental cursor. **None of them is the
mechanism.** The message was fetched. It was classified. It was then dropped
*after* classification, by the one path in ``pipeline.collect_review_items``
that leaves no application row, no review-queue entry, no counter and — below
``AUTO_FILE_GATE`` — not even a log line.

Why "absent from ``emails``" does not mean "never fetched"
---------------------------------------------------------
A scan reads up to ``_SYNC_DEFAULT_SCAN_TARGET`` (750) messages and persists
only the ones that roll up into an application or land in the review queue.
Production holds 51 ``emails`` rows against that target, so the table is a
record of what was *filed*, never of what was *read*. The issue's central
inference — "not misclassified: absent" — reads a filing table as a fetch log.

And the fetch is positively excluded by the issue's own timeline. The run at
2026-08-13 04:22 first persisted two messages received 2026-08-12 **03:36** and
**07:12**. A ``messages.list`` walk is newest-first, so anything that reached
03:36 had already passed 18:25. That run read the Together AI rejection and
filed nothing for it. (The same fact re-reads the issue's three-row table: a
07:12 message landing *after* a 23:35 one is not cursor coverage, it is a
re-list under rules that had changed — ``caf8e00``, 2026-08-12 20:35Z, landed
between the two runs. And the ``unreadable``-then-advance hole that hypotheses
2 and 3 describe was closed by ``522984d`` (#169) on 2026-08-13 20:51Z.)

What the classifier actually sees
---------------------------------
A cloud scan fetches ``format="metadata"``: Subject/From/Date plus Gmail's own
``snippet``, which is ~200 characters. An ATS rejection spends that budget on a
polite preamble, so whether the decision sentence is visible at all is decided
by how long the preamble happens to be. Both rejection snippets production
actually stored stop short of it — see ``VERKADA_SNIPPET`` and
``SUPERNOVA_SNIPPET`` below, 196 and 201 characters, both ending mid-preamble.

So the classifier reads the preamble and scores it as a *confirmation*. That is
survivable, barely: ``applied`` at 0.70 is under ``AUTO_FILE_GATE`` and at
exactly ``REVIEW_FLOOR``, so the message reaches the review queue and a human
can correct it. Every one of the three ``REJECTION`` rows on the real board got
there that way — all three carry ``user_corrected = true``, and rows 112/113
still carry ``suggested_category = 'APPLIED'``. **Applied has never once
auto-detected a rejection.**

Together AI fell through because of its SUBJECT
-----------------------------------------------
Verkada's rejection subject ("Thank you for your interest in Verkada, Ayush")
happens to contain an ``applied`` weak pattern, worth +2 in a subject. That +2
is the entire difference between 0.70 and 0.60 — between the review queue and
silence. Together AI's subject ("Important information about your application
to … @ Together AI") matches no pattern in any category, so the same preamble
scores one notch lower and the message produces nothing at all.

The hole is that knife-edge: an ATS rejection reaches the owner's queue only if
its subject line happens to contain a *confirmation* phrase.

The fix: the ATS floor
----------------------
**Mail from a known ATS sender is never silently dropped. If it scores below
the floor, it goes to the review queue.** ``pipeline.collect_review_items``
implements it; the boundary is what makes it safe:

- it only ever routes to the HUMAN QUEUE. It never files a row, never asserts a
  status, never writes a verdict — ``AUTO_FILE_GATE`` is untouched — so it
  cannot make the board confidently WRONG, which is the failure mode that ruled
  out the obvious alternative (adding Greenhouse's rejection subject template as
  a pattern scores this same message ``applied`` at +6 and would auto-file a
  rejection as APPLIED);
- it is bounded to LIFECYCLE categories from a CLOSED list of relay domains, so
  ``other``, ``follow_up``, non-canonical categories and every non-ATS sender
  behave exactly as before. Sections 3 and 4 assert both halves.

The classifier is deliberately NOT fixed. Recognising a rejection from 200
characters that contain no rejection is a hard problem, and
``test_the_classifier_still_scores_the_together_ai_rejection_under_the_floor``
pins that it remains unsolved — which is what stops this file passing for the
wrong reason.

Status of this file
-------------------
Characterisation plus the fix. This was #238's diagnosis, whose two
``xfail(strict=True)`` markers encoded the behaviour the product needed; both
are gone and the tests under them pass. The two assertions that read
``not _leaves_a_trace`` were rewritten rather than deleted: they now assert
which ROUTE a message takes into the queue, because after the fix "did it leave
a trace" is true for both halves of the pair and can no longer tell them apart.
"""
from __future__ import annotations

import pytest

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through the module singleton, matching
# tests/test_rules_classifier_rejection.py.
CLASSIFIER = RulesClassifier()

# Production's classifier is the RULES layer alone: hybrid.py short-circuits on
# ``settings.deployment == "cloud"`` before embeddings or SetFit are touched, so
# these are the verdicts Vercel produces. (That short-circuit also returns
# before hybrid's own OTHER -> NEEDS_REVIEW safety net at the bottom of
# ``classify``, which therefore never runs in production — a separate finding.)

GREENHOUSE = "no-reply@us.greenhouse-mail.io"
RIPPLING = "no-reply@ats.rippling.com"

# --------------------------------------------------------------------------
# The evidence: what production actually stored for two REAL rejections.
# Both are ``emails.body_snippet`` verbatim — ATS form-letter boilerplate, and
# already metadata this database holds.
# --------------------------------------------------------------------------

# emails.id 113 — Verkada via Greenhouse, 2026-08-13 17:30:11.
# 196 chars, and it ends on the word "Although", one clause short of the
# decision. suggested_category = 'APPLIED', user_corrected = true.
VERKADA_SUBJECT = "Thank you for your interest in Verkada, Ayush"
VERKADA_SNIPPET = (
    "Hi Ayush, Thank you for your interest in the Embedded Software Engineer, "
    "Access Control opportunity. It means a lot to us that you would consider "
    "joining our mission here at Verkada. Although your"
)

# emails.id 112 — Supernova Technology via Rippling, 2026-08-13 14:13:03.
# 201 chars. suggested_category = 'APPLIED', user_corrected = true.
SUPERNOVA_SUBJECT = "Thank You from Supernova Technology"
SUPERNOVA_SNIPPET = (
    "Hi Ayush, Thank you for taking the time to apply to the Junior Software "
    "Engineer role here at Supernova Technology. Please note, we have received "
    "many applications for this role and the search has been"
)

# --------------------------------------------------------------------------
# The message from #166. Subject and decision sentence are quoted verbatim in
# the public issue; the Gmail snippet is not recorded anywhere, so it is
# modelled on the two real ones above rather than invented.
# --------------------------------------------------------------------------
TOGETHER_SUBJECT = (
    "Important information about your application to "
    "Systems Research Engineer, GPU Programming @ Together AI"
)
# Shape A — the preamble runs past the snippet cut, exactly like Verkada's.
TOGETHER_SNIPPET_PREAMBLE = (
    "Hi Ayush, Thank you for your interest in the Systems Research Engineer, "
    "GPU Programming opportunity. It means a lot to us that you would consider "
    "joining our mission here at Together AI. Although your"
)
# Shape B — the decision sentence IS inside the snippet (issue #166 quotes it).
# The best case, and it is still not good enough.
TOGETHER_SNIPPET_WITH_DECISION = (
    "Hi Ayush, Thank you for your interest in Together AI. Unfortunately, we "
    "decided to move forward with other candidates whose experience more "
    "closely aligns with our team's needs."
)


def _item(subject: str, snippet: str, sender: str, message_id: str):
    """Classify like a scan does, then wrap the verdict as the pipeline sees it."""
    result = CLASSIFIER.classify(subject, snippet, sender)
    return result, pipeline.PipelineItem(
        message_id=message_id,
        category=result.category.value,
        sender_email=sender,
        subject=subject,
        sender_name=None,
        received_at=None,
        confidence=result.confidence,
        thread_id=message_id,
        snippet=snippet,
    )


def _leaves_a_trace(item) -> bool:
    """Would this message produce ANY row — an application, or a queue entry?

    These two calls are the whole of the pipeline's output surface. A message
    that satisfies neither is gone: ``collect_review_items`` returns without
    logging whenever the verdict is under ``AUTO_FILE_GATE``.
    """
    return bool(pipeline.roll_up_applications([item])) or bool(
        pipeline.collect_review_items([item])
    )


def _qualifies_only_by_the_ats_floor(item) -> bool:
    """Did the ATS floor — and nothing else — put this in the queue?

    Reads the route, not the outcome. An item is floor-only when it reaches the
    queue while sitting UNDER ``REVIEW_FLOOR``: every other road into
    ``collect_review_items`` requires either an explicit ``needs_review`` verdict
    or a lifecycle verdict at/above the floor.
    """
    return (
        item.confidence < pipeline.REVIEW_FLOOR
        and item.category != "needs_review"
        and bool(pipeline.collect_review_items([item]))
    )


# ===========================================================================
# 1. The Gmail snippet structurally cannot carry the decision sentence.
# ===========================================================================


@pytest.mark.parametrize(
    "snippet", [VERKADA_SNIPPET, SUPERNOVA_SNIPPET], ids=["verkada", "supernova"]
)
def test_real_ats_rejection_snippets_stop_before_the_decision(snippet: str) -> None:
    """Both stored rejection snippets are preamble only.

    Not a claim about Gmail's exact truncation rule — a claim about the two
    samples this product actually holds. It is why the classifier is being
    asked to recognise a rejection from text that contains no rejection.
    """
    assert len(snippet) <= 205, "snippet is longer than Gmail's ~200-char budget"
    lowered = snippet.lower()
    assert "unfortunately" not in lowered
    assert "not been selected" not in lowered
    assert "move forward with other" not in lowered


@pytest.mark.parametrize(
    ("subject", "snippet", "sender"),
    [
        (VERKADA_SUBJECT, VERKADA_SNIPPET, GREENHOUSE),
        (SUPERNOVA_SUBJECT, SUPERNOVA_SNIPPET, RIPPLING),
    ],
    ids=["verkada", "supernova"],
)
def test_real_rejections_are_classified_as_confirmations(
    subject: str, snippet: str, sender: str
) -> None:
    """Characterisation: production called both of these ``applied``.

    This is the assertion that validates the whole file as an instrument — it
    reproduces ``emails.suggested_category = 'APPLIED'`` as stored for rows 112
    and 113, which is what Ayush then corrected by hand.
    """
    result, item = _item(subject, snippet, sender, "probe")

    assert result.category is EmailCategory.APPLIED, result.scores
    # At REVIEW_FLOOR and under AUTO_FILE_GATE: the review queue, which is the
    # only reason these two were recoverable at all.
    assert result.confidence >= pipeline.REVIEW_FLOOR
    assert result.confidence < pipeline.AUTO_FILE_GATE
    assert _leaves_a_trace(item)


# ===========================================================================
# 2. The mechanism: Together AI's subject drops it under the review floor.
# ===========================================================================


def test_the_together_ai_subject_scores_nothing_anywhere() -> None:
    """"Important information about your application to X @ Y" matches no rule.

    Greenhouse's rejection subject template, and it is invisible to every
    category. With no body it is ``other`` — the state that produces silence.
    """
    result = CLASSIFIER.classify(TOGETHER_SUBJECT, "", GREENHOUSE)

    assert result.category is EmailCategory.OTHER, result.scores
    assert not any(score > 0 for score in result.scores.values()), result.scores


def test_the_classifier_still_scores_the_together_ai_rejection_under_the_floor() -> None:
    """The CLASSIFIER is not fixed, and this pins that it is not.

    The diagnosis is unchanged: on the same preamble shape that Verkada's
    rejection carried, Together AI's subject leaves the message under
    ``REVIEW_FLOOR``. Recognising a rejection from 200 characters that contain
    no rejection is a hard problem and this change does not pretend to solve it.

    Keeping this assertion is what stops the file going green for the wrong
    reason. If a later edit lifts this message over the floor by accident — the
    +0.05 ATS bonus is exactly the kind of thing that could — the fix below
    would still pass while no longer testing the floor at all.
    """
    result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "19ff7393d56eccfb"
    )

    assert result.confidence < pipeline.REVIEW_FLOOR, result.scores
    # Below the gate too, so the drop it used to take was also silent: the
    # pipeline logs a dropped verdict only at/above AUTO_FILE_GATE.
    assert result.confidence < pipeline.AUTO_FILE_GATE
    # It no longer vanishes — but by the ATS floor, not by classification.
    assert _qualifies_only_by_the_ats_floor(item)


def test_the_subject_is_the_whole_difference() -> None:
    """The positive control, and it still discriminates after the fix.

    Before: the same body under Verkada's subject left a row and under Together
    AI's did not. After: BOTH leave a row, so "did it leave a trace" no longer
    tells the two apart — and a control that cannot tell them apart is the
    "identical for the wrong reason" failure this pair exists to catch.

    So it now asserts the ROUTE rather than the outcome. Verkada's subject earns
    its place in the queue on the classifier's own confidence; Together AI's
    reaches the same queue only because the floor caught it. If a later change
    ever makes the two arrive by the same route, this goes red.
    """
    _lost, lost_item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "lost"
    )
    kept_result, kept_item = _item(
        VERKADA_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "kept"
    )

    assert _leaves_a_trace(lost_item) and _leaves_a_trace(kept_item)
    # Together AI's subject: below the floor, saved by the floor alone.
    assert _qualifies_only_by_the_ats_floor(lost_item)
    # Verkada's subject: at/above the floor, so it needs no help.
    assert kept_result.category is EmailCategory.APPLIED, kept_result.scores
    assert kept_result.confidence >= pipeline.REVIEW_FLOOR
    assert not _qualifies_only_by_the_ats_floor(kept_item)


def test_even_the_visible_decision_sentence_cannot_reach_the_board() -> None:
    """Best case — the sentence #166 quotes IS in the snippet — is still 0.70.

    One strong body match scores 3, and the confidence ladder needs 6 for 0.90.
    So a rejection whose body states the decision once, unambiguously, can only
    ever reach the review queue. Ayush's board cannot be corrected by ingestion
    alone, however well the fetch works.
    """
    result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_WITH_DECISION, GREENHOUSE, "best-case"
    )

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence < pipeline.AUTO_FILE_GATE, result.scores
    assert pipeline._qualifies_for_hard_row(item) is None
    assert pipeline.collect_review_items([item]), "review queue at best"
    assert not pipeline.roll_up_applications([item]), "never the board"


@pytest.mark.parametrize("sender", [GREENHOUSE, RIPPLING], ids=["greenhouse", "rippling"])
def test_greenhouse_and_rippling_are_recognised_as_ats_senders(sender: str) -> None:
    """Greenhouse is the most common ATS in the production corpus and, until
    this change, had never once received the +0.05 ATS confidence bonus.

    Asserted through ``is_ats_sender`` rather than by re-implementing its match,
    because that function is now what BOTH call sites read — the classifier's
    bonus and ``collect_review_items``' floor. (The match was an unanchored
    substring walk until #260; section 5 below is why it no longer is.)
    """
    from jobtracker.classifier.rules import is_ats_sender

    assert is_ats_sender(sender), sender


def test_the_ats_bonus_moves_no_message_across_the_auto_file_gate() -> None:
    """The reason the domain fix was not a drive-by: +0.05 can cross the gate.

    The bonus is applied to the confidence LADDER's output, and the ladder's
    rungs are 0.60 / 0.70 / 0.80 / 0.90 / 0.95. Only the 0.80 rung is dangerous:
    0.80 + 0.05 is exactly ``AUTO_FILE_GATE``, so a Greenhouse or Rippling
    message that scores 0.80 would begin auto-filing a hard status where it used
    to go to the review queue.

    Production says no stored Greenhouse/Rippling message sits on that rung —
    they are at 0.70 (1 + 1), 0.90 (11 + 1) and 0.95 (3) — so nothing on the
    real board changes filing behaviour. This pins the shapes that matter here:
    the three real messages this file models all stay under the gate.
    """
    for subject, snippet, sender in (
        (VERKADA_SUBJECT, VERKADA_SNIPPET, GREENHOUSE),
        (SUPERNOVA_SUBJECT, SUPERNOVA_SNIPPET, RIPPLING),
        (TOGETHER_SUBJECT, TOGETHER_SNIPPET_WITH_DECISION, GREENHOUSE),
    ):
        result = CLASSIFIER.classify(subject, snippet, sender)
        assert result.confidence == pytest.approx(0.75), (subject, result.scores)
        assert result.confidence < pipeline.AUTO_FILE_GATE


# ===========================================================================
# 3. The fix: the ATS floor. This was #238's strict xfail; the marker is gone.
# ===========================================================================


def test_an_ats_application_message_never_vanishes_silently() -> None:
    """Mail from a known ATS, about an application, leaves *something*.

    Not "is classified correctly" — that is a hard problem on 200 characters of
    preamble, and ``test_the_classifier_still_scores_...`` above pins that it is
    still unsolved. Only that it does not disappear. The review queue is the
    product's designed home for "we cannot tell", and it is what made every
    other rejection on this board recoverable.

    This is #238's ``xfail(strict=True)`` with the marker removed.
    """
    _result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "19ff7393d56eccfb"
    )

    assert _leaves_a_trace(item)


def test_the_floor_only_ever_routes_to_the_queue_never_to_the_board() -> None:
    """The boundary that makes the floor safe, asserted rather than assumed.

    A floored message must produce a review-queue entry and NOTHING else: no
    application row, no status, no verdict. ``AUTO_FILE_GATE`` is what enforces
    that and the floor does not touch it — but "does not touch it" is a claim
    about code, and this is the claim about behaviour.

    The queue entry's committed state is ``needs_review`` at persist time
    (``applications._persist_review_items*`` hardcode it); the classifier's guess
    rides along as a PROPOSAL in ``suggested_category``. So the floor never
    forges a human decision, which is what ``classified_as`` is for.
    """
    _result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "19ff7393d56eccfb"
    )

    assert pipeline.roll_up_applications([item]) == [], "the floor must not file"
    assert pipeline._qualifies_for_hard_row(item) is None

    review = pipeline.collect_review_items([item])
    assert [r.message_id for r in review] == ["19ff7393d56eccfb"]
    # The proposal is carried, not committed — and it is the classifier's own
    # (wrong) guess, exactly as it is for the two rejections Ayush corrected.
    assert review[0].category == "applied"
    assert review[0].confidence < pipeline.REVIEW_FLOOR


# ===========================================================================
# 4. The negative controls. A floor that catches everything is not a fix.
# ===========================================================================


def test_ordinary_non_ats_mail_below_the_floor_is_still_dropped() -> None:
    """The queue must not fill with mail from senders that are not ATS relays.

    Same category, same confidence, same subject and body as the message the
    floor rescues — only the sender differs. That is the whole point: the floor
    is keyed on the sender being a known transactional relay, and on nothing
    else. If this ever goes green-by-flooding, the fix has replaced a silent
    failure with an unusable queue.
    """
    for sender in (
        "recruiting@acme.com",  # a company's own careers address
        "hiring-manager@northstar.dev",  # a person at the employer
        "newsletter@digest.example",  # ordinary inbox noise
        "no-reply@notifications.linkedin.com",  # a job board, not an ATS
    ):
        result, item = _item(
            TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, sender, f"neg-{sender}"
        )
        assert result.confidence < pipeline.REVIEW_FLOOR, (sender, result.scores)
        assert not _leaves_a_trace(item), f"{sender} should still be dropped"


def test_the_floor_does_not_swallow_the_three_shapes_that_must_stay_dropped() -> None:
    """Three ATS-sender shapes the floor deliberately does NOT rescue.

    Each is dropped for its own reason, and each is the reason the floor is
    scoped to lifecycle categories rather than to the sender alone:

    - ``other`` — what a classifier miss and ATS job-alert noise both produce.
      Queueing it would put every promotional mail an ATS relays in front of the
      user, which is the flood this fix must not cause.
    - ``follow_up`` — excluded from filing AND from the queue by design, above
      the floor as well as below it. The floor must not quietly reverse that.
    - a category outside the canonical vocabulary — a BUG, and the pipeline's
      contract is that it is logged rather than turned into a queue entry.
    """
    for category, confidence in (
        ("other", 0.0),
        ("other", 0.5),
        ("follow_up", 0.90),
        ("rejected", 0.95),  # note: not "rejection" — non-canonical
    ):
        item = pipeline.PipelineItem(
            message_id=f"drop-{category}-{confidence}",
            category=category,
            sender_email=GREENHOUSE,
            subject=TOGETHER_SUBJECT,
            sender_name=None,
            received_at=None,
            confidence=confidence,
            thread_id=None,
            snippet=TOGETHER_SNIPPET_PREAMBLE,
        )
        assert pipeline.collect_review_items([item]) == [], (category, confidence)


# ===========================================================================
# 5. Issue #260 — the relay list is a list of DOMAINS, not of substrings.
#
# ``is_ats_sender`` matched with ``ats in domain``: unanchored containment, so
# an ATS name anywhere in the host counted. Anyone who can register a domain
# could therefore put themselves on a closed list — and since #252 that list
# decides ROUTING (the floor above), not merely a +0.05 nudge.
#
# The tests below are deliberately of two kinds and it matters which is which:
#
#   - ``..._is_not_an_ats_sender`` / ``..._cannot_reach_the_review_queue`` /
#     ``..._earns_no_confidence_bonus`` FAIL on the pre-#260 implementation.
#     They are the proof the defect was real.
#   - ``..._are_still_ats_senders`` / ``..._load_bearing...`` /
#     ``..._bare_rippling...`` pass on the old code too. They are regression
#     guards for the fix, not evidence of the bug, and must not be read as it.
# ===========================================================================

# Hosts that contain a listed ATS name but are NOT that ATS. Every one is
# registrable by a stranger; the third works through ``hire.com``, the shortest
# entry on the list, which is why a short generic entry is the sharpest edge.
LOOKALIKE_SENDERS = [
    "no-reply@greenhouse.io.mailgun.net",  # ATS name as the LEFT label
    "careers@notlever.co.example.com",  # ATS name in the MIDDLE, glued left
    "hr@sohire.comcast.net",  # "hire.com" straddling a label boundary
    "jobs@xgreenhouse.io",  # one character short of the real relay
    "noreply@workday.com.phish.example",  # the classic suffix-looking prefix
]

# The forms that legitimately match and must keep matching: the bare domain,
# and real subdomains production actually sees.
REAL_RELAY_SENDERS = [
    "no-reply@greenhouse.io",
    "no-reply@mail.greenhouse.io",
    "no-reply@us.greenhouse-mail.io",
    "no-reply@us-east.smartrecruiters.com",
    "no-reply@ats.rippling.com",
    "no-reply@mail.ats.rippling.com",
    "no-reply@lever.co",
    "hpe@myworkday.com",
]


@pytest.mark.parametrize("sender", LOOKALIKE_SENDERS)
def test_a_lookalike_domain_is_not_an_ats_sender(sender: str) -> None:
    """FAILS before #260. Containment let a stranger's domain onto the list.

    ``"greenhouse.io" in "greenhouse.io.mailgun.net"`` is True, and so is
    ``"hire.com" in "sohire.comcast.net"``. Neither host is operated by an ATS.
    A closed list whose membership test any registrar can satisfy is not closed.
    """
    from jobtracker.classifier.rules import is_ats_sender

    assert not is_ats_sender(sender), sender


@pytest.mark.parametrize("sender", REAL_RELAY_SENDERS)
def test_the_real_relay_forms_are_still_ats_senders(sender: str) -> None:
    """Passes on the OLD implementation too — a regression guard, not proof.

    Anchoring is only correct if it keeps every sender that legitimately matched.
    Checked against every e-mail address in the tracked tree (357 distinct
    domains, including the three committed evaluation corpora): the anchored form
    and the containment form disagree on none of them.
    """
    from jobtracker.classifier.rules import is_ats_sender

    assert is_ats_sender(sender), sender


def test_two_list_entries_became_load_bearing_under_anchoring() -> None:
    """Passes on the OLD implementation too, and exists to stop a "cleanup".

    Under containment ``myworkday.com`` was redundant with ``workday.com`` and
    ``greenhouse-mail.io`` looked like a variant of ``greenhouse.io``; a tidying
    pass could have deleted either without a test noticing. Under anchoring
    neither is redundant — ``myworkday.com`` does not end in ``.workday.com`` —
    and deleting one silently stops recognising a relay production really uses
    (``us.greenhouse-mail.io`` is the sender on Ayush's own Greenhouse mail).
    """
    from jobtracker.classifier.rules import ATS_DOMAINS, is_ats_sender

    assert "myworkday.com" in ATS_DOMAINS and "workday.com" in ATS_DOMAINS
    assert "greenhouse-mail.io" in ATS_DOMAINS and "greenhouse.io" in ATS_DOMAINS
    assert is_ats_sender("hpe@myworkday.com")
    assert is_ats_sender("no-reply@us.greenhouse-mail.io")


def test_bare_rippling_com_is_still_not_an_ats_sender() -> None:
    """Passes on the OLD implementation too. Anchoring must not widen the list.

    ``ats.rippling.com`` is listed as a full host on purpose: Rippling is a
    payroll and HR product as well as an ATS, and a bare ``rippling.com`` would
    sweep in payroll mail. Anchoring is a NARROWING change everywhere, and this
    pins that it did not accidentally promote the host to a registrable domain.
    """
    from jobtracker.classifier.rules import is_ats_sender

    assert not is_ats_sender("payroll@rippling.com")
    assert is_ats_sender("no-reply@ats.rippling.com")


def test_a_lookalike_sender_cannot_reach_the_review_queue() -> None:
    """FAILS before #260. The consequence, at the call site that routes.

    The exact message the ATS floor is FOR — Together AI's shape, ``applied`` at
    0.60, under ``REVIEW_FLOOR`` — but relayed by a host that merely contains an
    ATS name. Before #260 the floor caught it and it landed in Ayush's queue;
    the queue is a human's attention, and filling it from a domain anyone can
    register is how a safety net becomes spam.
    """
    for sender in LOOKALIKE_SENDERS:
        result, item = _item(
            TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, sender, f"spoof-{sender}"
        )
        assert result.confidence < pipeline.REVIEW_FLOOR, (sender, result.scores)
        assert pipeline.collect_review_items([item]) == [], sender
        assert not _leaves_a_trace(item), sender


def test_a_lookalike_sender_earns_no_confidence_bonus() -> None:
    """FAILS before #260, and this is the sharpest edge of the defect.

    The +0.05 bonus is added to the ladder's OUTPUT, and 0.80 + 0.05 is exactly
    ``AUTO_FILE_GATE``. So a lookalike domain does not only reach the queue: on
    the 0.80 rung it hands a message the confidence at which the pipeline may
    assert a hard status. The subject/body below is a real row from
    ``data/evaluation/classifier_eval_v*.jsonl`` — the only lifecycle message in
    the three corpora that lands on that rung — so this is not a shape invented
    to make the point.

    Asserted at the confidence, which is where the defect is. Filing also needs
    an employer, so this particular fixture would not have filed; a message that
    names one would.
    """
    subject = "Next step: interview"
    body = "We would like to invite you to interview for this role."

    unsigned = CLASSIFIER.classify(subject, body, None)
    assert unsigned.confidence == pytest.approx(0.80), unsigned.scores
    assert unsigned.confidence < pipeline.AUTO_FILE_GATE

    # The real relay earns the bonus, and that lands ON the gate. This is the
    # documented, intended behaviour — it is what makes the lookalike dangerous.
    genuine = CLASSIFIER.classify(subject, body, GREENHOUSE)
    assert genuine.confidence == pytest.approx(0.85), genuine.scores
    assert genuine.confidence >= pipeline.AUTO_FILE_GATE

    for sender in LOOKALIKE_SENDERS:
        spoofed = CLASSIFIER.classify(subject, body, sender)
        assert spoofed.confidence == pytest.approx(0.80), (sender, spoofed.scores)
        assert spoofed.confidence < pipeline.AUTO_FILE_GATE, sender
