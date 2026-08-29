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
A cloud scan USED to fetch ``format="metadata"``: Subject/From/Date plus
Gmail's own ``snippet``, which is ~200 characters. An ATS rejection spends that
budget on a polite preamble, so whether the decision sentence was visible at all
was decided by how long the preamble happened to be. Both rejection snippets
production actually stored stop short of it — see ``VERKADA_SNIPPET`` and
``SUPERNOVA_SNIPPET`` below, 196 and 201 characters, both ending mid-preamble.

That is why the fetch is now ``format="full"``: the body is read to classify
and discarded, never stored (``test_body_is_never_persisted.py``). The snippets
below are kept as fixtures ON PURPOSE — they are what the classifier sees when
a message yields no body text, so the behaviour they pin is still reachable and
still worth pinning.

So the classifier reads the preamble and scores it as a *confirmation*. That is
survivable, barely: ``applied`` at 0.70 is under ``AUTO_FILE_GATE`` and at
exactly ``REVIEW_FLOOR``, so the message reaches the review queue and a human
can correct it. All three ``REJECTION`` rows on the real board carry
``user_corrected = true``, and rows 112/113 still carry
``suggested_category = 'APPLIED'``.

This paragraph used to end "**Applied has never once auto-detected a
rejection.**" That inference does not follow from the flag it was read off, and
#311 is why: ``user_corrected`` was written ``True`` whether the human AGREED
with the machine or overruled it, so a flagged row says only that somebody
looked. The Palantir row (114) is flagged and is an agreement — the classifier
returned ``rejection`` at 0.75, the right category, held under the gate. Rows
112/113 keep their ``suggested_category = 'APPLIED'`` and remain real
misreads; that half stands. What the flag could never support is the "never
once" clause, and it has been removed rather than softened.

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


