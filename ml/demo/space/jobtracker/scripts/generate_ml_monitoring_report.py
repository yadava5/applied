#!/usr/bin/env python3
"""Generate ML monitoring reports with trend/drift/alert signals."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import select

from jobtracker.database import get_session, init_db
from jobtracker.database.models import Email, EmailCategory, TrainingData

JOB_CATEGORIES = [
    EmailCategory.APPLIED,
    EmailCategory.PENDING_APPLICATION,
    EmailCategory.INTERVIEW,
    EmailCategory.REJECTION,
    EmailCategory.OFFER,
    EmailCategory.ASSESSMENT,
    EmailCategory.FOLLOW_UP,
]


@dataclass(frozen=True)
class MonitoringThresholds:
    low_confidence_threshold: float
    low_confidence_growth_alert_pct: float
    low_confidence_delta_alert_count: int
    min_previous_low_confidence_volume: int
    min_distribution_volume: int
    distribution_drift_alert_pp: float
    confusion_pair_alert_count: int


def _normalize_category(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value).lower()


def _parse_csv_list(raw: str) -> list[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def _parse_confusion_pairs(raw: str) -> list[tuple[str, str]]:
    tokens = _parse_csv_list(raw)
    if not tokens:
        return []

    allowed = {category.value for category in JOB_CATEGORIES}
    pairs: list[tuple[str, str]] = []
    for token in tokens:
        if ":" not in token:
            raise ValueError(
                f"Invalid confusion pair '{token}'. Use 'label_a:label_b' format."
            )
        left, right = [part.strip() for part in token.split(":", 1)]
        if left not in allowed or right not in allowed:
            raise ValueError(
                f"Invalid confusion pair '{token}'. Allowed labels: {', '.join(sorted(allowed))}"
            )
        if left == right:
            continue
        pairs.append((left, right))
    return pairs


def _safe_pct(delta: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return (float(delta) / float(previous)) * 100.0


def _distribution_drift(
    current_counts: dict[str, int],
    previous_counts: dict[str, int],
    labels: list[str],
) -> dict[str, Any]:
    current_total = sum(current_counts.values())
    previous_total = sum(previous_counts.values())

    rows: list[dict[str, Any]] = []
    abs_sum = 0.0

    for label in labels:
        current_share = (
            float(current_counts.get(label, 0)) / float(current_total)
            if current_total > 0
            else 0.0
        )
        previous_share = (
            float(previous_counts.get(label, 0)) / float(previous_total)
            if previous_total > 0
            else 0.0
        )
        delta_pp = (current_share - previous_share) * 100.0
        abs_delta_pp = abs(delta_pp)
        abs_sum += abs_delta_pp
        rows.append(
            {
                "label": label,
                "current_share_pct": round(current_share * 100.0, 4),
                "previous_share_pct": round(previous_share * 100.0, 4),
                "delta_pp": round(delta_pp, 4),
                "abs_delta_pp": round(abs_delta_pp, 4),
            }
        )

    rows_sorted = sorted(rows, key=lambda row: row["abs_delta_pp"], reverse=True)
    max_row = rows_sorted[0] if rows_sorted else None
    drift_score_pp = round(abs_sum / 2.0, 4)

    return {
        "current_total": current_total,
        "previous_total": previous_total,
        "drift_score_pp": drift_score_pp,
        "max_label_drift": max_row,
        "by_label": rows_sorted,
    }


def _build_alerts(
    *,
    thresholds: MonitoringThresholds,
    low_conf_current: int,
    low_conf_previous: int,
    drift_summary: dict[str, Any],
    confusion_pair_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    low_conf_delta = low_conf_current - low_conf_previous
    low_conf_growth_pct = _safe_pct(low_conf_delta, low_conf_previous)

    if (
        low_conf_previous >= thresholds.min_previous_low_confidence_volume
        and low_conf_growth_pct is not None
        and low_conf_growth_pct >= thresholds.low_confidence_growth_alert_pct
    ):
        alerts.append(
            {
                "severity": "warning",
                "metric": "low_confidence_growth_pct",
                "value": round(low_conf_growth_pct, 4),
                "threshold": thresholds.low_confidence_growth_alert_pct,
                "message": "Low-confidence volume growth exceeded threshold.",
            }
        )

    if low_conf_delta >= thresholds.low_confidence_delta_alert_count:
        alerts.append(
            {
                "severity": "warning",
                "metric": "low_confidence_delta",
                "value": low_conf_delta,
                "threshold": thresholds.low_confidence_delta_alert_count,
                "message": "Absolute low-confidence delta exceeded threshold.",
            }
        )

    max_label_drift = drift_summary.get("max_label_drift")
    if (
        max_label_drift
        and int(drift_summary.get("current_total", 0)) >= thresholds.min_distribution_volume
        and int(drift_summary.get("previous_total", 0)) >= thresholds.min_distribution_volume
        and float(max_label_drift["abs_delta_pp"]) >= thresholds.distribution_drift_alert_pp
    ):
        alerts.append(
            {
                "severity": "warning",
                "metric": "max_label_distribution_drift_pp",
                "value": float(max_label_drift["abs_delta_pp"]),
                "threshold": thresholds.distribution_drift_alert_pp,
                "message": (
                    "Label distribution drift exceeded threshold "
                    f"for {max_label_drift['label']}."
                ),
            }
        )

    for pair_signal in confusion_pair_signals:
        if pair_signal["low_confidence_total"] >= thresholds.confusion_pair_alert_count:
            alerts.append(
                {
                    "severity": "warning",
                    "metric": "confusion_pair_low_confidence_total",
                    "pair": pair_signal["pair"],
                    "value": pair_signal["low_confidence_total"],
                    "threshold": thresholds.confusion_pair_alert_count,
                    "message": (
                        "Repeated low-confidence volume for confusion pair "
                        f"{pair_signal['pair'][0]} vs {pair_signal['pair'][1]}"
                    ),
                }
            )

    return alerts


async def _count_total_snapshot() -> tuple[int, int]:
    async with get_session() as session:
        total_emails = int((await session.exec(select(func.count(Email.id)))).one())
        total_training = int((await session.exec(select(func.count(TrainingData.id)))).one())
    return total_emails, total_training


async def _count_needs_review(low_confidence_threshold: float) -> int:
    async with get_session() as session:
        needs_review = int(
            (
                await session.exec(
                    select(func.count(Email.id)).where(Email.user_corrected.is_(False)).where(
                        or_(
                            Email.classified_as == EmailCategory.NEEDS_REVIEW,
                            and_(
                                Email.classified_as.in_(JOB_CATEGORIES),
                                or_(
                                    Email.classification_confidence.is_(None),
                                    Email.classification_confidence < low_confidence_threshold,
                                ),
                            ),
                        )
                    )
                )
            ).one()
        )
    return needs_review


async def _count_emails_by_category(
    *,
    start: datetime,
    end: datetime,
    uncorrected_only: bool,
    low_confidence_threshold: float | None,
) -> dict[str, int]:
    stmt = (
        select(Email.classified_as, func.count(Email.id))
        .where(Email.classified_as.in_(JOB_CATEGORIES))
        .where(Email.received_at >= start)
        .where(Email.received_at < end)
    )

    if uncorrected_only:
        stmt = stmt.where(Email.user_corrected.is_(False))

    if low_confidence_threshold is not None:
        stmt = stmt.where(
            or_(
                Email.classification_confidence.is_(None),
                Email.classification_confidence < low_confidence_threshold,
            )
        )

    stmt = stmt.group_by(Email.classified_as)

    async with get_session() as session:
        rows = (await session.exec(stmt)).all()

    output: dict[str, int] = {}
    for row in rows:
        label = _normalize_category(row[0])
        output[label] = int(row[1])
    return output


async def _count_corrections_by_label(
    *,
    start: datetime,
    end: datetime,
    real_sources: list[str],
) -> dict[str, int]:
    stmt = (
        select(TrainingData.label, func.count(TrainingData.id))
        .where(TrainingData.source.in_(real_sources))
        .where(TrainingData.created_at >= start)
        .where(TrainingData.created_at < end)
        .group_by(TrainingData.label)
    )

    async with get_session() as session:
        rows = (await session.exec(stmt)).all()

    return {str(row[0]): int(row[1]) for row in rows}


async def build_monitoring_payload(
    *,
    now_utc: datetime,
    days: int,
    thresholds: MonitoringThresholds,
    confusion_pairs: list[tuple[str, str]],
    real_sources: list[str],
) -> dict[str, Any]:
    await init_db()

    current_start = now_utc - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    total_emails, total_training = await _count_total_snapshot()
    needs_review_count = await _count_needs_review(thresholds.low_confidence_threshold)

    low_conf_current = await _count_emails_by_category(
        start=current_start,
        end=now_utc,
        uncorrected_only=True,
        low_confidence_threshold=thresholds.low_confidence_threshold,
    )
    low_conf_previous = await _count_emails_by_category(
        start=previous_start,
        end=current_start,
        uncorrected_only=True,
        low_confidence_threshold=thresholds.low_confidence_threshold,
    )

    dist_current = await _count_emails_by_category(
        start=current_start,
        end=now_utc,
        uncorrected_only=True,
        low_confidence_threshold=None,
    )
    dist_previous = await _count_emails_by_category(
        start=previous_start,
        end=current_start,
        uncorrected_only=True,
        low_confidence_threshold=None,
    )

    corrections_current = await _count_corrections_by_label(
        start=current_start,
        end=now_utc,
        real_sources=real_sources,
    )
    corrections_previous = await _count_corrections_by_label(
        start=previous_start,
        end=current_start,
        real_sources=real_sources,
    )

    label_order = [category.value for category in JOB_CATEGORIES]
    drift_summary = _distribution_drift(
        current_counts=dist_current,
        previous_counts=dist_previous,
        labels=label_order,
    )

    low_conf_current_total = sum(low_conf_current.values())
    low_conf_previous_total = sum(low_conf_previous.values())
    low_conf_delta = low_conf_current_total - low_conf_previous_total
    low_conf_growth_pct = _safe_pct(low_conf_delta, low_conf_previous_total)

    corrections_current_total = sum(corrections_current.values())
    corrections_previous_total = sum(corrections_previous.values())

    confusion_pair_signals: list[dict[str, Any]] = []
    for left, right in confusion_pairs:
        pair_signal = {
            "pair": [left, right],
            "low_confidence_total": low_conf_current.get(left, 0)
            + low_conf_current.get(right, 0),
            "low_confidence_by_label": {
                left: low_conf_current.get(left, 0),
                right: low_conf_current.get(right, 0),
            },
            "corrections_total": corrections_current.get(left, 0)
            + corrections_current.get(right, 0),
            "corrections_by_label": {
                left: corrections_current.get(left, 0),
                right: corrections_current.get(right, 0),
            },
        }
        confusion_pair_signals.append(pair_signal)

    alerts = _build_alerts(
        thresholds=thresholds,
        low_conf_current=low_conf_current_total,
        low_conf_previous=low_conf_previous_total,
        drift_summary=drift_summary,
        confusion_pair_signals=confusion_pair_signals,
    )

    return {
        "generated_at_utc": now_utc.isoformat(),
        "window_days": days,
        "window": {
            "current_start_utc": current_start.isoformat(),
            "current_end_utc": now_utc.isoformat(),
            "previous_start_utc": previous_start.isoformat(),
            "previous_end_utc": current_start.isoformat(),
        },
        "thresholds": {
            "low_confidence_threshold": thresholds.low_confidence_threshold,
            "low_confidence_growth_alert_pct": thresholds.low_confidence_growth_alert_pct,
            "low_confidence_delta_alert_count": thresholds.low_confidence_delta_alert_count,
            "min_previous_low_confidence_volume": thresholds.min_previous_low_confidence_volume,
            "min_distribution_volume": thresholds.min_distribution_volume,
            "distribution_drift_alert_pp": thresholds.distribution_drift_alert_pp,
            "confusion_pair_alert_count": thresholds.confusion_pair_alert_count,
        },
        "snapshot": {
            "total_emails": total_emails,
            "total_training_examples": total_training,
            "needs_review_count": needs_review_count,
            "real_sources": real_sources,
        },
        "low_confidence": {
            "current_total": low_conf_current_total,
            "previous_total": low_conf_previous_total,
            "delta": low_conf_delta,
            "growth_pct": round(low_conf_growth_pct, 4)
            if low_conf_growth_pct is not None
            else None,
            "current_by_label": dict(sorted(low_conf_current.items())),
            "previous_by_label": dict(sorted(low_conf_previous.items())),
        },
        "distribution": {
            "current_by_label": dict(sorted(dist_current.items())),
            "previous_by_label": dict(sorted(dist_previous.items())),
            "drift": drift_summary,
        },
        "user_corrections": {
            "current_total": corrections_current_total,
            "previous_total": corrections_previous_total,
            "delta": corrections_current_total - corrections_previous_total,
            "current_by_label": dict(sorted(corrections_current.items())),
            "previous_by_label": dict(sorted(corrections_previous.items())),
        },
        "confusion_pair_signals": confusion_pair_signals,
        "alerts": alerts,
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []

    thresholds = payload["thresholds"]
    snapshot = payload["snapshot"]
    low_confidence = payload["low_confidence"]
    distribution = payload["distribution"]
    user_corrections = payload["user_corrections"]

    lines.append("# ML Monitoring Report")
    lines.append("")
    lines.append(f"Generated at: {payload['generated_at_utc']} UTC")
    lines.append(f"Window: last {payload['window_days']} days")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- total_emails: {snapshot['total_emails']}")
    lines.append(f"- total_training_examples: {snapshot['total_training_examples']}")
    lines.append(f"- needs_review_count: {snapshot['needs_review_count']}")
    lines.append("")

    lines.append("## Thresholds")
    lines.append(
        f"- low_confidence_threshold: < {thresholds['low_confidence_threshold']:.2f}"
    )
    lines.append(
        f"- low_confidence_growth_alert_pct: >= {thresholds['low_confidence_growth_alert_pct']:.1f}%"
    )
    lines.append(
        f"- low_confidence_delta_alert_count: >= {thresholds['low_confidence_delta_alert_count']}"
    )
    lines.append(
        f"- min_distribution_volume: >= {thresholds['min_distribution_volume']} each window"
    )
    lines.append(
        f"- distribution_drift_alert_pp: >= {thresholds['distribution_drift_alert_pp']:.1f} pp"
    )
    lines.append(
        f"- confusion_pair_alert_count: >= {thresholds['confusion_pair_alert_count']}"
    )
    lines.append("")

    lines.append("## Low-Confidence Trend")
    lines.append(f"- current_total: {low_confidence['current_total']}")
    lines.append(f"- previous_total: {low_confidence['previous_total']}")
    lines.append(f"- delta: {low_confidence['delta']:+d}")
    growth = low_confidence["growth_pct"]
    lines.append(f"- growth_pct: {growth:.2f}%" if growth is not None else "- growth_pct: n/a")

    lines.append("")
    lines.append("### Low-Confidence By Label (Current Window)")
    if low_confidence["current_by_label"]:
        for label, count in low_confidence["current_by_label"].items():
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Distribution Drift (Uncorrected Job Labels)")
    max_drift = distribution["drift"].get("max_label_drift")
    lines.append(f"- drift_score_pp: {distribution['drift']['drift_score_pp']:.4f}")
    if max_drift:
        lines.append(
            "- max_label_drift: "
            f"{max_drift['label']} ({max_drift['abs_delta_pp']:.4f} pp)"
        )
    else:
        lines.append("- max_label_drift: n/a")

    lines.append("")
    lines.append("### Top Label Drift")
    top_drift = distribution["drift"]["by_label"][:5]
    if top_drift:
        for row in top_drift:
            lines.append(
                f"- {row['label']}: current={row['current_share_pct']:.4f}% | "
                f"previous={row['previous_share_pct']:.4f}% | delta={row['delta_pp']:+.4f} pp"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Confusion Pair Signals")
    if payload["confusion_pair_signals"]:
        for signal in payload["confusion_pair_signals"]:
            pair = signal["pair"]
            lines.append(
                f"- {pair[0]} vs {pair[1]}: "
                f"low_conf={signal['low_confidence_total']}, "
                f"corrections={signal['corrections_total']}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## User Corrections Trend")
    lines.append(f"- current_total: {user_corrections['current_total']}")
    lines.append(f"- previous_total: {user_corrections['previous_total']}")
    lines.append(f"- delta: {user_corrections['delta']:+d}")

    lines.append("")
    lines.append("### User Corrections By Label (Current Window)")
    if user_corrections["current_by_label"]:
        for label, count in user_corrections["current_by_label"].items():
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Alerts")
    alerts = payload["alerts"]
    if alerts:
        for alert in alerts:
            metric = alert["metric"]
            message = alert["message"]
            value = alert.get("value")
            threshold = alert.get("threshold")
            lines.append(
                f"- [{alert['severity']}] {metric}: {message} "
                f"(value={value}, threshold={threshold})"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Actions")
    lines.append("1. Review and clear high-volume low-confidence categories first.")
    lines.append("2. Prioritize real corrections for labels with low recent correction counts.")
    lines.append("3. Retrain once meaningful corrections are accumulated.")

    return "\n".join(lines) + "\n"


def _to_history_record(payload: dict[str, Any]) -> dict[str, Any]:
    low_conf = payload["low_confidence"]
    drift = payload["distribution"]["drift"]
    user_corr = payload["user_corrections"]

    max_drift = drift.get("max_label_drift")

    return {
        "generated_at_utc": payload["generated_at_utc"],
        "window_days": payload["window_days"],
        "low_confidence_current_total": low_conf["current_total"],
        "low_confidence_previous_total": low_conf["previous_total"],
        "low_confidence_delta": low_conf["delta"],
        "low_confidence_growth_pct": low_conf["growth_pct"],
        "distribution_drift_score_pp": drift["drift_score_pp"],
        "distribution_max_label": max_drift["label"] if max_drift else None,
        "distribution_max_label_drift_pp": max_drift["abs_delta_pp"] if max_drift else None,
        "user_corrections_current_total": user_corr["current_total"],
        "user_corrections_previous_total": user_corr["previous_total"],
        "user_corrections_delta": user_corr["delta"],
        "alerts_count": len(payload["alerts"]),
        "alert_metrics": [alert["metric"] for alert in payload["alerts"]],
    }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _write_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ML monitoring report")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data"
        / "evaluation"
        / "ml_monitoring_report.md",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data"
        / "evaluation"
        / "ml_monitoring_report.json",
    )
    parser.add_argument(
        "--history-jsonl",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "data"
        / "evaluation"
        / "ml_monitoring_history.jsonl",
    )
    parser.add_argument(
        "--append-history",
        action="store_true",
        help="Append condensed record to history JSONL",
    )
    parser.add_argument(
        "--real-sources",
        type=str,
        default="user_correction",
        help="Comma-separated TrainingData sources treated as real signals",
    )
    parser.add_argument(
        "--confusion-pairs",
        type=str,
        default="assessment:follow_up,applied:pending_application",
        help="Comma-separated confusion pairs in label_a:label_b format",
    )
    parser.add_argument("--low-confidence-threshold", type=float, default=0.85)
    parser.add_argument("--low-confidence-growth-alert-pct", type=float, default=25.0)
    parser.add_argument("--low-confidence-delta-alert-count", type=int, default=10)
    parser.add_argument("--min-previous-low-confidence-volume", type=int, default=5)
    parser.add_argument("--min-distribution-volume", type=int, default=20)
    parser.add_argument("--distribution-drift-alert-pp", type=float, default=12.0)
    parser.add_argument("--confusion-pair-alert-count", type=int, default=3)
    parser.add_argument(
        "--emit-github-step-summary",
        action="store_true",
        help="Write markdown report into GITHUB_STEP_SUMMARY when available",
    )
    parser.add_argument(
        "--fail-on-alert",
        action="store_true",
        help="Exit non-zero when alerts are present",
    )
    # Backwards compatibility with previous interface.
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Deprecated alias for --output-md",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.days <= 0:
        raise ValueError("--days must be > 0")
    if not 0.0 <= args.low_confidence_threshold <= 1.0:
        raise ValueError("--low-confidence-threshold must be between 0.0 and 1.0")
    if args.low_confidence_growth_alert_pct < 0.0:
        raise ValueError("--low-confidence-growth-alert-pct must be >= 0.0")
    if args.low_confidence_delta_alert_count < 0:
        raise ValueError("--low-confidence-delta-alert-count must be >= 0")
    if args.min_previous_low_confidence_volume < 0:
        raise ValueError("--min-previous-low-confidence-volume must be >= 0")
    if args.min_distribution_volume < 0:
        raise ValueError("--min-distribution-volume must be >= 0")
    if args.distribution_drift_alert_pp < 0.0:
        raise ValueError("--distribution-drift-alert-pp must be >= 0.0")
    if args.confusion_pair_alert_count < 0:
        raise ValueError("--confusion-pair-alert-count must be >= 0")


def main() -> int:
    args = parse_args()
    _validate_args(args)

    output_md = args.output if args.output is not None else args.output_md

    thresholds = MonitoringThresholds(
        low_confidence_threshold=args.low_confidence_threshold,
        low_confidence_growth_alert_pct=args.low_confidence_growth_alert_pct,
        low_confidence_delta_alert_count=args.low_confidence_delta_alert_count,
        min_previous_low_confidence_volume=args.min_previous_low_confidence_volume,
        min_distribution_volume=args.min_distribution_volume,
        distribution_drift_alert_pp=args.distribution_drift_alert_pp,
        confusion_pair_alert_count=args.confusion_pair_alert_count,
    )

    real_sources = _parse_csv_list(args.real_sources)
    if not real_sources:
        raise ValueError("--real-sources must include at least one source")

    confusion_pairs = _parse_confusion_pairs(args.confusion_pairs)

    now_utc = datetime.utcnow()
    payload = asyncio.run(
        build_monitoring_payload(
            now_utc=now_utc,
            days=args.days,
            thresholds=thresholds,
            confusion_pairs=confusion_pairs,
            real_sources=real_sources,
        )
    )

    markdown = render_markdown_report(payload)

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(markdown, encoding="utf-8")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.append_history:
        _append_jsonl(args.history_jsonl, _to_history_record(payload))

    if args.emit_github_step_summary:
        _write_step_summary(markdown)

    print(f"Wrote monitoring markdown: {output_md}")
    print(f"Wrote monitoring json: {args.output_json}")
    if args.append_history:
        print(f"Appended history record: {args.history_jsonl}")

    alerts = payload["alerts"]
    if alerts:
        for alert in alerts:
            print(
                "ALERT: "
                f"{alert['metric']} value={alert.get('value')} "
                f"threshold={alert.get('threshold')}"
            )
        if args.fail_on_alert:
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
