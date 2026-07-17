#!/usr/bin/env python3
"""Build GitHub issue payloads from ML monitoring alert JSON."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"warning": 1, "critical": 2}


def _normalize_severity(raw: Any) -> str:
    value = str(raw).strip().lower() if raw is not None else "warning"
    if value not in SEVERITY_ORDER:
        return "warning"
    return value


def _highest_severity(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "warning"
    return max(
        (_normalize_severity(alert.get("severity")) for alert in alerts),
        key=lambda value: SEVERITY_ORDER.get(value, 1),
    )


def build_issue_title(payload: dict[str, Any]) -> str:
    generated_at = str(payload.get("generated_at_utc") or "")
    date_tag = generated_at.split("T", 1)[0] if "T" in generated_at else generated_at
    if not date_tag:
        date_tag = datetime.utcnow().strftime("%Y-%m-%d")

    alerts = payload.get("alerts") or []
    highest = _highest_severity(alerts if isinstance(alerts, list) else [])
    return f"[ML Monitoring][{highest.upper()}] Alerts detected ({date_tag})"


def build_issue_body(payload: dict[str, Any]) -> str:
    alerts_raw = payload.get("alerts") or []
    alerts = alerts_raw if isinstance(alerts_raw, list) else []
    highest = _highest_severity(alerts)

    lines: list[str] = []
    lines.append("## Summary")
    lines.append(
        "Automated monitoring detected classifier health alerts. "
        "Follow the runbook and close this issue only after remediation is verified."
    )
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- generated_at_utc: `{payload.get('generated_at_utc', 'unknown')}`")
    lines.append(f"- window_days: `{payload.get('window_days', 'unknown')}`")
    lines.append(f"- alerts_count: `{len(alerts)}`")
    lines.append(f"- highest_severity: `{highest}`")
    lines.append("")

    lines.append("## Alerts")
    if alerts:
        lines.append("| Severity | Metric | Value | Threshold | Message |")
        lines.append("|---|---|---:|---:|---|")
        for alert in alerts:
            severity = _normalize_severity(alert.get("severity"))
            metric = str(alert.get("metric", "unknown"))
            value = str(alert.get("value", "n/a"))
            threshold = str(alert.get("threshold", "n/a"))
            message = str(alert.get("message", "")).replace("\n", " ").strip()
            lines.append(
                f"| `{severity}` | `{metric}` | `{value}` | `{threshold}` | {message} |"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Required Triage")
    lines.append("1. Follow `docs/ML_MONITORING_RUNBOOK.md` severity routing and owner map.")
    lines.append("2. Capture root-cause notes and remediation steps in this issue.")
    lines.append("3. Run verification commands after remediation:")
    lines.append("   - `scripts/monitoring_cycle.sh --days 7 --append-history`")
    lines.append(
        "   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier "
        "--mode rules --dataset data/evaluation/classifier_eval_v3.jsonl "
        "--baseline data/evaluation/baseline_rules_v3.json --tolerance 0.001 --min-macro-f1 0.95`"
    )
    lines.append(
        "   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier "
        "--mode hybrid --dataset data/evaluation/classifier_eval_v3.jsonl "
        "--baseline data/evaluation/baseline_hybrid_v3.json --hybrid-profile deterministic "
        "--tolerance 0.001 --min-macro-f1 0.95`"
    )
    lines.append("   - `.venv311/bin/pytest -q`")
    lines.append("")

    lines.append("## Close Criteria")
    lines.append("- Monitoring alert condition is cleared or threshold is intentionally recalibrated.")
    lines.append("- Remediation + verification evidence is documented in this issue.")
    lines.append("- Follow-up issue is created if deeper model/data work is required.")
    lines.append("")

    return "\n".join(lines)


def write_github_outputs(path: Path, outputs: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    lines = [f"{key}={value}" for key, value in outputs.items()]
    path.write_text(existing + prefix + "\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare GitHub issue title/body files from monitoring alert JSON."
    )
    parser.add_argument("--monitoring-json", type=Path, required=True)
    parser.add_argument("--title-out", type=Path, default=None)
    parser.add_argument("--body-out", type=Path, default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.monitoring_json.read_text(encoding="utf-8"))
    alerts = payload.get("alerts") or []
    has_alerts = bool(alerts)
    highest = _highest_severity(alerts if isinstance(alerts, list) else [])

    title = build_issue_title(payload)
    body = build_issue_body(payload)

    if args.title_out is not None:
        args.title_out.parent.mkdir(parents=True, exist_ok=True)
        args.title_out.write_text(title + "\n", encoding="utf-8")
    if args.body_out is not None:
        args.body_out.parent.mkdir(parents=True, exist_ok=True)
        args.body_out.write_text(body + "\n", encoding="utf-8")

    if args.github_output is not None:
        write_github_outputs(
            args.github_output,
            {
                "has_alerts": "true" if has_alerts else "false",
                "highest_severity": highest,
            },
        )

    print(f"HAS_ALERTS={'true' if has_alerts else 'false'}")
    print(f"HIGHEST_SEVERITY={highest}")
    if args.title_out is not None:
        print(f"Wrote issue title: {args.title_out}")
    if args.body_out is not None:
        print(f"Wrote issue body: {args.body_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

