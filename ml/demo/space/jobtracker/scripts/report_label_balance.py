#!/usr/bin/env python3
"""Report training-data label balance with real-data-priority view."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from sqlalchemy import text

from jobtracker.database import get_session, init_db

CORE_LABELS = [
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
    "follow_up",
    "other",
]


def _parse_sources(raw: str) -> set[str]:
    return {token.strip() for token in raw.split(",") if token.strip()}


async def build_report(target_per_label: int, real_sources: set[str]) -> str:
    await init_db()

    counts_by_source_label: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    async with get_session() as session:
        result = await session.exec(
            text(
                """
                SELECT COALESCE(source, '<null>') as source, label, COUNT(*)
                FROM training_data
                GROUP BY source, label
                """
            )
        )
        for row in result.fetchall():
            source, label, count = row
            counts_by_source_label[str(source)][str(label)] = int(count)

    all_totals: dict[str, int] = defaultdict(int)
    real_totals: dict[str, int] = defaultdict(int)

    for source, labels in counts_by_source_label.items():
        for label, count in labels.items():
            all_totals[label] += count
            if source in real_sources:
                real_totals[label] += count

    lines: list[str] = []
    lines.append("# Label Balance Report")
    lines.append("")
    lines.append(f"Target per label (real-priority): {target_per_label}")
    lines.append(f"Real sources: {', '.join(sorted(real_sources)) if real_sources else '(none)'}")
    lines.append("")
    lines.append("## By Source")
    for source in sorted(counts_by_source_label.keys()):
        pairs = ", ".join(
            f"{label}={count}" for label, count in sorted(counts_by_source_label[source].items())
        )
        lines.append(f"- {source}: {pairs}")

    lines.append("")
    lines.append("## Real-Priority Gaps")
    for label in CORE_LABELS:
        current = real_totals.get(label, 0)
        gap = max(0, target_per_label - current)
        lines.append(f"- {label}: real={current}, gap={gap}")

    lines.append("")
    lines.append("## All-Data Totals")
    for label in CORE_LABELS:
        lines.append(f"- {label}: total={all_totals.get(label, 0)}")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report label balance with real-data priority")
    parser.add_argument("--target-per-label", type=int, default=25)
    parser.add_argument(
        "--real-sources",
        type=str,
        default="user_correction",
        help="Comma-separated sources treated as real data",
    )
    parser.add_argument("--output", type=str, default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    real_sources = _parse_sources(args.real_sources)
    report = asyncio.run(build_report(args.target_per_label, real_sources))

    if args.output:
        from pathlib import Path

        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Wrote report: {out}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
