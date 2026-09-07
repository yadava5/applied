"""Issue #427 item 1 — the Python classifier raised where the TypeScript port answered.

The defect
----------
``RulesClassifier.classify`` annotated both text arguments ``str`` and then
handed them straight to compiled patterns. A ``None`` came out as::

    TypeError: expected string or bytes-like object, got 'NoneType'

at **two** sites, not one::

    rules.py  in_subject = bool(pattern.search(subject))
    rules.py  in_body    = bool(pattern.search(body))

The issue body cites a third line, ``_REPLY_SUBJECT.match(subject or "")``.
That one was already null-safe and is not what raised; the citation is wrong.

The same four inputs never threw in the browser port — it answered
``rejection``, ``applied``, ``other`` and ``applied`` — so the two engines
disagreed about whether a message is classifiable at all, which is a wider
disagreement than any pattern.

Why the fix is at the entry and not at the two sites
----------------------------------------------------
An early guard masks the later ones. Normalise ``subject`` where it is read and
a null-subject test goes green while the body path is still live: the test then
reads as coverage for a hole it never reached. ``classify`` normalises once,
before either argument has a reader, so the guard cannot be half-applied.

That shape is what the two tests below are built to pin, and it is why they are
two tests rather than one. :func:`test_a_null_subject_is_classified` drives a
null subject with a REAL body, and :func:`test_a_null_body_is_classified` drives
a real subject with a null body, so each one can only pass through its own site.
Deleting either normalisation line alone reds exactly one of them.

:func:`test_both_null_is_classified` is deliberately not counted as evidence for
either site: with both arguments null the subject site is reached first, so it
reds under either deletion and discriminates nothing. It is here because
"both null" is a real input, not because it proves placement.

What was actually reachable
---------------------------
Nothing, at the time of the fix, and the issue's reachability claim does not
survive being checked. Gmail ingestion cannot produce a null — ``gmail_client``
defaults the subject to ``"(No Subject)"`` and coerces the snippet with
``or ""``, and ``CloudGmailMessage`` types both ``str``. The evaluation and
benchmark scripts read a JSONL file through ``load_dataset``, which coerces
every field with ``_string_or_empty``; their ``EvaluationExample`` is typed
``str`` and cannot carry a null either.

What is real is the latent hole those callers happen to close by hand:
``Email.subject`` and ``Email.body_text`` are ``Optional[str] = None`` in
``database/models.py``, so the storage layer's own shape is one the classifier's
signature promised to accept and did not. This file closes the gap as a
contract and a parity fix, not as a live crash — claiming a crash nobody could
reach would be a worse defect than the one being fixed.

Why no corpus number moves
--------------------------
``x or ""`` is the identity on the whole ``str`` domain, ``""`` included, so
every input any corpus or evaluation set contains is passed through unchanged.
The ``str`` arms below are the assertion of that, in both directions: an
identity claim against ``""`` and pinned verdicts on real mail-shaped text.

Employers, roles and senders are invented and every domain is reserved.
"""

from __future__ import annotations

import asyncio

import pytest

from jobtracker.classifier.hybrid import HybridClassifier
from jobtracker.classifier.rules import RulesClassifier
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

# Invented, on reserved domains. Each pair is mail-shaped enough to score, so a
# null argument is the only thing separating it from a verdict.
APPLIED_SUBJECT = "Thank you for applying to Cedarhollow Systems"
APPLIED_BODY = (
    "We have received your application for the Backend Engineer position and "
    "our team will review it shortly."
)
APPLIED_SENDER = "no-reply@cedarhollow.example"

REJECTION_SUBJECT = "Update on your application to Thorncombecross Dynamics"
REJECTION_BODY = (
    "After careful consideration we have decided not to move forward with your "
    "application at this time. We wish you the best in your search."
)
REJECTION_SENDER = "careers@thorncombecross.example"

ASSESSMENT_SUBJECT = "Complete your coding assessment for Marlowbridge Labs"
ASSESSMENT_BODY = (
    "Please complete the take-home coding challenge within 5 days using the "
    "link below."
)
ASSESSMENT_SENDER = "assessments@marlowbridge.example"


# ---------------------------------------------------------------------------
# A null is answered, not raised — one test per site
# ---------------------------------------------------------------------------


