#!/usr/bin/env python3
"""Weekly real-signal labeling workflow for ML quality improvement."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, or_
from sqlmodel import select

from jobtracker.config import settings
from jobtracker.database import get_session, init_db
from jobtracker.database.models import Email, EmailCategory, TrainingData

JOB_LABELS = (
    "applied",
    "pending_application",
    "interview",
    "rejection",
    "offer",
    "assessment",
    "follow_up",
)
DEFAULT_TARGET_LABELS = ("offer", "interview", "pending_application")
DEFAULT_CONFUSION_PAIRS = (
    ("assessment", "follow_up"),
    ("applied", "pending_application"),
)
DEFAULT_REAL_SOURCES = ("user_correction",)
DEFAULT_TARGET_PER_LABEL = 25

REASON_LOW_CONFIDENCE = "low_confidence"
REASON_CONFUSION_PAIR = "confusion_pair_focus"
REASON_LOW_SUPPORT = "low_support_category"
REASON_TARGET_SIGNAL = "target_label_signal"

REASON_PRIORITY = {
    REASON_LOW_CONFIDENCE: 1,
    REASON_TARGET_SIGNAL: 2,
    REASON_LOW_SUPPORT: 3,
    REASON_CONFUSION_PAIR: 4,
}

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "data" / "evaluation" / "weekly_labeling"
DEFAULT_TRACKER_PATH = PROJECT_ROOT / "docs" / "ML_EXECUTION_TRACKER.md"

SENSITIVE_COLUMNS = {"subject", "body_text", "body_html", "body_snippet", "snippet"}

TARGET_SIGNAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "offer": (
        "offer letter",
        "formal offer",
        "offer of employment",
        "compensation package",
        "start date",
        "accept this offer",
        "employment agreement",
    ),
    "interview": (
        "interview invitation",
        "schedule interview",
        "phone screen",
        "hiring manager",
        "calendly",
        "availability for",
        "video interview",
    ),
    "pending_application": (
        "complete your application",
        "finish your application",
        "continue your application",
        "application is incomplete",
        "missing information",
        "action required",
        "before we can review your application",
    ),
}


@dataclass
class LabelingCandidate:
    email_id: int
    received_at: datetime | None
    source_account: str
    current_category: str
    confidence: float | None
    classification_method: str | None
    is_reviewed: bool
    reasons: set[str] = field(default_factory=set)
    target_signal_labels: set[str] = field(default_factory=set)


@dataclass
class WeeklyKPI:
    generated_at: datetime
    window_days: int
    real_sources: list[str]
    total_real_examples: int
    current_week_total: int
    previous_week_total: int
    weekly_delta: int
    all_time_by_label: dict[str, int]
    current_week_by_label: dict[str, int]
    previous_week_by_label: dict[str, int]
    latest_model_name: str | None
    latest_model_trained_at: str | None
    latest_model_real_examples: int | None
    latest_model_total_examples: int | None
    latest_model_real_share_pct: float | None


def _parse_csv_list(raw: str) -> list[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def _parse_target_labels(raw: str) -> list[str]:
    labels = _parse_csv_list(raw)
    if not labels:
        raise ValueError("At least one target label is required.")

    invalid = [label for label in labels if label not in JOB_LABELS]
    if invalid:
        raise ValueError(f"Invalid target labels: {', '.join(sorted(set(invalid)))}")
    return labels


def _parse_confusion_pairs(raw: str) -> list[tuple[str, str]]:
    tokens = _parse_csv_list(raw)
    if not tokens:
        raise ValueError("At least one confusion pair is required.")

    pairs: list[tuple[str, str]] = []
    for token in tokens:
        if ":" not in token:
            raise ValueError(
                f"Invalid confusion pair '{token}'. Use 'label_a:label_b' format."
            )
        left, right = [part.strip() for part in token.split(":", 1)]
        if left not in JOB_LABELS or right not in JOB_LABELS:
            raise ValueError(
                f"Invalid confusion pair '{token}'. Labels must be in {', '.join(JOB_LABELS)}"
            )
        if left == right:
            continue
        pairs.append((left, right))

    if not pairs:
        raise ValueError("At least one valid confusion pair is required.")
    return pairs


def _unwrap_email(row: object) -> Email:
    if isinstance(row, Email):
        return row
    if hasattr(row, "__getitem__"):
        return row[0]  # type: ignore[index]
    raise TypeError(f"Unexpected row type from SQLModel query: {type(row)}")


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return ""
    return f"{confidence:.4f}"


def _format_received_at(received_at: datetime | None) -> str:
    if received_at is None:
        return ""
    return received_at.isoformat()


def _candidate_sort_key(candidate: LabelingCandidate) -> tuple[int, float, float]:
    reason_priority = REASON_PRIORITY.get(_primary_reason(candidate), 99)
    confidence_score = candidate.confidence if candidate.confidence is not None else -1.0
    recency_score = candidate.received_at.timestamp() if candidate.received_at is not None else 0.0
    return (reason_priority, confidence_score, -recency_score)


def _primary_reason(candidate: LabelingCandidate) -> str:
    if not candidate.reasons:
        return ""
    return min(candidate.reasons, key=lambda reason: REASON_PRIORITY.get(reason, 99))


async def _fetch_candidates_for_labels(
    *,
    labels: list[str],
    since: datetime,
    query_limit: int,
    low_confidence_threshold: float | None = None,
    max_confidence: float | None = None,
) -> list[LabelingCandidate]:
    enum_labels = [EmailCategory(label) for label in labels]

    stmt = (
        select(Email)
        .where(Email.user_corrected.is_(False))
        .where(Email.classified_as.in_(enum_labels))
        .where(Email.received_at >= since)
    )

    if low_confidence_threshold is not None:
        stmt = stmt.where(
            or_(
                Email.classification_confidence.is_(None),
                Email.classification_confidence < low_confidence_threshold,
            )
        )

    if max_confidence is not None:
        stmt = stmt.where(
            or_(
                Email.classification_confidence.is_(None),
                Email.classification_confidence <= max_confidence,
            )
        )

    stmt = stmt.order_by(
        case(
            (Email.classification_confidence.is_(None), -1.0),
            else_=Email.classification_confidence,
        ),
        Email.received_at.desc(),
    ).limit(query_limit)

    async with get_session() as session:
        rows = (await session.exec(stmt)).all()

    candidates: list[LabelingCandidate] = []
    for row in rows:
        email = _unwrap_email(row)
        if email.id is None:
            continue
        if email.classified_as is None:
            category = "unknown"
        else:
            category = (
                email.classified_as.value
                if hasattr(email.classified_as, "value")
                else str(email.classified_as)
            )
        source_account = (
            email.source_account.value
            if hasattr(email.source_account, "value")
            else str(email.source_account)
        )
        candidates.append(
            LabelingCandidate(
                email_id=int(email.id),
                received_at=email.received_at,
                source_account=str(source_account),
                current_category=category,
                confidence=email.classification_confidence,
                classification_method=email.classification_method,
                is_reviewed=bool(email.is_reviewed),
            )
        )
    return candidates


async def _fetch_candidates_for_target_signal(
    *,
    target_label: str,
    since: datetime,
    query_limit: int,
    max_confidence: float | None = None,
) -> list[LabelingCandidate]:
    patterns = TARGET_SIGNAL_PATTERNS.get(target_label, ())
    if not patterns:
        return []

    signal_clauses = []
    for token in patterns:
        normalized = token.strip().lower()
        if not normalized:
            continue
        like_pattern = f"%{normalized}%"
        signal_clauses.append(func.lower(func.coalesce(Email.subject, "")).like(like_pattern))
        signal_clauses.append(func.lower(func.coalesce(Email.body_text, "")).like(like_pattern))
        signal_clauses.append(func.lower(func.coalesce(Email.body_snippet, "")).like(like_pattern))

    if not signal_clauses:
        return []

    stmt = (
        select(Email)
        .where(Email.user_corrected.is_(False))
        .where(Email.received_at >= since)
        .where(or_(*signal_clauses))
    )

    if max_confidence is not None:
        stmt = stmt.where(
            or_(
                Email.classification_confidence.is_(None),
                Email.classification_confidence <= max_confidence,
            )
        )

    # Prefer potentially misclassified/non-target rows first, then lower confidence.
    stmt = stmt.order_by(
        case(
            (Email.classified_as == EmailCategory(target_label), 1),
            else_=0,
        ),
        case(
            (Email.classification_confidence.is_(None), -1.0),
            else_=Email.classification_confidence,
        ),
        Email.received_at.desc(),
    ).limit(query_limit)

    async with get_session() as session:
        rows = (await session.exec(stmt)).all()

    candidates: list[LabelingCandidate] = []
    for row in rows:
        email = _unwrap_email(row)
        if email.id is None:
            continue
        if email.classified_as is None:
            category = "unknown"
        else:
            category = (
                email.classified_as.value
                if hasattr(email.classified_as, "value")
                else str(email.classified_as)
            )
        source_account = (
            email.source_account.value
            if hasattr(email.source_account, "value")
            else str(email.source_account)
        )
        candidates.append(
            LabelingCandidate(
                email_id=int(email.id),
                received_at=email.received_at,
                source_account=str(source_account),
                current_category=category,
                confidence=email.classification_confidence,
                classification_method=email.classification_method,
                is_reviewed=bool(email.is_reviewed),
            )
        )
    return candidates


def _merge_pool(
    *,
    candidate_map: dict[int, LabelingCandidate],
    pool: list[LabelingCandidate],
    reason: str,
    max_new_candidates: int,
    target_signal_label: str | None = None,
) -> None:
    added = 0
    for candidate in pool:
        existing = candidate_map.get(candidate.email_id)
        if existing is not None:
            existing.reasons.add(reason)
            if target_signal_label is not None:
                existing.target_signal_labels.add(target_signal_label)
            continue

        if added >= max_new_candidates:
            break

        candidate.reasons.add(reason)
        if target_signal_label is not None:
            candidate.target_signal_labels.add(target_signal_label)
        candidate_map[candidate.email_id] = candidate
        added += 1


def _compute_target_support_gaps(
    *,
    target_labels: list[str],
    all_time_by_label: dict[str, int],
    target_per_label: int,
) -> dict[str, dict[str, int]]:
    support: dict[str, dict[str, int]] = {}
    for label in target_labels:
        current_total = int(all_time_by_label.get(label, 0))
        gap = max(target_per_label - current_total, 0)
        support[label] = {"current_total": current_total, "gap_to_target": gap}
    return support


def _allocate_label_quotas(
    *,
    total_limit: int,
    target_labels: list[str],
    support_gaps: dict[str, dict[str, int]],
) -> dict[str, int]:
    if total_limit <= 0 or not target_labels:
        return {}

    labels = list(target_labels)
    raw_weights: dict[str, int] = {}
    for label in labels:
        gap = int(support_gaps.get(label, {}).get("gap_to_target", 0))
        raw_weights[label] = gap if gap > 0 else 1

    weight_sum = sum(raw_weights.values())
    quotas: dict[str, int] = {label: 0 for label in labels}
    remainders: list[tuple[float, str]] = []

    for label in labels:
        exact = (raw_weights[label] * total_limit) / weight_sum
        floor_value = int(exact)
        quotas[label] = floor_value
        remainders.append((exact - floor_value, label))

    assigned = sum(quotas.values())
    for _fractional, label in sorted(remainders, key=lambda item: item[0], reverse=True):
        if assigned >= total_limit:
            break
        quotas[label] += 1
        assigned += 1

    return quotas


def _select_final_candidates(
    *,
    candidates: list[LabelingCandidate],
    limit: int,
    confusion_share_cap: float,
) -> list[LabelingCandidate]:
    if limit <= 0:
        return []
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=_candidate_sort_key)
    confusion_cap = int(limit * confusion_share_cap)
    selected: list[LabelingCandidate] = []
    deferred_confusion: list[LabelingCandidate] = []
    confusion_selected = 0

    for candidate in sorted_candidates:
        primary_reason = _primary_reason(candidate)
        is_confusion_primary = primary_reason == REASON_CONFUSION_PAIR

        if is_confusion_primary and confusion_selected >= confusion_cap:
            deferred_confusion.append(candidate)
            continue

        selected.append(candidate)
        if is_confusion_primary:
            confusion_selected += 1
        if len(selected) >= limit:
            return selected

    # Backfill with deferred confusion candidates if we still need more rows.
    for candidate in deferred_confusion:
        selected.append(candidate)
        if len(selected) >= limit:
            break

    return selected


def write_candidates_csv(path: Path, candidates: list[LabelingCandidate]) -> None:
    fieldnames = [
        "rank",
        "email_id",
        "received_at",
        "source_account",
        "current_category",
        "confidence",
        "classification_method",
        "is_reviewed",
        "selection_reasons",
        "target_signal_labels",
        "reviewed_label",
        "notes",
    ]

    forbidden_columns = SENSITIVE_COLUMNS.intersection(fieldnames)
    if forbidden_columns:
        raise ValueError(
            f"Privacy violation: CSV columns include sensitive fields: {sorted(forbidden_columns)}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, candidate in enumerate(candidates, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "email_id": candidate.email_id,
                    "received_at": _format_received_at(candidate.received_at),
                    "source_account": candidate.source_account,
                    "current_category": candidate.current_category,
                    "confidence": _format_confidence(candidate.confidence),
                    "classification_method": candidate.classification_method or "",
                    "is_reviewed": int(candidate.is_reviewed),
                    "selection_reasons": ";".join(sorted(candidate.reasons)),
                    "target_signal_labels": ";".join(sorted(candidate.target_signal_labels)),
                    "reviewed_label": "",
                    "notes": "",
                }
            )


def _summarize_candidates(candidates: list[LabelingCandidate]) -> dict[str, Any]:
    reason_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    target_signal_counts: dict[str, int] = defaultdict(int)

    for candidate in candidates:
        category_counts[candidate.current_category] += 1
        for reason in candidate.reasons:
            reason_counts[reason] += 1
        for target_label in candidate.target_signal_labels:
            target_signal_counts[target_label] += 1

    return {
        "total_candidates": len(candidates),
        "candidate_ids": [candidate.email_id for candidate in candidates],
        "reason_counts": dict(sorted(reason_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "target_signal_counts": dict(sorted(target_signal_counts.items())),
    }


def _render_candidate_summary_markdown(
    *,
    generated_at: datetime,
    since: datetime,
    low_confidence_threshold: float,
    confusion_share_cap: float,
    target_labels: list[str],
    confusion_pairs: list[tuple[str, str]],
    target_per_label: int,
    target_support: dict[str, dict[str, int]],
    summary_payload: dict[str, Any],
    candidates_csv_path: Path,
) -> str:
    lines: list[str] = []
    lines.append("# Weekly Labeling Batch Summary")
    lines.append("")
    lines.append(f"Generated at: {generated_at.isoformat()} UTC")
    lines.append(f"Window start: {since.isoformat()} UTC")
    lines.append(f"Low-confidence threshold: < {low_confidence_threshold:.2f}")
    lines.append(f"Confusion-pair primary-share cap: {confusion_share_cap:.0%}")
    lines.append(f"Target low-support labels: {', '.join(target_labels)}")
    lines.append(f"Real-signal target per label: {target_per_label}")
    lines.append(
        "Target confusion pairs: "
        + ", ".join([f"{left} vs {right}" for left, right in confusion_pairs])
    )
    lines.append("")
    lines.append("## Selection Summary")
    lines.append(f"- total_candidates: {summary_payload['total_candidates']}")

    lines.append("")
    lines.append("### By Reason")
    reason_counts: dict[str, int] = summary_payload["reason_counts"]
    if reason_counts:
        for reason, count in reason_counts.items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### By Current Category")
    category_counts: dict[str, int] = summary_payload["category_counts"]
    if category_counts:
        for category, count in category_counts.items():
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### By Target Signal Label")
    target_signal_counts: dict[str, int] = summary_payload.get("target_signal_counts", {})
    if target_signal_counts:
        for label, count in target_signal_counts.items():
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Target Label Support (Real)")
    if target_support:
        for label in target_labels:
            support = target_support.get(label, {"current_total": 0, "gap_to_target": 0})
            lines.append(
                f"- {label}: real_total={support['current_total']}, "
                f"gap_to_target={support['gap_to_target']}"
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Candidate IDs")
    candidate_ids: list[int] = summary_payload["candidate_ids"]
    if candidate_ids:
        lines.append("- ids: " + ", ".join(str(email_id) for email_id in candidate_ids))
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Privacy")
    lines.append("- This artifact stores IDs and aggregate counts only.")
    lines.append("- It does not include subjects, snippets, or email body content.")
    lines.append("")
    lines.append("## Artifact")
    lines.append(f"- candidates_csv: `{candidates_csv_path}`")
    lines.append("")
    return "\n".join(lines)


def _load_latest_training_metadata() -> tuple[str | None, dict[str, Any] | None]:
    models_dir = Path(settings.database_dir).expanduser() / "models" / "setfit"
    try:
        if not models_dir.exists() or not models_dir.is_dir():
            return None, None
    except OSError:
        return None, None

    try:
        model_dirs = sorted([item for item in models_dir.iterdir() if item.is_dir()], reverse=True)
    except OSError:
        return None, None

    for model_dir in model_dirs:
        metadata_path = model_dir / "training_metadata.json"
        if not metadata_path.exists():
            continue
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return model_dir.name, payload

    return None, None


def calculate_real_signal_share_from_metadata(
    metadata: dict[str, Any] | None,
    real_sources: set[str],
) -> tuple[int | None, int | None, float | None]:
    if not metadata:
        return None, None, None

    source_counts_raw = metadata.get("source_counts")
    if not isinstance(source_counts_raw, dict):
        return None, None, None

    normalized_source_counts: dict[str, int] = {}
    for source, count in source_counts_raw.items():
        try:
            normalized_source_counts[str(source)] = int(count)
        except (TypeError, ValueError):
            continue

    total = sum(normalized_source_counts.values())
    if total <= 0:
        return 0, 0, None

    real = sum(
        count
        for source, count in normalized_source_counts.items()
        if source in real_sources
    )
    share_pct = (float(real) / float(total)) * 100.0
    return real, total, share_pct


async def _get_training_counts_by_label(
    *,
    real_sources: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, int]:
    stmt = (
        select(TrainingData.label, func.count(TrainingData.id))
        .where(TrainingData.source.in_(real_sources))
    )
    if start is not None:
        stmt = stmt.where(TrainingData.created_at >= start)
    if end is not None:
        stmt = stmt.where(TrainingData.created_at < end)
    stmt = stmt.group_by(TrainingData.label)

    async with get_session() as session:
        rows = (await session.exec(stmt)).all()

    counts: dict[str, int] = {}
    for row in rows:
        label = str(row[0])
        counts[label] = int(row[1])
    return dict(sorted(counts.items()))


async def _build_weekly_kpi(
    *,
    now: datetime,
    window_days: int,
    real_sources: list[str],
) -> WeeklyKPI:
    current_start = now - timedelta(days=window_days)
    previous_start = current_start - timedelta(days=window_days)

    all_time_by_label = await _get_training_counts_by_label(real_sources=real_sources)
    current_week_by_label = await _get_training_counts_by_label(
        real_sources=real_sources,
        start=current_start,
        end=now,
    )
    previous_week_by_label = await _get_training_counts_by_label(
        real_sources=real_sources,
        start=previous_start,
        end=current_start,
    )

    total_real_examples = sum(all_time_by_label.values())
    current_week_total = sum(current_week_by_label.values())
    previous_week_total = sum(previous_week_by_label.values())

    model_name, metadata = _load_latest_training_metadata()
    real_in_latest, total_in_latest, latest_share = calculate_real_signal_share_from_metadata(
        metadata,
        set(real_sources),
    )

    latest_trained_at: str | None = None
    if isinstance(metadata, dict):
        trained_at = metadata.get("trained_at")
        latest_trained_at = str(trained_at) if trained_at else None

    return WeeklyKPI(
        generated_at=now,
        window_days=window_days,
        real_sources=real_sources,
        total_real_examples=total_real_examples,
        current_week_total=current_week_total,
        previous_week_total=previous_week_total,
        weekly_delta=current_week_total - previous_week_total,
        all_time_by_label=all_time_by_label,
        current_week_by_label=current_week_by_label,
        previous_week_by_label=previous_week_by_label,
        latest_model_name=model_name,
        latest_model_trained_at=latest_trained_at,
        latest_model_real_examples=real_in_latest,
        latest_model_total_examples=total_in_latest,
        latest_model_real_share_pct=latest_share,
    )


def render_kpi_markdown(kpi: WeeklyKPI) -> str:
    lines: list[str] = []
    lines.append("### Weekly KPI Snapshot")
    lines.append("")
    lines.append(f"- generated_at_utc: `{kpi.generated_at.isoformat()}`")
    lines.append(f"- real_sources: `{', '.join(kpi.real_sources)}`")
    lines.append(f"- user_correction_total: `{kpi.total_real_examples}`")
    lines.append(f"- user_correction_last_{kpi.window_days}_days: `{kpi.current_week_total}`")
    lines.append(
        f"- user_correction_prev_{kpi.window_days}_days: `{kpi.previous_week_total}`"
    )
    lines.append(f"- user_correction_weekly_delta: `{kpi.weekly_delta:+d}`")

    if (
        kpi.latest_model_real_share_pct is not None
        and kpi.latest_model_real_examples is not None
        and kpi.latest_model_total_examples is not None
    ):
        lines.append(
            "- real_signal_share_latest_retrain: "
            f"`{kpi.latest_model_real_share_pct:.2f}%` "
            f"({kpi.latest_model_real_examples}/{kpi.latest_model_total_examples})"
        )
    else:
        lines.append("- real_signal_share_latest_retrain: `n/a` (no metadata found)")

    if kpi.latest_model_name:
        lines.append(f"- latest_model: `{kpi.latest_model_name}`")
    if kpi.latest_model_trained_at:
        lines.append(f"- latest_model_trained_at: `{kpi.latest_model_trained_at}`")

    lines.append("")
    lines.append("#### Per-Label Real-Signal Totals")
    if kpi.all_time_by_label:
        for label, count in kpi.all_time_by_label.items():
            current = kpi.current_week_by_label.get(label, 0)
            previous = kpi.previous_week_by_label.get(label, 0)
            delta = current - previous
            lines.append(
                f"- {label}: total={count}, "
                f"last_{kpi.window_days}d={current}, "
                f"delta_vs_prev_window={delta:+d}"
            )
    else:
        lines.append("- none")

    lines.append("")
    return "\n".join(lines)


def append_snapshot_to_tracker(
    *,
    tracker_path: Path,
    snapshot_date: datetime,
    kpi_markdown: str,
    summary_payload: dict[str, Any],
    candidates_csv_path: Path,
    summary_md_path: Path,
    summary_json_path: Path,
) -> None:
    heading = f"## Weekly KPI Snapshot ({snapshot_date.strftime('%Y-%m-%d')})"
    block_lines: list[str] = []
    block_lines.append(heading)
    block_lines.append("")
    block_lines.append(kpi_markdown.strip())
    block_lines.append("")
    block_lines.append("### Weekly Labeling Batch")
    block_lines.append(f"- total_candidates: `{summary_payload['total_candidates']}`")
    block_lines.append(
        "- reason_counts: "
        + ", ".join(
            f"{reason}={count}"
            for reason, count in summary_payload["reason_counts"].items()
        )
    )
    block_lines.append(
        "- category_counts: "
        + ", ".join(
            f"{label}={count}"
            for label, count in summary_payload["category_counts"].items()
        )
    )
    block_lines.append(
        "- candidate_ids: `"
        + ", ".join(str(email_id) for email_id in summary_payload["candidate_ids"])
        + "`"
    )
    block_lines.append("")
    block_lines.append("Artifacts:")
    block_lines.append(f"- `{candidates_csv_path}`")
    block_lines.append(f"- `{summary_md_path}`")
    block_lines.append(f"- `{summary_json_path}`")
    block_lines.append("")

    block = "\n".join(block_lines)

    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    existing = tracker_path.read_text(encoding="utf-8") if tracker_path.exists() else ""

    if heading in existing:
        # Keep appending deterministic snapshots idempotent per-day by skipping duplicate headings.
        return

    suffix = "" if existing.endswith("\n") else "\n"
    tracker_path.write_text(existing + suffix + "\n" + block, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate weekly real-signal labeling artifacts")
    parser.add_argument("--days", type=int, default=7, help="Lookback window for candidate selection")
    parser.add_argument(
        "--limit",
        type=int,
        default=60,
        help="Maximum number of candidates to emit for this batch",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        type=float,
        default=0.85,
        help="Threshold for low-confidence candidate selection",
    )
    parser.add_argument(
        "--low-confidence-limit",
        type=int,
        default=30,
        help="Max unique candidates added from low-confidence pool",
    )
    parser.add_argument(
        "--confusion-limit",
        type=int,
        default=20,
        help="Max unique candidates added from confusion-pair pool",
    )
    parser.add_argument(
        "--confusion-max-confidence",
        type=float,
        default=0.95,
        help="Upper confidence bound for confusion-pair pool sampling",
    )
    parser.add_argument(
        "--confusion-share-cap",
        type=float,
        default=0.50,
        help="Max fraction of final batch where confusion_pair_focus can be the primary reason",
    )
    parser.add_argument(
        "--support-limit",
        type=int,
        default=20,
        help="Max unique candidates added from low-support-label pool",
    )
    parser.add_argument(
        "--target-signal-limit",
        type=int,
        default=20,
        help="Max unique candidates added from target-label signal mining pool",
    )
    parser.add_argument(
        "--target-signal-max-confidence",
        type=float,
        default=0.92,
        help="Upper confidence bound for target-signal pool sampling",
    )
    parser.add_argument(
        "--target-per-label",
        type=int,
        default=DEFAULT_TARGET_PER_LABEL,
        help="Desired real-signal count per target label for gap-aware prioritization",
    )
    parser.add_argument(
        "--target-labels",
        type=str,
        default=",".join(DEFAULT_TARGET_LABELS),
        help="Comma-separated labels to prioritize for low-support sampling",
    )
    parser.add_argument(
        "--confusion-pairs",
        type=str,
        default=",".join([f"{left}:{right}" for left, right in DEFAULT_CONFUSION_PAIRS]),
        help="Comma-separated confusion pairs, each in label_a:label_b format",
    )
    parser.add_argument(
        "--real-sources",
        type=str,
        default=",".join(DEFAULT_REAL_SOURCES),
        help="Comma-separated training_data sources treated as real signal",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated weekly artifacts",
    )
    parser.add_argument(
        "--tracker-path",
        type=Path,
        default=DEFAULT_TRACKER_PATH,
        help="Path to docs tracker file used when --append-tracker is set",
    )
    parser.add_argument(
        "--append-tracker",
        action="store_true",
        help="Append KPI snapshot + batch summary into docs tracker",
    )
    parser.add_argument(
        "--query-overfetch-multiplier",
        type=int,
        default=4,
        help="Multiplier used when over-fetching query pools before de-dup/trim",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if args.days <= 0:
        raise ValueError("--days must be > 0")
    if args.limit <= 0:
        raise ValueError("--limit must be > 0")
    if args.low_confidence_limit < 0:
        raise ValueError("--low-confidence-limit must be >= 0")
    if args.confusion_limit < 0:
        raise ValueError("--confusion-limit must be >= 0")
    if args.support_limit < 0:
        raise ValueError("--support-limit must be >= 0")
    if args.target_signal_limit < 0:
        raise ValueError("--target-signal-limit must be >= 0")
    if not 0.0 <= args.low_confidence_threshold <= 1.0:
        raise ValueError("--low-confidence-threshold must be between 0.0 and 1.0")
    if not 0.0 <= args.confusion_max_confidence <= 1.0:
        raise ValueError("--confusion-max-confidence must be between 0.0 and 1.0")
    if not 0.0 <= args.confusion_share_cap <= 1.0:
        raise ValueError("--confusion-share-cap must be between 0.0 and 1.0")
    if not 0.0 <= args.target_signal_max_confidence <= 1.0:
        raise ValueError("--target-signal-max-confidence must be between 0.0 and 1.0")
    if args.target_per_label <= 0:
        raise ValueError("--target-per-label must be > 0")
    if args.query_overfetch_multiplier <= 0:
        raise ValueError("--query-overfetch-multiplier must be > 0")

    target_labels = _parse_target_labels(args.target_labels)
    confusion_pairs = _parse_confusion_pairs(args.confusion_pairs)
    real_sources = _parse_csv_list(args.real_sources)
    if not real_sources:
        raise ValueError("--real-sources must include at least one source")

    await init_db()

    generated_at = datetime.utcnow()
    since = generated_at - timedelta(days=args.days)

    confusion_labels = sorted({label for pair in confusion_pairs for label in pair})
    all_time_real_by_label = await _get_training_counts_by_label(real_sources=real_sources)
    target_support = _compute_target_support_gaps(
        target_labels=target_labels,
        all_time_by_label=all_time_real_by_label,
        target_per_label=args.target_per_label,
    )
    support_quotas = _allocate_label_quotas(
        total_limit=args.support_limit,
        target_labels=target_labels,
        support_gaps=target_support,
    )
    signal_quotas = _allocate_label_quotas(
        total_limit=args.target_signal_limit,
        target_labels=target_labels,
        support_gaps=target_support,
    )

    # Query more rows than limits to absorb dedupe overlap across pools.
    overfetch_multiplier = args.query_overfetch_multiplier
    low_confidence_pool = await _fetch_candidates_for_labels(
        labels=list(JOB_LABELS),
        since=since,
        query_limit=max(args.low_confidence_limit * overfetch_multiplier, args.limit * 2),
        low_confidence_threshold=args.low_confidence_threshold,
    )
    confusion_pool = await _fetch_candidates_for_labels(
        labels=confusion_labels,
        since=since,
        query_limit=max(args.confusion_limit * overfetch_multiplier, args.limit * 2),
        max_confidence=args.confusion_max_confidence,
    )

    candidate_map: dict[int, LabelingCandidate] = {}
    _merge_pool(
        candidate_map=candidate_map,
        pool=low_confidence_pool,
        reason=REASON_LOW_CONFIDENCE,
        max_new_candidates=args.low_confidence_limit,
    )
    _merge_pool(
        candidate_map=candidate_map,
        pool=confusion_pool,
        reason=REASON_CONFUSION_PAIR,
        max_new_candidates=args.confusion_limit,
    )

    for target_label in target_labels:
        support_quota = support_quotas.get(target_label, 0)
        if support_quota > 0:
            low_support_pool = await _fetch_candidates_for_labels(
                labels=[target_label],
                since=since,
                query_limit=max(support_quota * overfetch_multiplier, args.limit * 2),
            )
            _merge_pool(
                candidate_map=candidate_map,
                pool=low_support_pool,
                reason=REASON_LOW_SUPPORT,
                max_new_candidates=support_quota,
            )

        signal_quota = signal_quotas.get(target_label, 0)
        if signal_quota > 0:
            target_signal_pool = await _fetch_candidates_for_target_signal(
                target_label=target_label,
                since=since,
                query_limit=max(signal_quota * overfetch_multiplier, args.limit * 2),
                max_confidence=args.target_signal_max_confidence,
            )
            _merge_pool(
                candidate_map=candidate_map,
                pool=target_signal_pool,
                reason=REASON_TARGET_SIGNAL,
                max_new_candidates=signal_quota,
                target_signal_label=target_label,
            )

    selected = _select_final_candidates(
        candidates=list(candidate_map.values()),
        limit=args.limit,
        confusion_share_cap=args.confusion_share_cap,
    )
    summary_payload = _summarize_candidates(selected)
    summary_payload["target_support"] = target_support

    kpi = await _build_weekly_kpi(
        now=generated_at,
        window_days=args.days,
        real_sources=real_sources,
    )
    kpi_markdown = render_kpi_markdown(kpi)

    tag = generated_at.strftime("%Y%m%d")
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_csv_path = output_dir / f"weekly_labeling_candidates_{tag}.csv"
    summary_json_path = output_dir / f"weekly_labeling_summary_{tag}.json"
    summary_md_path = output_dir / f"weekly_labeling_summary_{tag}.md"
    kpi_md_path = output_dir / f"weekly_kpi_{tag}.md"

    write_candidates_csv(candidates_csv_path, selected)

    summary_json_payload = {
        "generated_at_utc": generated_at.isoformat(),
        "window_days": args.days,
        "window_start_utc": since.isoformat(),
        "target_labels": target_labels,
        "target_per_label": args.target_per_label,
        "target_support": target_support,
        "confusion_pairs": confusion_pairs,
        "confusion_max_confidence": args.confusion_max_confidence,
        "confusion_share_cap": args.confusion_share_cap,
        "low_confidence_threshold": args.low_confidence_threshold,
        "target_signal_max_confidence": args.target_signal_max_confidence,
        "summary": summary_payload,
    }
    summary_json_path.write_text(
        json.dumps(summary_json_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary_markdown = _render_candidate_summary_markdown(
        generated_at=generated_at,
        since=since,
        low_confidence_threshold=args.low_confidence_threshold,
        confusion_share_cap=args.confusion_share_cap,
        target_labels=target_labels,
        confusion_pairs=confusion_pairs,
        target_per_label=args.target_per_label,
        target_support=target_support,
        summary_payload=summary_payload,
        candidates_csv_path=candidates_csv_path,
    )
    summary_md_path.write_text(summary_markdown, encoding="utf-8")
    kpi_md_path.write_text(kpi_markdown, encoding="utf-8")

    if args.append_tracker:
        append_snapshot_to_tracker(
            tracker_path=args.tracker_path,
            snapshot_date=generated_at,
            kpi_markdown=kpi_markdown,
            summary_payload=summary_payload,
            candidates_csv_path=candidates_csv_path,
            summary_md_path=summary_md_path,
            summary_json_path=summary_json_path,
        )

    print(f"Wrote: {candidates_csv_path}")
    print(f"Wrote: {summary_json_path}")
    print(f"Wrote: {summary_md_path}")
    print(f"Wrote: {kpi_md_path}")
    if args.append_tracker:
        print(f"Updated tracker: {args.tracker_path}")
    print(f"Selected candidates: {len(selected)}")
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
