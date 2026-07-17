#!/usr/bin/env python3
"""Evaluate classifier quality on a labeled JSONL dataset.

This harness produces per-class precision/recall/F1, overall metrics,
and optional non-regression checks against a saved baseline report.
"""

from __future__ import annotations

import argparse
import asyncio
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
) -> list[str]:
    """Run classifier predictions for all examples."""
    predictions: list[str] = []

    if mode == "rules":
        classifier = get_rules_classifier()
        for item in examples:
            result = classifier.classify(item.subject, item.body_text, item.sender_email)
            predictions.append(result.category.value)
        return predictions

    if mode == "hybrid":
        classifier = HybridClassifier()
        _configure_hybrid_profile(classifier, hybrid_profile)
        for item in examples:
            result = await classifier.classify(item.subject, item.body_text, item.sender_email)
            predictions.append(result.category.value)
        return predictions

    raise ValueError(f"Unsupported mode: {mode}")


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
            # Prevent DB/stateful embedding examples from affecting benchmark outcomes.
            embeddings._known_embeddings = []
            embeddings._loaded = True
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

    mismatches = [
        ExampleOutcome(expected=exp, predicted=pred, subject=item.subject)
        for item, exp, pred in zip(examples, expected, predicted, strict=True)
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
            print(f"- expected={expected:<20} predicted={predicted:<20} subject={preview}")


async def run_evaluation(
    dataset: Path,
    mode: str,
    *,
    hybrid_profile: str,
) -> dict[str, Any]:
    await init_db()
    examples = load_dataset(dataset)
    expected = [item.label for item in examples]
    predicted = await predict_labels(
        examples,
        mode=mode,
        hybrid_profile=hybrid_profile,
    )
    report = compute_report(expected, predicted, examples, dataset_path=dataset, mode=mode)
    if mode == "hybrid":
        report["meta"]["hybrid_profile"] = hybrid_profile
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
        )
    )
    baseline_path = args.baseline or DEFAULT_BASELINES[args.mode]

    print_summary(report, max_mismatches=args.max_mismatches)

    if args.output is not None:
        _write_json(args.output, report)
        print(f"\nSaved report: {args.output}")

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
