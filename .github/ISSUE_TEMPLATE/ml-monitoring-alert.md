---
name: ML Monitoring Alert
about: Track triage/remediation for automated ML monitoring alerts
title: "[ML Monitoring][WARNING] Alerts detected (YYYY-MM-DD)"
labels: ["monitoring", "ml"]
assignees: []
---

## Summary

Automated monitoring detected classifier health alerts.

## Snapshot

- generated_at_utc:
- window_days:
- alerts_count:
- highest_severity:

## Alerts

| Severity | Metric | Value | Threshold | Message |
|---|---|---:|---:|---|
| warning | example_metric | 0 | 0 | replace with real row(s) |

## Triage Notes

- Root cause:
- Affected labels/flows:
- Chosen remediation:

## Verification

- [ ] `scripts/monitoring_cycle.sh --days 7 --append-history`
- [ ] v3 rules benchmark gate check
- [ ] v3 hybrid (deterministic) benchmark gate check
- [ ] `.venv311/bin/pytest -q`

## Close Criteria

- [ ] Alert cleared in latest monitoring output or threshold recalibration approved.
- [ ] Remediation and verification evidence captured in this issue.
- [ ] Follow-up issue(s) created for deferred work (if needed).

