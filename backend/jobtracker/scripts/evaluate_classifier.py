#!/usr/bin/env python3
"""Evaluate classifier quality on a labeled JSONL dataset.

This harness produces per-class precision/recall/F1, overall metrics,
and optional non-regression checks against a saved baseline report.

``--compare-rules`` additionally scores the rules-only classifier over the same
examples in the same invocation and prints the delta, which is the only
measurement of whether the learned layers earn their place; every report also
records the artifacts that answered (``artifacts``) and the SHA-256 of the
corpus, so a verdict can be traced to the checkpoint and dataset that produced
it. See ``docs/ML_PROMOTION_POLICY.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobtracker.classifier.hybrid import HybridClassifier
from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.database import init_db
from jobtracker.database.models import EmailCategory

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = BACKEND_DIR / "data" / "evaluation" / "classifier_eval_v1.jsonl"
DEFAULT_BASELINES = {
    "rules": BACKEND_DIR / "data" / "evaluation" / "baseline_rules_v1.json",
    "hybrid": BACKEND_DIR / "data" / "evaluation" / "baseline_hybrid_v1.json",
}

# The layers of HybridClassifier that are actually models. Deliberately excludes
# "content_filter", which is a deterministic veto reachable without any model
# loading, and "rules"/"fallback", which are the deterministic path itself.
# Kept in sync with the ``method=`` values in classifier/hybrid.py.
SEMANTIC_LAYERS = frozenset({"embeddings", "setfit"})

# How far ahead of rules-only the cascade must be on the committed set before a
# learned layer may serve real mail. Stated here, in the harness that measures
# it, so ``docs/ML_PROMOTION_POLICY.md`` cites executing code rather than an
# intention. It is a *reporting* threshold: --compare-rules prints the verdict
# and records it in the report, and no run fails merely for being behind.
# Today the cascade is behind rules by ~0.021 macro-F1, so nothing is
# promotable and the honest thing is to say so in the artifact.
PROMOTION_MARGIN = 0.005

VALID_LABELS = {category.value for category in EmailCategory}
DEFAULT_LABEL_ORDER = [
    EmailCategory.APPLIED.value,
    EmailCategory.PENDING_APPLICATION.value,
    EmailCategory.INTERVIEW.value,
    EmailCategory.REJECTION.value,
    EmailCategory.OFFER.value,
    EmailCategory.ASSESSMENT.value,
    EmailCategory.FOLLOW_UP.value,
    EmailCategory.OTHER.value,
    EmailCategory.NEEDS_REVIEW.value,
]


@dataclass
class EvaluationExample:
    subject: str
    body_text: str
    label: str
    sender_email: str | None


@dataclass
class ExampleOutcome:
    expected: str
    predicted: str
    subject: str
    # Which layer produced the wrong answer. Aggregate tallies say a model ran;
    # this says whether the model is what got it wrong, which is the difference
    # between "the cascade is behind" and "the cascade is behind because of X".
    method: str | None = None


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_dataset(path: Path) -> list[EvaluationExample]:
    """Load and validate JSONL dataset rows."""
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    examples: list[EvaluationExample] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_no}: expected object")

            label = _string_or_empty(payload.get("label"))
            if label not in VALID_LABELS:
                valid_sorted = ", ".join(sorted(VALID_LABELS))
                raise ValueError(
                    f"Line {line_no}: invalid label '{label}'. Valid labels: {valid_sorted}"
                )

            subject = _string_or_empty(payload.get("subject"))
            body_text = _string_or_empty(payload.get("body_text") or payload.get("body"))
            sender_email = _string_or_empty(payload.get("sender_email")) or None

            examples.append(
                EvaluationExample(
                    subject=subject,
                    body_text=body_text,
                    label=label,
                    sender_email=sender_email,
                )
            )

    if not examples:
        raise ValueError(f"Dataset is empty: {path}")

    return examples


async def predict_labels(
    examples: list[EvaluationExample],
    mode: str,
    *,
    hybrid_profile: str,
) -> tuple[list[str], list[str], HybridClassifier | None]:
    """
    Run classifier predictions for all examples.

    Returns the predicted labels, the layer that produced each one, and (for
    hybrid runs) the classifier instance itself, so the caller can record which
    artifacts answered — see ``_collect_artifact_provenance``.

    The tally is not diagnostics. ``HybridClassifier`` degrades on purpose when a
    semantic layer will not load — the API must keep answering when the SetFit
    model is missing — so a hybrid run whose ML layers are all dead still returns
    a full set of predictions, from rules. On this dataset rules and hybrid score
    identically (see ``data/evaluation/benchmark_history.md``), so that run scores
    0.9791, matches the committed baseline, and passes. A green hybrid benchmark
    is therefore not by itself evidence that anything hybrid ran. The tally is what
    makes the difference observable, and ``_assert_layers_exercised`` is what makes
    it fatal.
    """
    predictions: list[str] = []
    methods: list[str] = []

    if mode == "rules":
        rules_classifier = get_rules_classifier()
        for item in examples:
            rules_result = rules_classifier.classify(
                item.subject, item.body_text, item.sender_email
            )
            predictions.append(rules_result.category.value)
            methods.append("rules")
        return predictions, methods, None

    if mode == "hybrid":
        classifier = HybridClassifier()
        _configure_hybrid_profile(classifier, hybrid_profile)
        for item in examples:
            result = await classifier.classify(item.subject, item.body_text, item.sender_email)
            predictions.append(result.category.value)
            methods.append(getattr(result, "method", None) or "unknown")
        return predictions, methods, classifier

    raise ValueError(f"Unsupported mode: {mode}")


def _collect_artifact_provenance(classifier: HybridClassifier | None) -> dict[str, Any]:
    """
    Record *which* learned artifacts answered, not just that some layer did.

    A macro-F1 without this is untraceable: SetFit checkpoints are trained on
    disk, are never committed, and rotate (``MAX_SAVED_MODELS = 3``), so a
    cascade score six weeks old cannot otherwise be attributed to the model that
    produced it, and a bad retrain cannot be pointed at. Everything here is read
    off instances that already exist — nothing is loaded to fill this block, so
    a run that never touched a model records it as absent rather than loading
    one to find out.
    """
    provenance: dict[str, Any] = {}
    if classifier is None:
        return provenance

    embeddings = getattr(classifier, "_embeddings_instance", None)
    if embeddings is not None:
        embedding_model = getattr(embeddings, "_model", None)
        provenance["embeddings"] = {
            "model": getattr(type(embedding_model), "MODEL_NAME", None),
            "loaded": getattr(embedding_model, "_model", None) is not None,
            # The store the similarity layer searches. Zero means the layer was
            # present and had nothing to compare against, which is a different
            # fact from the model failing to load.
            "example_count": len(getattr(embeddings, "_known_embeddings", []) or []),
        }

    setfit = getattr(classifier, "_setfit_instance", None)
    if setfit is not None:
        from jobtracker.classifier.setfit_model import get_latest_model_path, get_models_dir

        checkpoint = get_latest_model_path()
        entry: dict[str, Any] = {
            "loaded": getattr(setfit, "_model", None) is not None,
            "checkpoint": checkpoint.name if checkpoint is not None else None,
        }
        if checkpoint is None:
            # Only recorded when there is nothing to record instead: the search
            # path is what makes an absent checkpoint diagnosable, and it is a
            # machine-specific path that would otherwise churn the committed
            # baseline on every re-record.
            entry["models_dir"] = str(get_models_dir())
        if checkpoint is not None:
            metadata_path = checkpoint / "training_metadata.json"
            if metadata_path.exists():
                try:
                    metadata = _read_json(metadata_path)
                except (OSError, ValueError):
                    metadata = {}
                # A deliberate subset: what identifies the artifact and what it
                # was trained on. The full metadata (per-label source counts)
                # stays next to the checkpoint.
                for key in ("base_model", "trained_at", "total_examples", "source_counts"):
                    if key in metadata:
                        entry[key] = metadata[key]
        provenance["setfit"] = entry

    return provenance


def _assert_layers_exercised(
    report: dict[str, Any],
    *,
    mode: str,
    hybrid_profile: str,
) -> list[str]:
    """
    Fail a hybrid/full run whose semantic layers never actually ran.

    Only ``--hybrid-profile full`` is checked. ``deterministic`` disables SetFit
    and blanks the embedding examples by design, for machine-stable CI gating, so
    demanding those layers there would be demanding the opposite of what it is for.
    """
    if mode != "hybrid" or hybrid_profile != "full":
        return []

    layers = report.get("layers", {})
    # An allowlist, not "anything that is not rules". ``content_filter`` is a
    # deterministic veto that fires both ahead of the rules layer (hybrid.py:238)
    # and inside the semantic branches (hybrid.py:353, :398), so its presence says
    # nothing about whether an ML layer ran -- a lite-mode run scores 0.9791 with
    # content_filter=5, rules=58, fallback=33 and no model loaded at all. Naming the
    # two layers that are actually models is the only check that excludes that run.
    if any(layers.get(name, 0) > 0 for name in SEMANTIC_LAYERS):
        return []

    observed = ", ".join(f"{k}={v}" for k, v in sorted(layers.items())) or "none recorded"
    expected = "/".join(sorted(SEMANTIC_LAYERS))
    return [
        f"hybrid/full answered nothing from {expected} (layers: {observed}). "
        "Every prediction came from the deterministic path, so this run measures the "
        "rules classifier and would report it as hybrid. Known causes: setfit or "
        "sentence-transformers failed to import (check the warnings above), "
        "JOBTRACKER_LITE_MODE is set, or deployment=cloud forces lite mode. "
        f"{_missing_artifact_hint(report)}"
        "Re-run with --allow-degraded-layers if a rules-only measurement is what you want."
    ]


def _missing_artifact_hint(report: dict[str, Any]) -> str:
    """
    Name the artifact that is absent, with the path that was searched.

    On a GitHub-hosted runner the cause is always the same and is not a bug:
    SetFit checkpoints live under the app's data directory and are not in the
    repository, so there is nothing to load. Saying which directory was empty
    turns that from a puzzling red build into the documented blocker it is.
    """
    setfit = (report.get("artifacts") or {}).get("setfit") or {}
    if not setfit:
        return ""
    checkpoint = setfit.get("checkpoint")
    if checkpoint is None:
        return f"No SetFit checkpoint was found in {setfit.get('models_dir')}. "
    return f"A SetFit checkpoint is on disk ({checkpoint}) but did not answer. "


def _configure_hybrid_profile(classifier: HybridClassifier, profile: str) -> None:
    """
    Configure hybrid classifier profile for reproducible evaluation.

    - full: normal runtime behavior (all available layers)
    - deterministic: force layer behavior that is independent of local model/DB state
      by disabling SetFit and bypassing embedding examples
    """
    if profile == "full":
        return

    if profile == "deterministic":
        classifier.set_lite_mode(True)
        embeddings = getattr(classifier, "_embeddings", None)
        if embeddings is not None:
            # Prevent DB/stateful embedding examples from affecting benchmark
            # outcomes. Must go through ``pin_empty_corpus``: the layer's load
            # cache is keyed by owner, so poking ``_loaded`` alone no longer
            # stops a re-read for a caller with a different identity.
            embeddings.pin_empty_corpus()
        return

    raise ValueError(f"Unsupported hybrid profile: {profile}")


def _select_label_order(expected: list[str], predicted: list[str]) -> list[str]:
    expected_set = set(expected)
    predicted_set = set(predicted)
    seen = expected_set | predicted_set

    ordered: list[str] = []
    for label in DEFAULT_LABEL_ORDER:
        if label in seen:
            ordered.append(label)

    for label in sorted(seen - set(ordered)):
        ordered.append(label)

    return ordered


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def compute_report(
    expected: list[str],
    predicted: list[str],
    examples: list[EvaluationExample],
    dataset_path: Path,
    mode: str,
    methods: list[str] | None = None,
) -> dict[str, Any]:
    """Build aggregate metrics and confusion matrix."""
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted label counts do not match")

    labels = _select_label_order(expected, predicted)
    total = len(expected)

    per_label: dict[str, dict[str, Any]] = {}
    for label in labels:
        true_positive = sum(
            1 for exp, pred in zip(expected, predicted, strict=True) if exp == label and pred == label
        )
        false_positive = sum(
            1 for exp, pred in zip(expected, predicted, strict=True) if exp != label and pred == label
        )
        false_negative = sum(
            1 for exp, pred in zip(expected, predicted, strict=True) if exp == label and pred != label
        )
        support = sum(1 for exp in expected if exp == label)

        precision = _safe_div(true_positive, true_positive + false_positive)
        recall = _safe_div(true_positive, true_positive + false_negative)
        f1 = _safe_div(2 * precision * recall, precision + recall)

        per_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
        }

    accuracy = _safe_div(
        sum(1 for exp, pred in zip(expected, predicted, strict=True) if exp == pred),
        total,
    )

    labels_with_support = [label for label, metrics in per_label.items() if metrics["support"] > 0]
    macro_f1 = _safe_div(
        sum(per_label[label]["f1"] for label in labels_with_support),
        len(labels_with_support),
    )
    weighted_f1 = _safe_div(
        sum(per_label[label]["f1"] * per_label[label]["support"] for label in per_label),
        total,
    )

    confusion_matrix: dict[str, dict[str, int]] = {
        actual: dict.fromkeys(labels, 0) for actual in labels
    }
    for actual, pred in zip(expected, predicted, strict=True):
        confusion_matrix[actual][pred] += 1

    layer_of: list[str | None] = list(methods) if methods is not None else [None] * total
    mismatches = [
        ExampleOutcome(expected=exp, predicted=pred, subject=item.subject, method=method)
        for item, exp, pred, method in zip(
            examples, expected, predicted, layer_of, strict=True
        )
        if exp != pred
    ]

    label_distribution = Counter(expected)
    prediction_distribution = Counter(predicted)

    return {
        "meta": {
            "dataset": str(dataset_path),
            "mode": mode,
            "generated_at": datetime.now(UTC).isoformat(),
            "sample_count": total,
        },
        "overall": {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "weighted_f1": weighted_f1,
            "misclassified": len(mismatches),
        },
        "per_label": per_label,
        "confusion_matrix": confusion_matrix,
        "label_distribution": dict(label_distribution),
        "prediction_distribution": dict(prediction_distribution),
        "mismatches": [
            {
                "expected": item.expected,
                "predicted": item.predicted,
                "subject": item.subject,
                **({"method": item.method} if item.method is not None else {}),
            }
            for item in mismatches
        ],
    }


def compare_against_baseline(
    report: dict[str, Any],
    baseline: dict[str, Any],
    tolerance: float,
) -> list[str]:
    """Return non-regression failures relative to baseline metrics."""
    failures: list[str] = []

    # A run is only comparable to a baseline taken under the same profile. The
    # committed hybrid baseline is a `deterministic` one -- SetFit off, embedding
    # examples blanked -- which is why it equals the rules baseline to sixteen
    # decimal places. Scoring a `full` run against it reads every contribution the
    # semantic layers make, good or bad, as a regression against the rules number.
    current_profile = report.get("meta", {}).get("hybrid_profile")
    baseline_profile = baseline.get("meta", {}).get("hybrid_profile")
    if current_profile != baseline_profile:
        failures.append(
            f"hybrid_profile mismatch: this run is '{current_profile}' but the baseline "
            f"was generated with '{baseline_profile}'. These measure different classifiers "
            "and their scores are not comparable. Point --baseline at a file recorded "
            "under the same profile, or regenerate with --update-baseline."
        )
        return failures

    # The same idea one level deeper. A `full` run whose SetFit checkpoint is
    # missing still passes the profile check and still answers every example --
    # from rules -- so against a baseline that *did* have the model it reports
    # the model's absence as a quality regression. The layer guard above catches
    # the case where NO semantic layer answered; this catches the case where one
    # answered and the other, which the baseline was recorded with, did not.
    baseline_layers = baseline.get("layers") or {}
    current_layers = report.get("layers") or {}
    absent = [
        layer
        for layer in sorted(SEMANTIC_LAYERS)
        if baseline_layers.get(layer, 0) > 0 and current_layers.get(layer, 0) == 0
    ]
    if absent:
        recorded_checkpoint = ((baseline.get("artifacts") or {}).get("setfit") or {}).get(
            "checkpoint"
        )
        detail = (
            f" The baseline was recorded with checkpoint {recorded_checkpoint}."
            if "setfit" in absent and recorded_checkpoint
            else ""
        )
        failures.append(
            f"learned layer mismatch: the baseline was recorded with "
            f"{', '.join(absent)} answering, and here "
            f"{'it' if len(absent) == 1 else 'they'} answered nothing.{detail} "
            "This run measures a smaller classifier than the baseline does, so the "
            "score difference is the missing artifact and not a quality change. "
            "Supply the artifact, or compare against a baseline recorded without it."
        )
        return failures

    current_overall = report.get("overall", {})
    baseline_overall = baseline.get("overall", {})

    for metric_name in ["accuracy", "macro_f1", "weighted_f1"]:
        baseline_value = baseline_overall.get(metric_name)
        current_value = current_overall.get(metric_name)
        if not isinstance(baseline_value, (int, float)):
            continue
        if not isinstance(current_value, (int, float)):
            failures.append(f"Missing current overall metric: {metric_name}")
            continue
        if current_value + tolerance < baseline_value:
            failures.append(
                f"overall.{metric_name} regressed: current={current_value:.4f}, "
                f"baseline={baseline_value:.4f}, tolerance={tolerance:.4f}"
            )

    current_per_label = report.get("per_label", {})
    baseline_per_label = baseline.get("per_label", {})

    if isinstance(baseline_per_label, dict):
        for label, baseline_metrics_any in baseline_per_label.items():
            if not isinstance(baseline_metrics_any, dict):
                continue
            baseline_support = baseline_metrics_any.get("support", 0)
            baseline_f1 = baseline_metrics_any.get("f1")
            if baseline_support == 0 or not isinstance(baseline_f1, (int, float)):
                continue

            current_metrics_any = current_per_label.get(label)
            if not isinstance(current_metrics_any, dict):
                failures.append(f"Missing current per-label metrics: {label}")
                continue

            current_f1 = current_metrics_any.get("f1")
            if not isinstance(current_f1, (int, float)):
                failures.append(f"Missing current per-label f1: {label}")
                continue

            if current_f1 + tolerance < baseline_f1:
                failures.append(
                    f"per_label.{label}.f1 regressed: current={current_f1:.4f}, "
                    f"baseline={baseline_f1:.4f}, tolerance={tolerance:.4f}"
                )

    return failures


def print_summary(report: dict[str, Any], max_mismatches: int) -> None:
    """Print a concise human-readable report."""
    meta = report["meta"]
    overall = report["overall"]
    per_label = report["per_label"]

    print("\n=== Classifier Evaluation ===")
    print(f"dataset: {meta['dataset']}")
    print(f"mode: {meta['mode']}")
    if "hybrid_profile" in meta:
        print(f"hybrid_profile: {meta['hybrid_profile']}")
    print(f"samples: {meta['sample_count']}")
    layers = report.get("layers") or {}
    if layers:
        # Printed next to the score, not buried, because it is the line that says
        # whether the score came from the classifier named in `mode`.
        answered = ", ".join(f"{name}={count}" for name, count in sorted(layers.items()))
        print(f"answered by: {answered}")
    artifacts = report.get("artifacts") or {}
    if artifacts:
        # The other half of "which classifier was this": the layer tally says a
        # model answered, this says *which* model, in the run log where a reader
        # of a green build will see it.
        embeddings = artifacts.get("embeddings") or {}
        if embeddings:
            print(
                f"embeddings: model={embeddings.get('model')} "
                f"loaded={embeddings.get('loaded')} "
                f"examples={embeddings.get('example_count')}"
            )
        setfit = artifacts.get("setfit") or {}
        if setfit:
            print(
                f"setfit: checkpoint={setfit.get('checkpoint')} "
                f"loaded={setfit.get('loaded')} "
                f"base={setfit.get('base_model')} "
                f"trained_on={setfit.get('total_examples')} examples"
            )
    print(
        f"accuracy: {overall['accuracy']:.4f} | macro_f1: {overall['macro_f1']:.4f} | "
        f"weighted_f1: {overall['weighted_f1']:.4f} | misclassified: {overall['misclassified']}"
    )

    print("\nPer-label metrics")
    print("label                   support  precision  recall  f1")
    for label in per_label:
        metrics = per_label[label]
        print(
            f"{label:<22} {metrics['support']:>7}  {metrics['precision']:.4f}"
            f"     {metrics['recall']:.4f}  {metrics['f1']:.4f}"
        )

    mismatches = report.get("mismatches", [])
    if isinstance(mismatches, list) and mismatches:
        print(f"\nMismatches (showing up to {max_mismatches})")
        for item in mismatches[:max_mismatches]:
            if not isinstance(item, dict):
                continue
            expected = item.get("expected", "")
            predicted = item.get("predicted", "")
            subject = str(item.get("subject", ""))
            preview = subject if len(subject) <= 90 else subject[:87] + "..."
            answered_by = f" by={item['method']}" if item.get("method") else ""
            print(
                f"- expected={expected:<20} predicted={predicted:<20}"
                f"{answered_by} subject={preview}"
            )


def build_comparison(
    report: dict[str, Any],
    reference: dict[str, Any],
    *,
    promotion_margin: float,
) -> dict[str, Any]:
    """
    Score this run against the rules-only run of the same dataset.

    The question "do the learned layers help?" has been answered in prose for
    months and measured by nothing: CI runs rules, and hybrid under the
    `deterministic` profile that switches the learned layers off, which is why
    both committed baselines read the same 0.9791. A delta computed here, in the
    same invocation and over the same examples, is the smallest thing that makes
    the answer a number rather than a claim.

    ``promotable`` is deliberately not a pass/fail. Being behind rules is the
    status quo, and a gate that failed for it would be red on day one and
    deleted by week two; what matters is that the number is printed, pinned in
    the committed baseline, and cannot move without showing up in a diff.
    """
    current_overall = report.get("overall", {})
    reference_overall = reference.get("overall", {})

    delta = {
        metric: float(current_overall.get(metric, 0.0)) - float(reference_overall.get(metric, 0.0))
        for metric in ("accuracy", "macro_f1", "weighted_f1")
    }
    delta["misclassified"] = int(current_overall.get("misclassified", 0)) - int(
        reference_overall.get("misclassified", 0)
    )

    macro_delta = delta["macro_f1"]
    if macro_delta > 0:
        verdict = "ahead_of_rules"
    elif macro_delta < 0:
        verdict = "behind_rules"
    else:
        verdict = "level_with_rules"

    # Which examples changed hands. A macro-F1 delta says the learned layers cost
    # two examples; this says which two, and which layer answered them -- the
    # difference between a number to argue about and a defect to work on.
    reference_mismatches = {
        str(item.get("subject", "")): item
        for item in reference.get("mismatches", [])
        if isinstance(item, dict)
    }
    current_mismatches = {
        str(item.get("subject", "")): item
        for item in report.get("mismatches", [])
        if isinstance(item, dict)
    }
    fixed = [
        reference_mismatches[subject]
        for subject in reference_mismatches
        if subject not in current_mismatches
    ]
    broken = [
        current_mismatches[subject]
        for subject in current_mismatches
        if subject not in reference_mismatches
    ]

    return {
        "reference_mode": reference.get("meta", {}).get("mode", "rules"),
        "reference_overall": reference_overall,
        "reference_layers": reference.get("layers", {}),
        "fixed_vs_reference": fixed,
        "broken_vs_reference": broken,
        "delta": delta,
        "verdict": verdict,
        "promotion_margin": promotion_margin,
        # The single bit the promotion policy turns on. False today, and the day
        # it flips the committed baseline diff dates the event.
        "promotable": macro_delta >= promotion_margin,
    }


def print_comparison(report: dict[str, Any]) -> None:
    """Print the rules-vs-this-run table."""
    comparison = report.get("comparison")
    if not comparison:
        return

    meta = report.get("meta", {})
    this_run = meta.get("mode", "current")
    if meta.get("hybrid_profile"):
        this_run = f"{this_run}/{meta['hybrid_profile']}"
    reference_mode = comparison.get("reference_mode", "rules")

    current_overall = report.get("overall", {})
    reference_overall = comparison.get("reference_overall", {})
    delta = comparison.get("delta", {})

    print(f"\n=== {reference_mode} vs {this_run} ===")
    print(f"{'metric':<16}{reference_mode:>12}{this_run:>16}{'delta':>12}")
    for metric in ("accuracy", "macro_f1", "weighted_f1"):
        print(
            f"{metric:<16}{float(reference_overall.get(metric, 0.0)):>12.4f}"
            f"{float(current_overall.get(metric, 0.0)):>16.4f}"
            f"{float(delta.get(metric, 0.0)):>+12.4f}"
        )
    print(
        f"{'misclassified':<16}{int(reference_overall.get('misclassified', 0)):>12}"
        f"{int(current_overall.get('misclassified', 0)):>16}"
        f"{int(delta.get('misclassified', 0)):>+12}"
    )

    # In both lists `by=` names the layer that produced the WRONG answer, in
    # whichever of the two runs got it wrong.
    for heading, key in (
        (f"fixed vs {reference_mode} (wrong there, right here)", "fixed_vs_reference"),
        (f"broken vs {reference_mode} (right there, wrong here)", "broken_vs_reference"),
    ):
        items = comparison.get(key) or []
        print(f"\n{heading}: {len(items)}")
        for item in items:
            answered_by = f" by={item['method']}" if item.get("method") else ""
            print(
                f"- expected={item.get('expected', ''):<20} "
                f"predicted={item.get('predicted', ''):<20}{answered_by} "
                f"subject={item.get('subject', '')}"
            )

    margin = float(comparison.get("promotion_margin", PROMOTION_MARGIN))
    macro_delta = float(delta.get("macro_f1", 0.0))
    print(
        f"verdict: {comparison.get('verdict')} "
        f"({macro_delta:+.4f} macro-F1; promotion needs >= {margin:+.4f}) -> "
        f"promotable={comparison.get('promotable')}"
    )


async def run_evaluation(
    dataset: Path,
    mode: str,
    *,
    hybrid_profile: str,
    compare_rules: bool = False,
    promotion_margin: float = PROMOTION_MARGIN,
) -> dict[str, Any]:
    await init_db()
    examples = load_dataset(dataset)
    expected = [item.label for item in examples]
    predicted, methods, classifier = await predict_labels(
        examples,
        mode=mode,
        hybrid_profile=hybrid_profile,
    )
    report = compute_report(
        expected, predicted, examples, dataset_path=dataset, mode=mode, methods=methods
    )
    # Which layer answered, and how often. Recorded in the report so the artifact
    # itself says whether the ML path ran, rather than leaving that to be inferred
    # from a score that rules alone can reproduce.
    report["layers"] = dict(Counter(methods))
    # Which artifacts answered, so the score can be traced back to them later.
    report["artifacts"] = _collect_artifact_provenance(classifier)
    # The corpus, by content rather than by filename: a baseline is only a
    # baseline for the dataset it was measured on, and datasets get edited.
    report["meta"]["dataset_sha256"] = _sha256(dataset)
    if mode == "hybrid":
        report["meta"]["hybrid_profile"] = hybrid_profile

    if compare_rules:
        reference_predicted, reference_methods, _ = await predict_labels(
            examples,
            mode="rules",
            hybrid_profile="full",
        )
        reference = compute_report(
            expected,
            reference_predicted,
            examples,
            dataset_path=dataset,
            mode="rules",
            methods=reference_methods,
        )
        reference["layers"] = dict(Counter(reference_methods))
        report["comparison"] = build_comparison(
            report, reference, promotion_margin=promotion_margin
        )

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate classifier on a labeled JSONL dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=["rules", "hybrid"], default="rules")
    parser.add_argument(
        "--hybrid-profile",
        choices=["full", "deterministic"],
        default="full",
        help=(
            "Hybrid evaluation profile. "
            "'deterministic' disables stateful semantic layers for machine-stable CI gating."
        ),
    )
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="Allowed drop when comparing against baseline metrics",
    )
    parser.add_argument(
        "--min-macro-f1",
        type=float,
        default=None,
        help="Absolute macro-F1 floor that must be met",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write current report to --baseline and skip non-regression checks",
    )
    parser.add_argument(
        "--max-mismatches",
        type=int,
        default=15,
        help="How many mismatches to print",
    )
    parser.add_argument(
        "--allow-degraded-layers",
        action="store_true",
        help=(
            "Permit a --mode hybrid --hybrid-profile full run in which no semantic "
            "layer answered. Off by default: such a run measures the rules "
            "classifier and reports it as hybrid."
        ),
    )
    parser.add_argument(
        "--compare-rules",
        action="store_true",
        help=(
            "Also run the rules classifier over the same dataset and report the "
            "delta. This is the only measurement of whether the learned layers "
            "help; it never fails the run on its own."
        ),
    )
    parser.add_argument(
        "--promotion-margin",
        type=float,
        default=PROMOTION_MARGIN,
        help=(
            "Macro-F1 margin over rules-only required before a learned layer is "
            "promotable (see docs/ML_PROMOTION_POLICY.md). Reported, not enforced."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode != "hybrid" and args.hybrid_profile != "full":
        print("\nFAIL: --hybrid-profile is only valid when --mode hybrid")
        return 1

    report = asyncio.run(
        run_evaluation(
            args.dataset,
            args.mode,
            hybrid_profile=args.hybrid_profile,
            compare_rules=args.compare_rules,
            promotion_margin=args.promotion_margin,
        )
    )
    baseline_path = args.baseline or DEFAULT_BASELINES[args.mode]

    print_summary(report, max_mismatches=args.max_mismatches)
    print_comparison(report)

    if args.output is not None:
        _write_json(args.output, report)
        print(f"\nSaved report: {args.output}")

    # Before any pass/fail verdict, and before --update-baseline can write this
    # report over the committed one: a hybrid run whose ML layers never loaded
    # must not be allowed to become the baseline that future runs are judged by.
    if not args.allow_degraded_layers:
        layer_failures = _assert_layers_exercised(
            report, mode=args.mode, hybrid_profile=args.hybrid_profile
        )
        if layer_failures:
            print("\nFAIL: the evaluated classifier is not the one that was requested")
            for failure in layer_failures:
                print(f"- {failure}")
            return 1

    if args.min_macro_f1 is not None:
        macro_f1 = float(report["overall"]["macro_f1"])
        if macro_f1 < args.min_macro_f1:
            print(
                f"\nFAIL: macro_f1 {macro_f1:.4f} is below "
                f"required floor {args.min_macro_f1:.4f}"
            )
            return 1

    if args.update_baseline:
        _write_json(baseline_path, report)
        print(f"\nUpdated baseline: {baseline_path}")
        return 0

    if baseline_path.exists():
        baseline = _read_json(baseline_path)
        failures = compare_against_baseline(report, baseline, tolerance=args.tolerance)
        if failures:
            print("\nFAIL: non-regression checks failed")
            for failure in failures:
                print(f"- {failure}")
            return 1
        print("\nPASS: non-regression checks passed")
    else:
        print(f"\nNo baseline found at {baseline_path}; skipping regression checks")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
