"""Tests for weekly real-signal labeling workflow tooling."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from jobtracker.config import settings
from jobtracker.database import get_session, init_db
from jobtracker.database.models import Email, EmailCategory, EmailSource, TrainingData
from jobtracker.scripts import weekly_labeling_workflow as workflow
from jobtracker.scripts.weekly_labeling_workflow import (
    LabelingCandidate,
    WeeklyKPI,
    append_snapshot_to_tracker,
    calculate_real_signal_share_from_metadata,
    render_kpi_markdown,
    write_candidates_csv,
)


async def _reset_weekly_tables() -> None:
    await init_db()
    async with get_session() as session:
        await session.exec(text("DELETE FROM email_embeddings"))
        await session.exec(text("DELETE FROM training_data"))
        await session.exec(text("DELETE FROM emails"))
        await session.exec(text("DELETE FROM applications"))
        await session.commit()


def test_write_candidates_csv_is_privacy_safe(tmp_path: Path) -> None:
    output_path = tmp_path / "weekly_labeling_candidates.csv"
    candidates = [
        LabelingCandidate(
            email_id=101,
            received_at=datetime(2026, 2, 28, 12, 0, 0),
            source_account="gmail",
            current_category="pending_application",
            confidence=0.71,
            classification_method="setfit",
            is_reviewed=False,
            reasons={"low_confidence", "low_support_category"},
        )
    ]

    write_candidates_csv(output_path, candidates)
    text = output_path.read_text(encoding="utf-8")

    assert "email_id" in text
    assert "subject" not in text
    assert "body_text" not in text
    assert "body_snippet" not in text


def test_calculate_real_signal_share_from_metadata() -> None:
    metadata = {
        "source_counts": {
            "user_correction": 30,
            "external_dataset": 70,
        }
    }
    real, total, pct = calculate_real_signal_share_from_metadata(
        metadata,
        {"user_correction"},
    )

    assert real == 30
    assert total == 100
    assert pct is not None
    assert round(pct, 2) == 30.0


def test_render_kpi_markdown_contains_required_issue_2_metrics() -> None:
    kpi = WeeklyKPI(
        generated_at=datetime(2026, 2, 28, 13, 30, 0),
        window_days=7,
        real_sources=["user_correction"],
        total_real_examples=120,
        current_week_total=18,
        previous_week_total=11,
        weekly_delta=7,
        all_time_by_label={"interview": 22, "pending_application": 14},
        current_week_by_label={"interview": 5, "pending_application": 3},
        previous_week_by_label={"interview": 2, "pending_application": 1},
        latest_model_name="setfit_model_20260228_130000",
        latest_model_trained_at="2026-02-28T13:00:00",
        latest_model_real_examples=40,
        latest_model_total_examples=200,
        latest_model_real_share_pct=20.0,
    )

    content = render_kpi_markdown(kpi)
    assert "user_correction_weekly_delta" in content
    assert "Per-Label Real-Signal Totals" in content
    assert "real_signal_share_latest_retrain" in content


def test_append_snapshot_to_tracker_avoids_duplicate_heading(tmp_path: Path) -> None:
    tracker_path = tmp_path / "ML_EXECUTION_TRACKER.md"
    tracker_path.write_text("# Tracker\n", encoding="utf-8")

    snapshot_date = datetime(2026, 2, 28, 18, 0, 0)
    append_snapshot_to_tracker(
        tracker_path=tracker_path,
        snapshot_date=snapshot_date,
        kpi_markdown="### Weekly KPI Snapshot\n\n- user_correction_weekly_delta: `+3`\n",
        summary_payload={
            "total_candidates": 2,
            "reason_counts": {"low_confidence": 2},
            "category_counts": {"interview": 1, "pending_application": 1},
            "candidate_ids": [10, 20],
        },
        candidates_csv_path=tmp_path / "candidates.csv",
        summary_md_path=tmp_path / "summary.md",
        summary_json_path=tmp_path / "summary.json",
    )
    first = tracker_path.read_text(encoding="utf-8")

    append_snapshot_to_tracker(
        tracker_path=tracker_path,
        snapshot_date=snapshot_date,
        kpi_markdown="### Weekly KPI Snapshot\n\n- user_correction_weekly_delta: `+3`\n",
        summary_payload={
            "total_candidates": 2,
            "reason_counts": {"low_confidence": 2},
            "category_counts": {"interview": 1, "pending_application": 1},
            "candidate_ids": [10, 20],
        },
        candidates_csv_path=tmp_path / "candidates.csv",
        summary_md_path=tmp_path / "summary.md",
        summary_json_path=tmp_path / "summary.json",
    )
    second = tracker_path.read_text(encoding="utf-8")

    assert first == second


def test_append_snapshot_to_tracker_includes_standardized_sections(tmp_path: Path) -> None:
    tracker_path = tmp_path / "ML_EXECUTION_TRACKER.md"
    tracker_path.write_text("# Tracker\n", encoding="utf-8")

    append_snapshot_to_tracker(
        tracker_path=tracker_path,
        snapshot_date=datetime(2026, 3, 4, 10, 0, 0),
        kpi_markdown=(
            "### Weekly KPI Snapshot\n\n"
            "- generated_at_utc: `2026-03-04T10:00:00`\n"
            "- real_sources: `user_correction`\n"
            "- user_correction_total: `81`\n"
            "- user_correction_last_7_days: `5`\n"
            "- user_correction_prev_7_days: `4`\n"
            "- user_correction_weekly_delta: `+1`\n"
            "- real_signal_share_latest_retrain: `20.00%` (40/200)\n"
            "\n"
            "#### Per-Label Real-Signal Totals\n"
            "- offer: total=2, last_7d=1, delta_vs_prev_window=+1\n"
        ),
        summary_payload={
            "total_candidates": 3,
            "reason_counts": {"target_label_signal": 2, "low_confidence": 1},
            "category_counts": {"other": 1, "interview": 2},
            "candidate_ids": [101, 102, 103],
        },
        candidates_csv_path=tmp_path / "candidates.csv",
        summary_md_path=tmp_path / "summary.md",
        summary_json_path=tmp_path / "summary.json",
    )

    content = tracker_path.read_text(encoding="utf-8")
    assert "## Weekly KPI Snapshot (2026-03-04)" in content
    assert "### Weekly KPI Snapshot" in content
    assert "#### Per-Label Real-Signal Totals" in content
    assert "### Weekly Labeling Batch" in content
    assert "- total_candidates: `3`" in content
    assert "- reason_counts: " in content
    assert "- category_counts: " in content
    assert "- candidate_ids: `101, 102, 103`" in content


def test_allocate_label_quotas_biases_toward_larger_real_signal_gaps() -> None:
    support_gaps = {
        "offer": {"current_total": 2, "gap_to_target": 23},
        "interview": {"current_total": 18, "gap_to_target": 7},
        "pending_application": {"current_total": 26, "gap_to_target": 0},
    }

    quotas = workflow._allocate_label_quotas(
        total_limit=12,
        target_labels=["offer", "interview", "pending_application"],
        support_gaps=support_gaps,
    )

    assert sum(quotas.values()) == 12
    assert quotas["offer"] > quotas["interview"]
    assert quotas["pending_application"] <= quotas["interview"]


def test_select_final_candidates_caps_primary_confusion_share() -> None:
    base_time = datetime(2026, 3, 1, 10, 0, 0)
    candidates = []
    for idx in range(6):
        candidates.append(
            LabelingCandidate(
                email_id=idx + 1,
                received_at=base_time + timedelta(minutes=idx),
                source_account="gmail",
                current_category="applied",
                confidence=0.9,
                classification_method="rules",
                is_reviewed=False,
                reasons={"confusion_pair_focus"},
            )
        )
    for idx in range(6, 14):
        candidates.append(
            LabelingCandidate(
                email_id=idx + 1,
                received_at=base_time + timedelta(minutes=idx),
                source_account="gmail",
                current_category="offer",
                confidence=0.8,
                classification_method="setfit",
                is_reviewed=False,
                reasons={"target_label_signal"},
            )
        )

    selected = workflow._select_final_candidates(
        candidates=candidates,
        limit=8,
        confusion_share_cap=0.25,
    )

    assert len(selected) == 8
    confusion_primary = sum(
        1
        for item in selected
        if workflow._primary_reason(item) == workflow.REASON_CONFUSION_PAIR
    )
    assert confusion_primary <= 2


@pytest.mark.asyncio
async def test_weekly_workflow_rejects_invalid_thresholds(tmp_path: Path) -> None:
    args = argparse.Namespace(
        days=7,
        limit=10,
        low_confidence_threshold=1.2,
        low_confidence_limit=10,
        confusion_limit=10,
        confusion_max_confidence=0.95,
        confusion_share_cap=0.50,
        support_limit=10,
        target_signal_limit=10,
        target_signal_max_confidence=0.92,
        target_per_label=25,
        target_labels="offer,interview,pending_application",
        confusion_pairs="assessment:follow_up,applied:pending_application",
        real_sources="user_correction",
        output_dir=tmp_path / "out",
        tracker_path=tmp_path / "tracker.md",
        append_tracker=False,
        query_overfetch_multiplier=4,
    )

    with pytest.raises(ValueError, match="low-confidence-threshold"):
        await workflow._run(args)


@pytest.mark.asyncio
async def test_weekly_workflow_run_selects_expected_candidates_and_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_weekly_tables()
    monkeypatch.setattr(settings, "database_dir", str(tmp_path / "dbdir"), raising=False)

    now = datetime.utcnow()

    async with get_session() as session:
        emails = [
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<weekly-1@test.com>",
                received_at=now - timedelta(hours=1),
                subject="Interview update",
                sender_email="recruiter@test.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.40,
                classification_method="setfit",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<weekly-2@test.com>",
                received_at=now - timedelta(hours=2),
                subject="Application received",
                sender_email="team@test.com",
                classified_as=EmailCategory.PENDING_APPLICATION,
                classification_confidence=0.90,
                classification_method="rules",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<weekly-3@test.com>",
                received_at=now - timedelta(hours=3),
                subject="Applied status",
                sender_email="team@test.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.90,
                classification_method="rules",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.ICLOUD,
                message_id="<weekly-4@test.com>",
                received_at=now - timedelta(hours=4),
                subject="Offer details",
                sender_email="hiring@test.com",
                classified_as=EmailCategory.OFFER,
                classification_confidence=0.99,
                classification_method="rules",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.ICLOUD,
                message_id="<weekly-5@test.com>",
                received_at=now - timedelta(hours=5),
                subject="Follow up",
                sender_email="hiring@test.com",
                classified_as=EmailCategory.FOLLOW_UP,
                classification_confidence=0.96,
                classification_method="rules",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.ICLOUD,
                message_id="<weekly-6@test.com>",
                received_at=now - timedelta(hours=6),
                subject="Assessment instructions",
                sender_email="hiring@test.com",
                classified_as=EmailCategory.ASSESSMENT,
                classification_confidence=0.92,
                classification_method="setfit",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<weekly-7@test.com>",
                received_at=now - timedelta(hours=7),
                subject="Old corrected item",
                sender_email="team@test.com",
                classified_as=EmailCategory.REJECTION,
                classification_confidence=0.30,
                classification_method="setfit",
                user_corrected=True,
            ),
        ]
        session.add_all(emails)

        session.add(
            TrainingData(
                subject="Recent correction",
                body_text="test",
                label="interview",
                source="user_correction",
                created_at=now - timedelta(days=3),
            )
        )
        session.add(
            TrainingData(
                subject="Previous correction",
                body_text="test",
                label="offer",
                source="user_correction",
                created_at=now - timedelta(days=10),
            )
        )
        await session.commit()

        for email in emails:
            await session.refresh(email)

        expected_low_conf_id = int(emails[0].id or 0)
        expected_excluded_id = int(emails[4].id or 0)  # follow_up @ 0.96 exceeds confusion cap

    output_dir = tmp_path / "weekly-output"
    args = argparse.Namespace(
        days=30,
        limit=10,
        low_confidence_threshold=0.85,
        low_confidence_limit=10,
        confusion_limit=10,
        confusion_max_confidence=0.95,
        confusion_share_cap=0.50,
        support_limit=10,
        target_signal_limit=10,
        target_signal_max_confidence=0.92,
        target_per_label=25,
        target_labels="offer,interview,pending_application",
        confusion_pairs="assessment:follow_up,applied:pending_application",
        real_sources="user_correction",
        output_dir=output_dir,
        tracker_path=tmp_path / "tracker.md",
        append_tracker=False,
        query_overfetch_multiplier=4,
    )

    rc = await workflow._run(args)
    assert rc == 0

    summary_paths = sorted(output_dir.glob("weekly_labeling_summary_*.json"))
    assert len(summary_paths) == 1
    summary = json.loads(summary_paths[0].read_text(encoding="utf-8"))
    candidate_ids = summary["summary"]["candidate_ids"]

    # Low-confidence interview candidate must be included and prioritized.
    assert candidate_ids[0] == expected_low_conf_id
    # High-confidence follow_up candidate above confusion cap should be excluded.
    assert expected_excluded_id not in candidate_ids
    assert summary["summary"]["reason_counts"]["low_confidence"] >= 1
    assert summary["summary"]["reason_counts"]["low_support_category"] >= 1
    assert summary["summary"]["reason_counts"]["confusion_pair_focus"] >= 1

    csv_paths = sorted(output_dir.glob("weekly_labeling_candidates_*.csv"))
    assert len(csv_paths) == 1
    with csv_paths[0].open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
    assert "subject" not in fieldnames
    assert "body_text" not in fieldnames
    assert "body_snippet" not in fieldnames


@pytest.mark.asyncio
async def test_weekly_workflow_honors_custom_pairs_labels_and_thresholds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_weekly_tables()
    monkeypatch.setattr(settings, "database_dir", str(tmp_path / "dbdir"), raising=False)

    now = datetime.utcnow()
    async with get_session() as session:
        session.add(
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<custom-1@test.com>",
                received_at=now - timedelta(hours=1),
                subject="Offer note",
                sender_email="team@test.com",
                classified_as=EmailCategory.OFFER,
                classification_confidence=0.80,
                classification_method="rules",
                user_corrected=False,
            )
        )
        session.add(
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<custom-2@test.com>",
                received_at=now - timedelta(hours=2),
                subject="Pending note",
                sender_email="team@test.com",
                classified_as=EmailCategory.PENDING_APPLICATION,
                classification_confidence=0.90,
                classification_method="rules",
                user_corrected=False,
            )
        )
        await session.commit()

    output_dir = tmp_path / "custom-output"
    args = argparse.Namespace(
        days=30,
        limit=10,
        low_confidence_threshold=0.60,
        low_confidence_limit=10,
        confusion_limit=10,
        confusion_max_confidence=0.50,
        confusion_share_cap=0.50,
        support_limit=10,
        target_signal_limit=10,
        target_signal_max_confidence=0.92,
        target_per_label=25,
        target_labels="offer",
        confusion_pairs="interview:offer",
        real_sources="user_correction",
        output_dir=output_dir,
        tracker_path=tmp_path / "tracker.md",
        append_tracker=False,
        query_overfetch_multiplier=3,
    )

    rc = await workflow._run(args)
    assert rc == 0

    summary_path = sorted(output_dir.glob("weekly_labeling_summary_*.json"))[0]
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["target_labels"] == ["offer"]
    assert payload["confusion_pairs"] == [["interview", "offer"]]
    assert payload["confusion_max_confidence"] == 0.5
    # Ensure support-target candidate still appears even with strict confusion threshold.
    assert payload["summary"]["total_candidates"] >= 1


@pytest.mark.asyncio
async def test_weekly_workflow_target_signal_mines_sparse_label_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_weekly_tables()
    monkeypatch.setattr(settings, "database_dir", str(tmp_path / "dbdir"), raising=False)

    now = datetime.utcnow()
    async with get_session() as session:
        emails = [
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<signal-1@test.com>",
                received_at=now - timedelta(hours=1),
                subject="Offer letter attached",
                sender_email="talent@test.com",
                classified_as=EmailCategory.OTHER,
                classification_confidence=0.90,
                classification_method="rules",
                user_corrected=False,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<signal-2@test.com>",
                received_at=now - timedelta(hours=2),
                subject="Weekly newsletter",
                sender_email="news@test.com",
                classified_as=EmailCategory.OTHER,
                classification_confidence=0.80,
                classification_method="rules",
                user_corrected=False,
            ),
        ]
        session.add_all(emails)
        await session.commit()
        for email in emails:
            await session.refresh(email)
        target_email_id = int(emails[0].id or 0)

    output_dir = tmp_path / "signal-output"
    args = argparse.Namespace(
        days=30,
        limit=10,
        low_confidence_threshold=0.10,
        low_confidence_limit=0,
        confusion_limit=0,
        confusion_max_confidence=0.95,
        confusion_share_cap=0.50,
        support_limit=0,
        target_signal_limit=5,
        target_signal_max_confidence=0.92,
        target_per_label=25,
        target_labels="offer",
        confusion_pairs="assessment:follow_up",
        real_sources="user_correction",
        output_dir=output_dir,
        tracker_path=tmp_path / "tracker.md",
        append_tracker=False,
        query_overfetch_multiplier=3,
    )

    rc = await workflow._run(args)
    assert rc == 0

    summary_path = sorted(output_dir.glob("weekly_labeling_summary_*.json"))[0]
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    candidate_ids = payload["summary"]["candidate_ids"]

    assert target_email_id in candidate_ids
    assert payload["summary"]["reason_counts"]["target_label_signal"] >= 1
    assert payload["summary"]["target_signal_counts"]["offer"] >= 1
