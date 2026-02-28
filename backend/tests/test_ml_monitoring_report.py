"""Tests for ML monitoring report helper logic."""

from __future__ import annotations

import pytest

from jobtracker.scripts.generate_ml_monitoring_report import (
    MonitoringThresholds,
    _build_alerts,
    _distribution_drift,
    _parse_confusion_pairs,
)


def test_parse_confusion_pairs_accepts_valid_pairs() -> None:
    pairs = _parse_confusion_pairs("assessment:follow_up,applied:pending_application")
    assert pairs == [("assessment", "follow_up"), ("applied", "pending_application")]


def test_parse_confusion_pairs_rejects_invalid_label() -> None:
    with pytest.raises(ValueError):
        _parse_confusion_pairs("assessment:not_a_label")


def test_distribution_drift_calculates_max_label_and_score() -> None:
    drift = _distribution_drift(
        current_counts={"applied": 8, "interview": 2},
        previous_counts={"applied": 2, "interview": 8},
        labels=["applied", "interview"],
    )

    assert drift["current_total"] == 10
    assert drift["previous_total"] == 10
    assert drift["max_label_drift"]["label"] in {"applied", "interview"}
    assert drift["drift_score_pp"] == pytest.approx(60.0, abs=1e-6)


def test_build_alerts_flags_growth_drift_and_confusion_pairs() -> None:
    thresholds = MonitoringThresholds(
        low_confidence_threshold=0.85,
        low_confidence_growth_alert_pct=25.0,
        low_confidence_delta_alert_count=5,
        min_previous_low_confidence_volume=2,
        min_distribution_volume=10,
        distribution_drift_alert_pp=10.0,
        confusion_pair_alert_count=3,
    )
    alerts = _build_alerts(
        thresholds=thresholds,
        low_conf_current=20,
        low_conf_previous=10,
        drift_summary={
            "current_total": 30,
            "previous_total": 30,
            "max_label_drift": {"label": "applied", "abs_delta_pp": 15.0},
        },
        confusion_pair_signals=[
            {"pair": ["assessment", "follow_up"], "low_confidence_total": 4}
        ],
    )

    metrics = {alert["metric"] for alert in alerts}
    assert "low_confidence_growth_pct" in metrics
    assert "low_confidence_delta" in metrics
    assert "max_label_distribution_drift_pp" in metrics
    assert "confusion_pair_low_confidence_total" in metrics


def test_build_alerts_skips_drift_when_distribution_volume_too_low() -> None:
    thresholds = MonitoringThresholds(
        low_confidence_threshold=0.85,
        low_confidence_growth_alert_pct=25.0,
        low_confidence_delta_alert_count=5,
        min_previous_low_confidence_volume=2,
        min_distribution_volume=10,
        distribution_drift_alert_pp=10.0,
        confusion_pair_alert_count=3,
    )
    alerts = _build_alerts(
        thresholds=thresholds,
        low_conf_current=12,
        low_conf_previous=10,
        drift_summary={
            "current_total": 4,
            "previous_total": 2,
            "max_label_drift": {"label": "applied", "abs_delta_pp": 90.0},
        },
        confusion_pair_signals=[],
    )

    metrics = {alert["metric"] for alert in alerts}
    assert "max_label_distribution_drift_pp" not in metrics
