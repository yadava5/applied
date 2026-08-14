"""``hybrid.py``'s ``OTHER`` -> ``NEEDS_REVIEW`` safety net is dead. Pin it (#253).

The block at the bottom of ``HybridClassifier.classify`` reads as a guarantee:
mail the classifier cannot place, but which scores as plausibly job-related, is
held for a human instead of dropped. It has never once run.

It is dead **twice over**, and the two facts can be removed independently — so
this file pins them independently.

**(a) Deployment.** ``self._cloud_rules_only`` returns ~130 lines earlier, and
cloud is the only place production mail is classified. Anyone who rewires that
short-circuit — to re-enable the semantic layers, say — switches the net on for
every message in a scan as a side effect. That is exactly the queue-flooding
blast radius #252 was scoped to avoid, and it should not happen by accident.

**(b) The guard is unsatisfiable, on every deployment.** ``rules.py`` seeds
``scores`` with one entry per ``EmailCategory``, so ``scores["other"]`` is
always exactly 0 and the winning score is never negative. Rules returns
``OTHER`` on exactly one branch, ``if winner_score <= 0``, which given that
floor means ``winner_score == 0`` — every category scored <= 0. So
``category == OTHER`` already *implies* ``max_job_score <= 0``, and the net's
``max_job_score >= 2`` cannot hold. Wiring the net into the cloud branch
verbatim would therefore change nothing at all; the block would still never be
entered.

What the net was reaching for does exist: a message whose job patterns matched
and were then erased by ``negative`` (-5) or ``veto`` (clamp to 0) arithmetic
lands ``OTHER`` with real evidence behind it. But that evidence survives only
in ``matched_patterns``. ``scores`` holds the post-arithmetic total, which for
such a message is *negative*. The net reads the wrong side of the subtraction —
``test_the_population_the_net_was_reaching_for_scores_negative`` is that case,
made concrete.

**Volume, measured before this file was written (#253):** over the committed
evaluation corpus (200 messages) plus production ``emails`` metadata replayed
read-only (51), the net fires on 0. That 0 is a proof rather than a sample —
but the corpus is thin here regardless (26 ``OTHER`` verdicts, 13 of them
content-guard forces), so read it as "the guard cannot be met", never as
"the threshold is well chosen".

**When this file goes red, it is doing its job.** It asserts current behaviour
on purpose. A failure here means someone changed one of the two facts above and
should go read #253 before deciding the failure is a bug.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobtracker.classifier import hybrid as hybrid_module
from jobtracker.classifier.hybrid import HybridClassifier
from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.database.models import EmailCategory

# The six categories the net inspects — hybrid.py's own list, restated so a
# change to one is visible as a diff against the other.
JOB_CATEGORIES = (
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
)

EVAL_FILES = (
    "classifier_eval_v1.jsonl",
    "classifier_eval_v2.jsonl",
    "classifier_eval_v3.jsonl",
)

# A message whose job patterns matched and were then subtracted away. This is
# the shape the safety net exists for, and the net cannot see it: the evidence
# lives in ``matched_patterns`` while the score it reads is negative.
ERASED_EVIDENCE = (
    "Thanks for applying",
    "your course is unfortunately over",
    None,
)

# Rules-unsure, content-guard-clean messages. These are what make the cloud
# reachability assertion load-bearing: each scores BELOW 0.90, so the early
# ``rules_result.confidence >= 0.90`` return cannot be what keeps them out of
# the fallback block. Only the cloud short-circuit can.
BELOW_THE_EARLY_RETURN = (
    ("A quick note", "We will review your resume.", None),
    ("Thank you for your interest", "Regards.", None),
    ERASED_EVIDENCE,
    ("Checking in", "Wanted to see where things stand.", "person@example.com"),
)


def _corpus() -> list[tuple[str, str, str | None]]:
    """The committed evaluation corpus, as (subject, body, sender) triples."""
    root = Path(__file__).resolve().parents[1] / "data" / "evaluation"
    messages: list[tuple[str, str, str | None]] = []
    for name in EVAL_FILES:
        for line in (root / name).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            messages.append(
                (row.get("subject", ""), row.get("body_text", ""), row.get("sender_email"))
            )
    return messages


CORPUS = _corpus()


def _max_job_score(scores: dict[str, int]) -> int:
    return max(scores.get(category, 0) for category in JOB_CATEGORIES)


@pytest.fixture()
def cloud_classifier(monkeypatch: pytest.MonkeyPatch) -> HybridClassifier:
    """A classifier built the way Vercel builds it.

    ``_cloud_rules_only`` is read from ``settings`` in ``__init__``, so this
    patches the setting and constructs — rather than setting the attribute
    afterwards, which would test the fixture instead of the constructor.
    """
    monkeypatch.setattr(hybrid_module.settings, "deployment", "cloud")
    classifier = HybridClassifier()
    assert classifier._cloud_rules_only is True, "cloud flag not wired"
    return classifier


# ---------------------------------------------------------------------------
# (a) The cloud path never reaches the block the net lives in.
# ---------------------------------------------------------------------------


async def test_the_cloud_path_never_reaches_the_fallback_block(cloud_classifier):
    """No cloud verdict is ever produced by the fallback — the net's own block.

    Two observables, and the second is the one that holds in CI.

    ``method`` is the obvious one: the cloud path can only answer
    ``content_filter`` (entry guard) or ``rules`` (the >= 0.90 return, or the
    short-circuit). ``fallback`` means execution ran off the end of
    ``classify()``, which is where the safety net sits.

    But ``method`` alone is environment-dependent. Locally the semantic layers
    are not installed, so removing the short-circuit lands in ``fallback``; in
    CI, where torch and sentence-transformers ARE installed, the same removal
    could answer ``embeddings`` and — if a future edit widened the allowed set
    — slip past. The lazy loaders do not have that problem. Layer 2 evaluates
    ``self._embeddings.is_available()`` unconditionally, and that property
    access populates ``_embeddings_instance``. Both instances staying ``None``
    after a full battery is proof that execution never got past the
    short-circuit, in any environment, whatever is installed.

    Goes red if the ``if self._cloud_rules_only:`` branch is removed or
    narrowed. That is not a broken test — see this module's docstring.
    """
    verdicts = []
    for subject, body, sender in list(BELOW_THE_EARLY_RETURN) + CORPUS:
        result = await cloud_classifier.classify(subject, body, sender)
        verdicts.append((subject, result))

    assert cloud_classifier._embeddings_instance is None, (
        "the cloud classifier reached Layer 2 — execution ran past the "
        "short-circuit, and the OTHER -> NEEDS_REVIEW safety net at the "
        "bottom of classify() is now live for every message in a scan. "
        "See #253."
    )
    assert cloud_classifier._setfit_instance is None, (
        "the cloud classifier reached Layer 3; same consequence as above (#253)"
    )

    offenders = [
        (subject, result.method)
        for subject, result in verdicts
        if result.method not in {"rules", "content_filter"}
    ]
    assert offenders == [], (
        "a cloud verdict came from past the short-circuit: "
        f"{offenders[:5]}. The OTHER -> NEEDS_REVIEW safety net lives down "
        "there; enabling this path enables the net for every message in a "
        "scan. See #253."
    )


async def test_the_reachability_pin_is_not_vacuous(cloud_classifier):
    """The assertion above must rest on the short-circuit, not on an earlier return.

    If every message the pin feeds happened to score >= 0.90, ``classify``
    would return at the rules layer and the pin would pass with the
    short-circuit deleted. Prove there are messages whose ONLY reason for not
    reaching the fallback is the cloud branch.
    """
    rules = get_rules_classifier()
    unsure = [
        (subject, body, sender)
        for subject, body, sender in BELOW_THE_EARLY_RETURN
        if rules.classify(subject, body, sender).confidence < 0.90
        and cloud_classifier._forced_other_reason(subject, body, sender) is None
    ]
    assert len(unsure) >= 3, (
        "the reachability pin needs messages that are rules-unsure AND not "
        f"content-guarded, or it proves nothing; got {len(unsure)}"
    )


async def test_no_cloud_verdict_is_ever_needs_review(cloud_classifier):
    """``NEEDS_REVIEW`` is the net's output, and production has never seen it.

    ``collect_review_items`` routes ``category == "needs_review"`` straight to
    the human queue at any confidence. Nothing on the cloud path emits it.
    """
    emitted = set()
    for subject, body, sender in list(BELOW_THE_EARLY_RETURN) + CORPUS:
        result = await cloud_classifier.classify(subject, body, sender)
        emitted.add(result.category)
    assert EmailCategory.NEEDS_REVIEW not in emitted, (
        "the cloud classifier emitted NEEDS_REVIEW. If that was deliberate, "
        "#253 is the argument about queue volume you now owe."
    )


# ---------------------------------------------------------------------------
# (b) The guard itself cannot be satisfied, on any deployment.
# ---------------------------------------------------------------------------


def test_other_always_implies_every_job_score_is_non_positive():
    """The rules contract the net's condition contradicts.

    ``rules.py`` returns ``OTHER`` only when the winning score is <= 0, and
    ``scores["other"]`` is always exactly 0 — so ``OTHER`` means every job
    category scored <= 0, and ``max_job_score >= 2`` is unreachable.

    Goes red if that branch is relaxed (``winner_score < 3``, say) or if
    ``PATTERNS`` gains an ``EmailCategory.OTHER`` entry that lets ``other``
    win on a positive score.
    """
    rules = get_rules_classifier()
    others = 0
    violations = []
    for subject, body, sender in list(BELOW_THE_EARLY_RETURN) + CORPUS:
        result = rules.classify(subject, body, sender)
        if result.category is not EmailCategory.OTHER:
            continue
        others += 1
        top = _max_job_score(result.scores)
        if top > 0:
            violations.append((subject, top))

    assert others >= 20, (
        f"only {others} OTHER verdicts in the corpus — the implication has "
        "almost no subjects left and this pin has stopped meaning anything"
    )
    assert violations == [], (
        "rules returned OTHER with a positive job score: "
        f"{violations[:5]}. The safety net in hybrid.py is written against "
        "the opposite contract; if this is now possible, go read #253 — the "
        "net may have just become live."
    )


def test_the_population_the_net_was_reaching_for_scores_negative():
    """The exact shape the net exists for, and the number it reads.

    Job patterns matched (``applied``, in the subject, worth +6) and were then
    erased by ``negative`` arithmetic. The message lands ``OTHER`` with real
    evidence in ``matched_patterns`` — and ``max_job_score`` is negative, so
    the net's ``>= 2`` never sees it. This is the diagnosis, not a passing
    detail: the net reads the post-subtraction total.
    """
    subject, body, sender = ERASED_EVIDENCE
    result = get_rules_classifier().classify(subject, body, sender)

    assert result.category is EmailCategory.OTHER
    assert any("[STRONG-SUBJECT]" in tag for tag in result.matched_patterns), (
        "the fixture is only interesting if a job pattern actually matched; "
        f"matched={result.matched_patterns}"
    )
    assert result.scores["applied"] < 0, (
        "this fixture exists because its job evidence is subtracted below "
        f"zero; scores={result.scores}"
    )
    assert _max_job_score(result.scores) < 2, (
        "the net's threshold is now reachable for the very population it was "
        "written for — which makes it live. See #253."
    )
