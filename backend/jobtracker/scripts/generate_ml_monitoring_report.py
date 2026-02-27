#!/usr/bin/env python3
"""Generate periodic ML monitoring report from local database."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from jobtracker.database import get_session, init_db

JOB_CATEGORIES = [
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
    "follow_up",
]


async def build_report(days: int) -> str:
    await init_db()
    since = datetime.utcnow() - timedelta(days=days)

    async with get_session() as session:
        total_emails = int((await session.exec(text("SELECT COUNT(*) FROM emails"))).first()[0])
        total_training = int((await session.exec(text("SELECT COUNT(*) FROM training_data"))).first()[0])

        needs_review_count = int(
            (
                await session.exec(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM emails
                        WHERE user_corrected = 0
                          AND (
                            classified_as = 'needs_review'
                            OR (
                              classification_confidence < 0.85
                              AND classified_as IN (
                                'applied','pending_application','interview','rejection','offer','assessment','follow_up'
                              )
                            )
                          )
                        """
                    )
                )
            ).first()[0]
        )

        low_conf_rows = (
            await session.exec(
                text(
                    """
                    SELECT classified_as, COUNT(*)
                    FROM emails
                    WHERE classification_confidence < 0.85
                      AND classified_as IN (
                        'applied','pending_application','interview','rejection','offer','assessment','follow_up'
                      )
                    GROUP BY classified_as
                    ORDER BY COUNT(*) DESC
                    """
                )
            )
        ).fetchall()

        corrections_rows = (
            await session.exec(
                text(
                    """
                    SELECT label, COUNT(*)
                    FROM training_data
                    WHERE source = 'user_correction'
                      AND created_at >= :since
                    GROUP BY label
                    ORDER BY COUNT(*) DESC
                    """
                ).bindparams(since=since)
            )
        ).fetchall()

    low_conf_by_label = {str(row[0]): int(row[1]) for row in low_conf_rows}
    corrections_by_label = {str(row[0]): int(row[1]) for row in corrections_rows}
    corrections_total = sum(corrections_by_label.values())

    lines: list[str] = []
    lines.append("# ML Monitoring Report")
    lines.append("")
    lines.append(f"Generated at: {datetime.utcnow().isoformat()} UTC")
    lines.append(f"Window: last {days} days")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- total_emails: {total_emails}")
    lines.append(f"- total_training_examples: {total_training}")
    lines.append(f"- needs_review_count: {needs_review_count}")
    lines.append(f"- user_corrections_last_{days}_days: {corrections_total}")

    lines.append("")
    lines.append("## Low-Confidence Job Emails (<0.85)")
    if low_conf_by_label:
        for label in JOB_CATEGORIES:
            if label in low_conf_by_label:
                lines.append(f"- {label}: {low_conf_by_label[label]}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append(f"## User Corrections Last {days} Days")
    if corrections_by_label:
        for label, count in corrections_by_label.items():
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Actions")
    lines.append("1. Review and clear high-volume low-confidence categories first.")
    lines.append("2. Prioritize real corrections for labels with low recent correction counts.")
    lines.append("3. Re-run `scripts/ml_cycle.sh` after meaningful correction volume.")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ML monitoring report")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "ml_monitoring_report.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(build_report(args.days))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote monitoring report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
