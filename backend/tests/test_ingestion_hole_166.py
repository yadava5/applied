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

Status of this file
-------------------
Characterisation, plus one ``xfail(strict=True)`` that encodes the behaviour
the product needs. Nothing here is fixed — closing the hole means changing what
mail the board reads, which is a product decision, not a patch. Drop the
``xfail`` marker to get the red test.
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


def test_the_together_ai_rejection_vanishes_without_trace() -> None:
    """THE BUG, reproduced: no application row, no queue entry, no log line.

    Same preamble shape as Verkada's, which DID reach the queue. The only
    difference is the subject line, and it is worth the 0.10 that separates
    ``REVIEW_FLOOR`` from silence.
    """
    result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "19ff7393d56eccfb"
    )

    assert result.confidence < pipeline.REVIEW_FLOOR, result.scores
    assert not _leaves_a_trace(item), "expected the terminal drop; it left a row"
    # And the drop is silent: collect_review_items only logs at/above the
    # auto-file gate, precisely to keep ordinary inbox noise out of the log.
    assert result.confidence < pipeline.AUTO_FILE_GATE


def test_the_subject_is_the_whole_difference() -> None:
    """Swap in Verkada's subject over Together AI's body and it survives.

    The pair is the proof that neither the fetch, the cursor, nor the body is
    what decided this message's fate.
    """
    _lost, lost_item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "lost"
    )
    _kept, kept_item = _item(
        VERKADA_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "kept"
    )

    assert not _leaves_a_trace(lost_item)
    assert _leaves_a_trace(kept_item)


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


def test_greenhouse_and_rippling_are_not_recognised_as_ats_senders() -> None:
    """``ATS_DOMAINS`` lists ``greenhouse.io``; Greenhouse sends from
    ``us.greenhouse-mail.io``, which that substring does not match.

    Greenhouse is the most common ATS in the production corpus and has never
    once received the +0.05 ATS confidence bonus. Rippling's ATS is absent
    outright. Recorded, not fixed: the bonus can push a 0.80 verdict to exactly
    ``AUTO_FILE_GATE``, so adding these domains changes which mail auto-files
    and is not a drive-by edit.
    """
    from jobtracker.classifier.rules import ATS_DOMAINS

    for sender in (GREENHOUSE, RIPPLING):
        domain = sender.split("@", 1)[1]
        assert not any(ats in domain for ats in ATS_DOMAINS), domain


# ===========================================================================
# 3. What the product needs. RED — drop the marker to see it fail.
# ===========================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "issue #166, unfixed: an ATS lifecycle message whose subject matches no "
        "pattern falls under REVIEW_FLOOR and is dropped with no row, no queue "
        "entry and no log. Closing this changes what mail the board reads, so it "
        "is a product decision rather than a patch."
    ),
)
def test_an_ats_application_message_must_never_vanish_silently() -> None:
    """Mail from a known ATS, about an application, must leave *something*.

    Not "must be classified correctly" — that is a hard problem on 200
    characters of preamble. Only that it must not disappear. The review queue
    is the product's designed home for "we cannot tell", and it is what made
    every other rejection on this board recoverable.
    """
    _result, item = _item(
        TOGETHER_SUBJECT, TOGETHER_SNIPPET_PREAMBLE, GREENHOUSE, "19ff7393d56eccfb"
    )

    assert _leaves_a_trace(item)
