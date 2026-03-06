"""Tests for monitoring-alert issue payload generation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from jobtracker.scripts.prepare_ml_monitoring_alert_issue import (
    build_issue_body,
    build_issue_title,
    write_github_outputs,
)


def test_build_issue_title_uses_highest_severity_and_date() -> None:
    payload = {
        "generated_at_utc": "2026-03-05T10:00:00",
        "alerts": [
            {"severity": "warning", "metric": "low_confidence_delta"},
            {"severity": "critical", "metric": "max_label_distribution_drift_pp"},
        ],
    }

    title = build_issue_title(payload)
    assert title == "[ML Monitoring][CRITICAL] Alerts detected (2026-03-05)"


def test_build_issue_body_renders_alert_table_and_triage_steps() -> None:
    payload = {
        "generated_at_utc": "2026-03-05T10:00:00",
        "window_days": 7,
        "alerts": [
            {
                "severity": "warning",
                "metric": "low_confidence_growth_pct",
                "value": 35.2,
                "threshold": 25.0,
                "message": "Low-confidence volume growth exceeded threshold.",
            }
        ],
    }

    body = build_issue_body(payload)
    assert "## Alerts" in body
    assert "`low_confidence_growth_pct`" in body
    assert "docs/ML_MONITORING_RUNBOOK.md" in body
    assert "scripts/monitoring_cycle.sh --days 7 --append-history" in body
    assert "## Close Criteria" in body


def test_write_github_outputs_appends_key_values(tmp_path: Path) -> None:
    output_path = tmp_path / "gh_output.txt"
    output_path.write_text("existing=1\n", encoding="utf-8")

    write_github_outputs(
        output_path,
        {"has_alerts": "true", "highest_severity": "warning"},
    )

    text = output_path.read_text(encoding="utf-8")
    assert "existing=1" in text
    assert "has_alerts=true" in text
    assert "highest_severity=warning" in text


def test_cli_like_payload_round_trip_is_json_compatible(tmp_path: Path) -> None:
    payload = {
        "generated_at_utc": "2026-03-05T10:00:00",
        "window_days": 7,
        "alerts": [],
    }
    json_path = tmp_path / "monitoring.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert build_issue_title(parsed).startswith("[ML Monitoring][WARNING]")
    assert "alerts_count: `0`" in build_issue_body(parsed)

