#!/usr/bin/env python3
"""
Per-layer latency for the hybrid classifier.

The accuracy of this cascade is measured (``evaluate_classifier.py``); its cost
was not. That gap matters more than it looks, because the layers differ in cost
by orders of magnitude — a regex sweep against a transformer forward pass — and
an aggregate "mean latency" over the whole cascade is a number about the *mix* of
inputs, not about the system. Change the corpus and the mean moves without a line
of code changing.

So this reports **per layer**, and reports which layer answered each example
alongside the timing. A latency figure for "the classifier" that does not say
which layer produced it cannot be compared with anything, including its own
earlier self.

Two things are deliberately measured the way they are:

**Warm, not cold.** A warmup pass runs before timing so model load and lazy
imports are excluded. Cold-start is a real cost and a different question; mixing
it in would put a one-off multi-second model load into the same distribution as
a 50-microsecond regex match and make the percentiles meaningless.

**Percentiles, not means.** A cascade's cost distribution is multi-modal by
construction — that is what a cascade *is*. The mean of a bimodal distribution
describes neither mode. p50 and p95 per layer do.

Usage:
    python -m jobtracker.scripts.benchmark_classifier_latency
    python -m jobtracker.scripts.benchmark_classifier_latency --repetitions 5 --output out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobtracker.classifier.hybrid import HybridClassifier
from jobtracker.database import init_db
from jobtracker.scripts.evaluate_classifier import SEMANTIC_LAYERS, load_dataset

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = BACKEND_DIR / "data" / "evaluation" / "classifier_eval_v3.jsonl"


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Explicit because numpy's default is interpolated
    and the two disagree on small samples — 96 examples is a small sample."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, int(round(pct / 100.0 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


async def measure(
    dataset: Path, repetitions: int
) -> tuple[dict[str, list[float]], list[dict[str, Any]]]:
    await init_db()
    examples = load_dataset(dataset)
    classifier = HybridClassifier()

    # Warmup. The first classify() pays for lazy imports and model load; folding
    # that into the sample would swamp every subsequent measurement.
    for item in examples[: min(8, len(examples))]:
        await classifier.classify(item.subject, item.body_text, item.sender_email)

    by_layer: dict[str, list[float]] = defaultdict(list)
    per_example: list[dict[str, Any]] = []

    for rep in range(repetitions):
        for item in examples:
            start = time.perf_counter()
            result = await classifier.classify(
                item.subject, item.body_text, item.sender_email
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            layer = getattr(result, "method", None) or "unknown"
            by_layer[layer].append(elapsed_ms)
            if rep == 0:
                per_example.append(
                    {
                        "subject": item.subject[:80],
                        "layer": layer,
                        "ms": round(elapsed_ms, 4),
                    }
                )

    return by_layer, per_example


def summarise(by_layer: dict[str, list[float]]) -> dict[str, Any]:
    layers: dict[str, Any] = {}
    for name, samples in sorted(by_layer.items()):
        layers[name] = {
            "n": len(samples),
            "p50_ms": round(_percentile(samples, 50), 4),
            "p95_ms": round(_percentile(samples, 95), 4),
            "p99_ms": round(_percentile(samples, 99), 4),
            "min_ms": round(min(samples), 4),
            "max_ms": round(max(samples), 4),
            "mean_ms": round(statistics.fmean(samples), 4),
        }

    everything = [x for samples in by_layer.values() for x in samples]
    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
            "note": (
                "Warm latencies: a warmup pass precedes timing so model load and "
                "lazy imports are excluded. Percentiles are nearest-rank."
            ),
        },
        "layers": layers,
        # Present, but the per-layer numbers are the ones that mean anything.
        # This aggregate is a property of the corpus mix as much as of the code.
        "end_to_end": {
            "n": len(everything),
            "p50_ms": round(_percentile(everything, 50), 4),
            "p95_ms": round(_percentile(everything, 95), 4),
            "p99_ms": round(_percentile(everything, 99), 4),
        },
    }


def print_report(report: dict[str, Any]) -> None:
    print("\n=== Hybrid classifier latency, per layer ===")
    print(f"{'layer':<18}{'n':>6}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'max ms':>10}")
    for name, s in report["layers"].items():
        print(
            f"{name:<18}{s['n']:>6}{s['p50_ms']:>10.3f}{s['p95_ms']:>10.3f}"
            f"{s['p99_ms']:>10.3f}{s['max_ms']:>10.3f}"
        )
    e = report["end_to_end"]
    print(
        f"\n{'end-to-end':<18}{e['n']:>6}{e['p50_ms']:>10.3f}{e['p95_ms']:>10.3f}"
        f"{e['p99_ms']:>10.3f}"
    )
    print(
        "\nThe end-to-end row is a property of this corpus's layer mix as much as "
        "of the code.\nCompare the per-layer rows; compare the aggregate only "
        "against the same dataset."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--require-semantic",
        action="store_true",
        help=(
            "Fail if no semantic layer answered. The cascade degrades to rules "
            "when a model will not load, and a rules-only run would report "
            "flatteringly low latency for a classifier that is not running."
        ),
    )
    args = parser.parse_args()

    by_layer, per_example = asyncio.run(measure(args.dataset, args.repetitions))
    report = summarise(by_layer)
    print_report(report)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(report)
        payload["per_example"] = per_example
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved: {args.output}")

    if args.require_semantic and not any(
        name in SEMANTIC_LAYERS for name in report["layers"]
    ):
        print(
            "\nFAIL: no semantic layer answered — this measures the rules "
            f"classifier. Layers seen: {sorted(report['layers'])}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
