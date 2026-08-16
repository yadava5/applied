#!/usr/bin/env python3
"""Build benchmark history artifacts from baseline evaluation files."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


# `cascade` is `--mode hybrid --hybrid-profile full` with the learned layers
# actually answering -- recorded by scripts/cascade_gate.sh, which refuses to
# write a baseline in which they did not. It is listed as its own mode rather
# than folded into `hybrid` because the reader's question is "does the ML help?"
# and the answer is the gap between this row and the `rules` row of the same
# version. Without the row, the table's only hybrid v3 entry is the
# deterministic one, which is the regexes wearing the cascade's name.
BASELINE_RE = re.compile(r"^baseline_(rules|hybrid|cascade)_v(\d+)\.json$")


@dataclass
class BenchmarkRow:
    mode: str
    version: int
    dataset: str
    profile: str
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
                # Carried through because dropping it made this table misleading:
                # the v3 hybrid baseline is a `deterministic` run, which disables
                # SetFit and blanks the embedding examples. That is why its row and
                # the rules row agree to four decimal places. Without this column a
                # reader concludes the cascade scores 0.9791; what scores 0.9791 is
                # the cascade with its models switched off.
                profile=str(meta.get("hybrid_profile", "n/a")),
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
                        "profile": row.profile,
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
        "`profile` is the hybrid evaluation profile the baseline was recorded under.",
        "`deterministic` disables SetFit and blanks the embedding examples for",
        "machine-stable CI gating, so a `deterministic` hybrid row measures the",
        "deterministic path -- which is why it matches the `rules` row exactly.",
        "",
        "A `cascade` row is the same classifier with the learned layers switched on",
        "and a SetFit checkpoint loaded, recorded by `scripts/cascade_gate.sh`. Its",
        "gap to the `rules` row of the same version is the only measurement of what",
        "the learned layers are worth. It is not produced by CI: no checkpoint ships",
        "in this repository, so a GitHub-hosted runner has nothing to load.",
        "",
        "| mode | version | profile | dataset | accuracy | macro_f1 | weighted_f1 | misclassified |",
        "|------|---------|---------|---------|----------|----------|-------------|---------------|",
    ]

    for row in rows:
        lines.append(
            f"| {row.mode} | v{row.version} | {row.profile} | `{row.dataset}` | {row.accuracy:.4f} | "
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