def test_a_null_subject_is_classified() -> None:
    """Bound to the ``in_subject`` site: the body here is a real string.

    Delete ``subject = subject or ""`` and this reds. Delete the body's
    normalisation instead and this stays green, which is what makes it a test
    of one site rather than of the pair.
    """
    result = CLASSIFIER.classify(None, REJECTION_BODY, REJECTION_SENDER)

    assert result.category == EmailCategory.REJECTION
    assert 0.0 < result.confidence <= 0.95


def test_a_null_body_is_classified() -> None:
    """Bound to the ``in_body`` site: the subject here is a real string.

    The mirror of the test above. Nothing reaches the body site unless the
    subject site has already been passed, which is precisely why a
    subject-only fix would have left this one failing.
    """
    result = CLASSIFIER.classify(APPLIED_SUBJECT, None, APPLIED_SENDER)

    assert result.category == EmailCategory.APPLIED
    assert 0.0 < result.confidence <= 0.95


def test_both_null_is_classified() -> None:
    """Real input, no discriminating power — see the module docstring.

    With both arguments null the subject site raises first, so this reds under
    either single deletion and says nothing about which one is missing.
    """
    result = CLASSIFIER.classify(None, None)

    assert result.category == EmailCategory.OTHER
    assert result.confidence == 0.5


# ---------------------------------------------------------------------------
# A null is exactly an empty string, not merely "something"
# ---------------------------------------------------------------------------


def test_a_null_subject_scores_as_an_empty_subject() -> None:
    """The semantic claim, not just the absence of a traceback.

    ``or ""`` is only correct if a null and an empty string are the same
    message. Whole-result equality asserts that on the category, the
    confidence, the matched patterns and every per-category score at once.
    """
    assert CLASSIFIER.classify(None, REJECTION_BODY, REJECTION_SENDER) == (
        CLASSIFIER.classify("", REJECTION_BODY, REJECTION_SENDER)
    )


def test_a_null_body_scores_as_an_empty_body() -> None:
    """Also covers the three body readers the normalisation now runs ahead of.

    ``own_text_span``, ``asserted_text`` and ``reflow_paragraphs`` all saw the
    raw ``None`` before this fix and survived it by accident. They now see
    ``""``, and this equality is what says that substitution changed nothing.
    """
    assert CLASSIFIER.classify(APPLIED_SUBJECT, None, APPLIED_SENDER) == (
        CLASSIFIER.classify(APPLIED_SUBJECT, "", APPLIED_SENDER)
    )


# ---------------------------------------------------------------------------
# The string path did not move
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "body", "sender", "category", "confidence"),
    [
        pytest.param(
            APPLIED_SUBJECT,
            APPLIED_BODY,
            APPLIED_SENDER,
            EmailCategory.APPLIED,
            0.95,
            id="applied",
        ),
        pytest.param(
            REJECTION_SUBJECT,
            REJECTION_BODY,
            REJECTION_SENDER,
            EmailCategory.REJECTION,
            0.95,
            id="rejection",
        ),
        pytest.param(
            ASSESSMENT_SUBJECT,
            ASSESSMENT_BODY,
            ASSESSMENT_SENDER,
            EmailCategory.ASSESSMENT,
            0.95,
            id="assessment",
        ),
        pytest.param(
            APPLIED_SUBJECT,
            "",
            APPLIED_SENDER,
            EmailCategory.APPLIED,
            0.90,
            id="empty-body",
        ),
        pytest.param(
            "",
            REJECTION_BODY,
            REJECTION_SENDER,
            EmailCategory.REJECTION,
            0.95,
            id="empty-subject",
        ),
        pytest.param("", "", None, EmailCategory.OTHER, 0.50, id="both-empty"),
    ],
)
def test_the_string_path_is_unchanged(
    subject: str,
    body: str,
    sender: str | None,
    category: EmailCategory,
    confidence: float,
) -> None:
    """Verdicts recorded on the parent commit, before the normalisation existed.

    Three categories plus the three ``str`` edge cases the fix could plausibly
    have disturbed. Values written out here rather than derived from a second
    call, so an assertion cannot agree with a regression by sharing it.
    """
    result = CLASSIFIER.classify(subject, body, sender)

    assert result.category == category
    assert result.confidence == pytest.approx(confidence)