def test_the_visible_decision_sentence_now_reaches_the_board() -> None:
    """Best case — the sentence #166 quotes IS in the snippet — and it FILES.

    This test used to be characterisation of a defect, named
    ``..._cannot_reach_the_board`` and asserting 0.70: one strong body match is
    +3, the ladder needs +6 for the 0.90 rung, so a rejection stating its
    decision once could only ever reach the review queue. "Ayush's board cannot
    be corrected by ingestion alone, however well the fetch works" is what it
    said, and it was true.

    #316 removed the cause. "we decided to move forward with other candidates"
    now matches a general pattern AND its noun-anchored twin, which is +6 from
    the body alone — 0.90 on the ladder, before any ATS bonus. So the real
    Together AI message this file is about files a ``rejected`` row instead of
    queueing for a human, which is the whole point of the change.

    The assertion is INVERTED rather than deleted, and deliberately so: this is
    the message #166 is named for, and if a later change puts it back under the
    gate that is a regression worth a red test rather than a silent return to
    the old behaviour.

    AND IT NOW FILES UNDER THE RIGHT COMPANY — #325, which is what the last
    assertion is really for. Until then this line read ``Research Engineer``
    and was pinned as characterisation of a defect: ``_EMPLOYER_ANCHORED`` read
    "…your application **to** Systems Research Engineer, GPU Programming @
    Together AI" as naming an employer, and ``_CORP_TAIL`` ate "Systems" on the
    way out, leaving a job title where the company belongs.

    The fix is an ORDERING one. ``pipeline._EMPLOYER_AT_SIGN`` matches the
    trailing "@ <Company>" and is tried BEFORE the anchored pattern, for ATS
    mail only. Two patterns both fire on this subject and they disagree; the
    at-sign wins because "<title> @ <company>" means one thing, while
    "application to X" names a company only when the subject did not already
    name a role. Measured over all 52 stored production emails first: not one
    of them contains an at-sign, so no filed row moved and nothing merged or
    split. This message was never among them — it is the one #166 is named for
    precisely because it never reached the board.

    What #316 changed is only that the defect was REACHABLE for this message at
    all. Below the gate it never got as far as naming an employer.
    ``_qualifies_for_hard_row`` guards the "unnameable employer" case —
    ``resolve_employer`` returns None and no row is created — so this was a
    wrong name rather than a missing guard, and the guard was working.

    The assertion is kept, not deleted, and is now a REGRESSION test in both
    directions: the message must still file (that is #316) and it must file
    against Together AI (that is #325). Either one going back costs a red here.
    """
    result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_WITH_DECISION, GREENHOUSE, "best-case"
    )

    assert result.category is EmailCategory.REJECTION, result.scores
    assert result.confidence >= pipeline.AUTO_FILE_GATE, result.scores
    # And it is the LADDER that clears the gate, not the +0.05 ATS bonus riding
    # on top of a 0.80 — see the next test, whose invariant this must not break.
    assert (
        CLASSIFIER.classify(
            TOGETHER_SUBJECT, TOGETHER_SNIPPET_WITH_DECISION, None
        ).confidence
        >= pipeline.AUTO_FILE_GATE
    )
    assert pipeline._qualifies_for_hard_row(item) is not None
    # The employer, not the job title it is advertised under (#325).
    assert [
        (r.company_display, r.status) for r in pipeline.roll_up_applications([item])
    ] == [("Together AI", "rejected")]


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
    real board changes filing behaviour.

    Stated as the LADDER value, not the delivered one, since #316. Together AI's
    decision snippet now scores 0.90 on the ladder and 0.95 delivered, so
    asserting "delivered is 0.75" would have made this test red for a reason
    that has nothing to do with what it is about. What it is about is the rung
    the bonus is added TO: no message here sits on 0.80, so +0.05 never carries
    anything over 0.85 that was not already there. That is the invariant, and it
    now holds for a message on either side of the gate.
    """
    for subject, snippet, sender in (
        (VERKADA_SUBJECT, VERKADA_SNIPPET, GREENHOUSE),
        (SUPERNOVA_SUBJECT, SUPERNOVA_SNIPPET, RIPPLING),
        (TOGETHER_SUBJECT, TOGETHER_SNIPPET_WITH_DECISION, GREENHOUSE),
    ):
        ladder = CLASSIFIER.classify(subject, snippet, None)
        delivered = CLASSIFIER.classify(subject, snippet, sender)
        # The dangerous rung, and nothing is on it.
        assert ladder.confidence != pytest.approx(0.80), (subject, ladder.scores)
        # So the bonus never decides the gate: both readings agree about it.
        assert (ladder.confidence >= pipeline.AUTO_FILE_GATE) == (
            delivered.confidence >= pipeline.AUTO_FILE_GATE
        ), (subject, ladder.confidence, delivered.confidence)

    # And the two messages that DO stay under the gate still do, at the value
    # this file was written about.
    for subject, snippet, sender in (
        (VERKADA_SUBJECT, VERKADA_SNIPPET, GREENHOUSE),
        (SUPERNOVA_SUBJECT, SUPERNOVA_SNIPPET, RIPPLING),
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


def test_the_floor_does_not_swallow_the_shapes_that_must_stay_dropped() -> None:
    """The shapes the floor deliberately does NOT rescue.

    Each is dropped for its own reason, and each is the reason the floor is
    scoped to lifecycle categories rather than to the sender alone:

    - a category outside the canonical vocabulary — a BUG, and the pipeline's
      contract is that it is logged rather than turned into a queue entry.
      Queueing it would hide the bug behind a plausible-looking row. That holds
      whoever sent it, so it is asserted on the relay AND off it.
    - ``follow_up`` — the user's own chasing mail, and queueing it asks them to
      classify themselves. THE SENDER IS NOW PART OF THAT SENTENCE (#458): the
      premise is about mail the reader SENT, so it is asserted here only for
      senders that are not relays. A known ATS does not carry the reader's own
      mail, and on that sender the same verdict is a category error whose
      silent drop cost 11 real rejections; see
      ``test_relayed_follow_up_is_not_your_own.py``.

    ``other`` USED TO BE ON THIS LIST and is not any more. That is #447: the
    reason given here was that queueing it "would put every promotional mail an
    ATS relays in front of the user", and the message this very test uses as its
    payload is a REAL Together AI rejection — one of the 610 that reached no
    card, no queue and no counter. The flood was the right worry and the wrong
    conclusion; the fix was to find a signal narrower than the sender rather
    than to keep dropping. ``other`` now has its own pair of cases below.

    This test caught a genuine defect in the #447 change, which is why the
    survivors stay in a loop of their own: its first draft read
    ``is_lifecycle or references(...)`` and reversed BOTH of these as a side
    effect.
    """
    for category, confidence, sender in (
        # Non-canonical, and it stays a logged bug on either kind of sender.
        ("rejected", 0.95, GREENHOUSE),  # note: not "rejection" — non-canonical
        ("rejected", 0.95, "recruiting@acme.com"),
        # The reader's own chasing mail, which is what ``follow_up`` means.
        # Both a company address and a plain one, at both ends of the gate.
        ("follow_up", 0.90, "recruiting@acme.com"),
        ("follow_up", 0.70, "ayush@example.com"),
    ):
        item = pipeline.PipelineItem(
            message_id=f"drop-{category}-{confidence}-{sender}",
            category=category,
            sender_email=sender,
            subject=TOGETHER_SUBJECT,
            sender_name=None,
            received_at=None,
            confidence=confidence,
            thread_id=None,
            snippet=TOGETHER_SNIPPET_PREAMBLE,
        )
        assert pipeline.collect_review_items([item]) == [], (
            category,
            confidence,
            sender,
        )


def test_an_other_verdict_is_queued_only_when_it_speaks_about_your_application() -> None:
    """The #447 floor, and the control that stops it becoming "queue the sender".

    Both messages are ``other`` at the same confidence, from the same real
    Greenhouse relay, below every gate. The ONLY difference is whether the text
    speaks about an application the reader made. One is a real Together AI
    rejection whose verdict sits past the snippet cut; the other is a job-alert
    digest of the kind an ATS relays constantly.

    These two are each other's control and neither means anything alone. The
    first alone passes for a floor that queues everything an ATS sends — the
    widening this module declined to make. The second alone passes for the
    pre-#447 code, which dropped both.
    """

    def item(message_id: str, subject: str, snippet: str) -> pipeline.PipelineItem:
        return pipeline.PipelineItem(
            message_id=message_id,
            category="other",
            sender_email=GREENHOUSE,
            subject=subject,
            sender_name=None,
            received_at=None,
            confidence=0.5,
            thread_id=None,
            snippet=snippet,
        )

    rejection = item("real-rejection", TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE)
    queued = pipeline.collect_review_items([rejection])
    assert [r.message_id for r in queued] == ["real-rejection"], (
        "a REAL rejection, relayed by a real ATS, whose verdict sits past "
        "Gmail's snippet cut. Before #447 this reached no card, no queue entry "
        "and no counter — indistinguishable from a mailbox that never received "
        "it. It must reach a person."
    )
    assert queued[0].company_display == "Together AI", (
        "queued with no employer against it is a row nobody can act on, which "
        "defeats the point of queueing it."
    )

    alert = item(
        "job-alert",
        "New roles at Together AI this week",
        "Hi Ayush, here are the latest openings at Together AI: Systems "
        "Research Engineer, and several more on our careers page. Set up an "
        "alert to hear about new roles first.",
    )
    assert pipeline.collect_review_items([alert]) == [], (
        "an ATS job alert is not about any application of the user's and must "
        "still drop. If this queues, the floor has widened to the SENDER and "
        "the guarantee above is worthless."
    )


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

    # Written as a set subset rather than ``"myworkday.com" in ATS_DOMAINS``,
    # which is LIST MEMBERSHIP and not substring containment — but CodeQL's
    # ``py/incomplete-url-substring-sanitization`` cannot tell Python's two
    # ``in`` operators apart and read the membership test as the very defect
    # this section fixes, raising four high-severity false positives. Suppressing
    # the rule here would be worse than rewriting: an inline dismissal on this
    # exact file is what a future reader would most reasonably trust, and it
    # would also mask a genuine reintroduction of the substring bug. Do not
    # "simplify" this back to ``in``.
    assert {"myworkday.com", "workday.com"}.issubset(ATS_DOMAINS)
    assert {"greenhouse-mail.io", "greenhouse.io"}.issubset(ATS_DOMAINS)
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


def test_the_argument_is_a_parsed_address_and_never_a_raw_from_header() -> None:
    """The one input where anchoring could have been a REGRESSION, pinned.

    Containment tolerated the trailing ``>`` of a display-name header —
    ``"greenhouse-mail.io" in "us.greenhouse-mail.io>"`` is True — and anchoring
    does not. If a raw ``From`` value could reach ``is_ats_sender``, #260 would
    have dropped real Greenhouse and Rippling mail out of the floor.

    It cannot: every path that produces a ``sender_email`` parses the header
    first with ``email.utils.parseaddr`` — ``cloud/gmail_client.py`` (the cloud
    scan that feeds ``collect_review_items``), ``email_clients/gmail.py`` and
    ``email_clients/icloud.py``. This asserts the contract at the boundary
    rather than trusting the three call sites to keep it, using the two relay
    headers production actually receives.

    Half of this — that the unparsed form does not match — behaves differently
    on the old code. That is a shape which cannot reach the function, so it is
    recorded here as the contract, not counted as evidence of the defect.
    """
    from email.utils import parseaddr

    from jobtracker.classifier.rules import is_ats_sender

    for header in (
        "Verkada Recruiting <no-reply@us.greenhouse-mail.io>",
        '"Supernova Technology, Inc." <no-reply@ats.rippling.com>',
    ):
        _name, address = parseaddr(header)
        assert "<" not in address and ">" not in address, address
        assert is_ats_sender(address), address
        # And the unparsed header is not an address, so it is not a sender.
        assert not is_ats_sender(header), header


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


# ===========================================================================
# 7. A BOUND MUST NOT ASSUME WHAT SITS IN THE GAP — issue #466
# ===========================================================================
#
# Three patterns bounded a span that holds a JOB TITLE, and each bound encoded
# an assumption about titles that real ones break. They are tested together
# because they are one defect wearing three costumes, and apart because each
# has its own control.
#
# Every title below is a real shape from the owner's mailbox, with employer
# sub-brands and product names replaced by invented ones of the same length —
# the rule `tests/corpus_independent/observed.py` follows.

#: The longest real title measured, 2026-08-22. It carries a comma, a
#: parenthesis and a colon, and it is 72 characters.
LONG_TITLE = "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)"


def test_a_title_with_punctuation_still_reads_as_an_application_reference() -> None:
    """`[\\w,\\ \\-/]` held no `(`, `)`, `:` or `#`, and real titles carry all four.

    This is what the #447 floor rides on, so a title the class could not span
    meant a message about a real application reached no card, no queue and no
    counter.
    """
    for title in (LONG_TITLE, "Software Engineer, C#",
                  "Software Engineer, Agentic AI Harness & Quality - Talonflow"):
        text = f"Thank you for taking the time to apply to the {title} role here at Northwind."
        assert pipeline.references_an_application("Thank You from Northwind", text), title


def test_a_job_advert_is_still_not_a_reference_to_your_application() -> None:
    """The control on the widening, and the reason it is a CLAUSE bound.

    Widening what counts as "about an application you made" widens what reaches
    the review queue, so the failure mode is a queue full of recruiter mail.
    None of these names an application the reader made.
    """
    for text in (
        "Apply to the roles below before they close — 14 new openings this week.",
        "Ready to apply? Browse the position listings on our careers page.",
        "Apply to a company you love. New roles added daily.",
        "Thousands apply to the biggest names in tech every day; here is how to stand out.",
        "You can apply to the newsletter settings page to change how often we email you.",
    ):
        assert not pipeline.references_an_application("New roles for you", text), text


def test_the_employers_possessive_is_not_part_of_the_job_title() -> None:
    """"applying to <Employer>'s <Title> position" — the capture took both.

    The role token IS the application identity, so a confirmation that said
    "<Employer>'s Frontend Engineer" and a rejection that said "Frontend
    Engineer" were two applications. The title here is 17 characters: this was
    never about length.
    """
    confirmation = "Hi Ayush, Thank you for applying to Northwind Analytics's Frontend Engineer position!"
    rejection = "Hi Ayush, Thank you so much for taking the time to apply for the Frontend Engineer opening at Northwind Analytics."

    a = pipeline.role_from_message("Thank you for applying", confirmation)
    b = pipeline.role_from_message("Important information", rejection)
    assert a == "Frontend Engineer", a
    assert pipeline.normalize_role_token(a) == pipeline.normalize_role_token(b)


def test_a_role_named_without_a_possessive_is_unchanged() -> None:
    """The control on the guard above: it must only remove an employer."""
    text = "Thank you for applying to the Backend Engineer, Payments position at Northwind."
    assert pipeline.role_from_message("Thanks", text) == "Backend Engineer, Payments"


def test_a_parenthesised_title_still_yields_a_role() -> None:
    """The requisition capture excluded `(`, so a real title yielded NO role.

    The stated reason for excluding it was to stop the capture running past the
    requisition label. The LABEL does that, and still does. Excluding the
    character only lost the role — and a confirmation carrying a requisition id
    and no role does not join its own rejection, which carries a role and no id.
    """
    text = (
        "Hi Ayush, Thank you for taking the time to submit your application for "
        f"{LONG_TITLE} (Job number: 200045485)."
    )
    assert pipeline.role_from_message("Thank you for your application!", text) == LONG_TITLE


def test_the_requisition_label_is_still_what_ends_the_title() -> None:
    """The control: an unlabelled parenthesis must not terminate the capture,
    and a plain title must be unaffected."""
    plain = "Hi Ayush, submit your application for Software Engineer II (Job number: 200045485)."
    assert pipeline.role_from_message("Thanks", plain) == "Software Engineer II"


def test_the_requisition_id_does_not_spend_the_titles_width() -> None:
    """A bounded capture must not measure text the cleaner is about to delete.

    Amazon prints the requisition between the title and the word that ends it:

        "...your application for the <TITLE> (ID: 10475660) position."

    The role capture is ``[A-Z](?:(?!'s\\s)[^.!?\\n]){3,90}?`` — a 91-character
    ceiling — and the span from the title's first letter to " position" is 93
    with the id inside it. So the bound cannot be met, the engine backtracks the
    preceding gap, and the capture restarts one word later. ``_clean_role``
    deletes the id on the very next line, which is the point: the bound was
    spent on characters that were never part of the answer.

    Applications 112 and 126 reached the owner's live board titled "Development
    Engineer I ...", each missing the first word of its own job title. Measured
    2026-08-23.
    """
    title = "Software Development Engineer I - AI/ML Network Infrastructure, Annapurna Labs"
    assert len(title) == 78
    body = (
        "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We've received your "
        f"application for the {title} (ID: 10475660) position. What happens next?"
    )
    assert pipeline.role_from_message("Thank you for Applying to Amazon!", body) == title


def test_the_same_title_without_a_requisition_is_unchanged() -> None:
    """The control that says the fix is about the id and not about the length.

    The identical title with no id is 78 characters, inside the ceiling either
    way, and was always captured whole. If this ever fails alongside the test
    above, the ceiling moved rather than the id being excluded from it.
    """
    title = "Software Development Engineer I - AI/ML Network Infrastructure, Annapurna Labs"
    body = (
        "Amazon.jobs Hi Ayush, Thanks for applying to Amazon! We've received your "
        f"application for the {title} position. What happens next?"
    )
    assert pipeline.role_from_message("Thank you for Applying to Amazon!", body) == title


def test_an_unlabelled_parenthesis_still_belongs_to_the_title() -> None:
    """The other control: only a LABELLED id is excluded from the width.

    ``req-id-same-title`` in the corpus prints "(R-40001)", which ``_clean_role``
    does not strip, so it is part of the title and must stay inside the bound
    and inside the answer. Excluding every parenthesis instead would silently
    truncate real titles — DoorDash's "Software Engineer I, Entry-Level
    (Graduation Date: Fall 2025-Summer 2026)" is one.
    """
    body = (
        "Hi Ayush, Thanks for applying! We have received your application for the "
        "Backend Engineer (R-40001) position."
    )
    assert (
        pipeline.role_from_message("Thanks", body) == "Backend Engineer (R-40001)"
    )
