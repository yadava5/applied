#!/usr/bin/env python3
"""Build benchmark history artifacts from baseline evaluation files."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


BASELINE_RE = re.compile(r"^baseline_(rules|hybrid)_v(\d+)\.json$")


@dataclass
class BenchmarkRow:
    mode: str
    version: int
    dataset: str
    accuracy: float
    macro_f1: float
    weighted_f1: float
    misclassified: int


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid json object in {path}")
    return data


def collect_rows(evaluation_dir: Path) -> list[BenchmarkRow]:
    rows: list[BenchmarkRow] = []
    for path in sorted(evaluation_dir.glob("baseline_*_v*.json")):
        match = BASELINE_RE.match(path.name)
        if not match:
            continue

        mode = match.group(1)
        version = int(match.group(2))
        payload = _load_json(path)

        meta = payload.get("meta", {})
        overall = payload.get("overall", {})

        rows.append(
            BenchmarkRow(
                mode=mode,
                version=version,
                dataset=str(meta.get("dataset", "")),
                accuracy=float(overall.get("accuracy", 0.0)),
                macro_f1=float(overall.get("macro_f1", 0.0)),
                weighted_f1=float(overall.get("weighted_f1", 0.0)),
                misclassified=int(overall.get("misclassified", 0)),
            )
        )

    rows.sort(key=lambda row: (row.mode, row.version))
    return rows


def write_jsonl(rows: list[BenchmarkRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    {
                        "mode": row.mode,
                        "version": row.version,
                        "dataset": row.dataset,
                        "accuracy": row.accuracy,
                        "macro_f1": row.macro_f1,
                        "weighted_f1": row.weighted_f1,
                        "misclassified": row.misclassified,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def write_markdown(rows: list[BenchmarkRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Benchmark History",
        "",
        "Auto-generated from `baseline_*_v*.json` files.",
        "",
        "| mode | version | dataset | accuracy | macro_f1 | weighted_f1 | misclassified |",
        "|------|---------|---------|----------|----------|-------------|---------------|",
    ]

    for row in rows:
        lines.append(
            f"| {row.mode} | v{row.version} | `{row.dataset}` | {row.accuracy:.4f} | "
            f"{row.macro_f1:.4f} | {row.weighted_f1:.4f} | {row.misclassified} |"
        )

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build benchmark history artifacts")
    parser.add_argument(
        "--evaluation-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "evaluation",
    )
    parser.add_argument(
        "--jsonl-output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "benchmark_history.jsonl",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "benchmark_history.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = collect_rows(args.evaluation_dir)
    if not rows:
        raise SystemExit("No baseline files found")

    write_jsonl(rows, args.jsonl_output)
    write_markdown(rows, args.markdown_output)

    print(f"Wrote {len(rows)} benchmark rows")
    print(f"JSONL: {args.jsonl_output}")
    print(f"Markdown: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