# ---------------------------------------------------------------------------
# The HYBRID entry, which is the one every reachable caller actually enters
# ---------------------------------------------------------------------------
#
# #427 item 1 was closed on the RULES layer above, and that left the defect
# live one level up. ``HybridClassifier.classify`` is what the pipeline calls;
# ``RulesClassifier.classify`` is what the hybrid calls. So the fix above made
# the inner engine answer a null while the outer one still raised on it, and
# the parity claim item 1 is about was still false at the boundary that runs.
#
# THE CRASH WAS IN A LOG LINE, which is why nothing found it by reading the
# classification path. The content guard's ``logger.debug`` takes
# ``subject[:120]`` as an ARGUMENT, and arguments are evaluated eagerly no
# matter what the log level is, so a diagnostic that is switched off in
# production still destroyed the branch it exists to describe. Worse, the
# branch had already decided: ``_forced_other_reason`` is null-safe and had
# returned a reason, so the answer existed and was thrown away on the way to
# describing it.
#
# THE TWO ARMS DO NOT BOTH DISCRIMINATE HERE, and that is a measured result
# rather than an oversight. Deleting each normalisation in turn, on the five
# inputs below:
#
#     delete ``subject = subject or ""``  -> null-subject + digest body RAISES
#                                            TypeError; the other four unmoved
#     delete ``body = body or ""``        -> NOTHING MOVES. All five identical.
#
# So only the subject arm is gated, and the file says so instead of shipping a
# body test that would pass with the line deleted. The body normalisation is
# still correct and still lands: ``_forced_other_reason`` and the rules layer
# each re-normalise internally, so the only reader that can currently observe a
# raw ``None`` is the lifecycle rescan, which composes ``f"{subject}\n{body}"``
# and would scan the literal text ``None`` — and no lifecycle pattern matches
# that word, so the difference is real but has no outcome to show. It is kept
# for parity with ``RulesClassifier.classify``'s signature, which is the whole
# subject of this issue, and it is deliberately UNGATED rather than falsely
# gated.

#: Two ``NON_APPLICATION_PATTERNS`` hits and no lifecycle hit, which is what
#: ``_forced_other_reason`` requires to return "digest_or_promotional_content".
#: Written out rather than imported from the pattern list: an expectation read
#: from the thing it checks compares a value to itself.
DIGEST_BODY = "Here are your recommended jobs this week. Click unsubscribe to stop."


def _hybrid(subject, body, sender):
    """Drive the real async entry point. Not a helper around a helper."""
    return asyncio.run(HybridClassifier().classify(subject, body, sender))


def test_the_content_guard_answers_a_null_subject_instead_of_raising() -> None:
    """The live crash, with the control that proves the branch was reached.

    ``confidence == 0.96`` and ``method == "content_filter"`` are the guard's
    own signature. Asserting them rather than "did not raise" is what stops
    this passing because the guard silently stopped firing.
    """
    result = _hybrid(None, DIGEST_BODY, "a@b.example")

    assert result.method == "content_filter"
    assert result.confidence == 0.96


def test_the_content_guard_fires_on_a_real_subject_too() -> None:
    """The directional control for the test above.

    Same body, a real subject. If this ever stops returning the guard's
    signature then the test above is asserting something other than the
    branch it names, and both need re-deriving.
    """
    result = _hybrid("Jobs for you", DIGEST_BODY, "a@b.example")

    assert result.method == "content_filter"
    assert result.confidence == 0.96


def test_a_null_subject_reaches_the_hybrid_answer_an_empty_one_reaches() -> None:
    """The semantic claim: ``or ""`` is the identity, at the outer entry too.

    Compared on the three fields the pipeline reads. Whole-object equality is
    not available here — ``ClassificationResult`` carries a ``details`` dict
    whose contents are not part of the claim.
    """
    got = _hybrid(None, DIGEST_BODY, "a@b.example")
    want = _hybrid("", DIGEST_BODY, "a@b.example")

    assert (got.category, got.confidence, got.method) == (
        want.category,
        want.confidence,
        want.method,
    )


def test_a_null_does_not_disturb_a_verdict_the_hybrid_already_reached() -> None:
    """A lifecycle message still classifies, with a null in the other field.

    The refusal this pins is the tempting one: normalising at the entry must
    not change what a message that was already answered comes back as.
    """
    result = _hybrid("Update on your application", None, "careers@halberd.test")

    assert result.category is not None
    assert _hybrid("Update on your application", "", "careers@halberd.test").category == (
        result.category
    )
