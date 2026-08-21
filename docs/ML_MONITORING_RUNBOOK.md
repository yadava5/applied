# ML Monitoring Runbook

Updated: **March 5, 2026**
Scope: monitoring triage for classifier confidence/drift alerts

> **Scope, added 2026-08-15 — this runbook is a local operator procedure. None of
> it runs in the hosted deployment.**
>
> The "Updated" stamp above is an edit date, not a claim that this triage loop is
> being run. The inputs are artifacts produced by `scripts/monitoring_cycle.sh`
> and `scripts/weekly_labeling_cycle.sh`, both invoked by hand against a local
> backend; neither runs in CI or on Vercel. The deployed classifier is
> **rules-only** — `HybridClassifier.classify` short-circuits to the rules layer
> whenever `settings.deployment == "cloud"`
> (`backend/jobtracker/classifier/hybrid.py:326`).
>
> Every "retrain" remediation below is therefore a local action, and default-deny
> even there: training refuses unless the corpus is wholly synthetic or its single
> owner is allowlisted, and the allowlist is empty unless configured
> (`backend/jobtracker/classifier/setfit_model.py:38-75`). Applied reads mail
> under Gmail's restricted `gmail.readonly` scope; Google's Workspace API
> user-data policy permits training only a model personalized to one end user with
> no co-mingling, so an unconfigured deployment training on nobody is the intended
> state. No user correction collected here changes a hosted classification.

## Purpose

Convert weekly monitoring artifacts into consistent triage and remediation actions,
with explicit owners, severity routing, and verification gates.

## Inputs

- `backend/data/evaluation/ml_monitoring_report.md`
- `backend/data/evaluation/ml_monitoring_report.json`
- `backend/data/evaluation/ml_monitoring_history.jsonl`
- alert issue payload files (workflow-generated when alerts exist):
  - `backend/data/evaluation/ml_monitoring_alert_title.txt`
  - `backend/data/evaluation/ml_monitoring_alert_body.md`

## Owner Model

- Primary owner: current ML maintainer for the week.
- Secondary owner: backend maintainer when remediation touches API/rules/runtime behavior.
- Escalation owner: repo maintainer if alert persists across two weekly cycles.

## Severity Matrix

| Severity | Trigger Condition | Owner | SLA |
|---|---|---|---|
| `warning` | Any single threshold breach in monitoring report | Primary owner | Triage within 1 business day |
| `critical` | Any of: (1) 2+ warning metrics in same run, (2) same warning persists for 2 weekly runs, (3) benchmark gate regression after remediation | Primary + Secondary owner | Same day triage + remediation plan |

## Alert Types and Playbooks

### 1) `low_confidence_growth_pct` / `low_confidence_delta`

- Trigger: low-confidence volume grows above configured thresholds.
- Owner: Primary.
- Triage:
  1. Inspect `low_confidence.current_by_label` in report JSON.
  2. Confirm whether growth is concentrated in sparse lifecycle labels.
  3. Run weekly sparse-label SOP to collect corrections.
- Remediation:
  - increase weekly review effort for affected labels
  - retrain after corrections
- Verification commands:
  - `scripts/weekly_labeling_cycle.sh --append-tracker --days 7 --target-per-label 25 --target-signal-limit 20 --confusion-share-cap 0.50`
  - `scripts/monitoring_cycle.sh --days 7 --append-history`

### 2) `max_label_distribution_drift_pp`

- Trigger: uncorrected label share shift exceeds threshold.
- Owner: Primary + Secondary.
- Triage:
  1. Inspect `distribution.drift.by_label` and max drift label.
  2. Check recent ingestion/source changes.
  3. Spot-check representative emails for misroutes.
- Remediation:
  - targeted real-label corrections
  - retrain + benchmark verification
  - threshold recalibration only with documented rationale
- Verification commands:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_rules_v3.json --tolerance 0.001 --min-macro-f1 0.95`
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_hybrid_v3.json --hybrid-profile deterministic --tolerance 0.001 --min-macro-f1 0.95`
  - `scripts/monitoring_cycle.sh --days 7 --append-history`

### 3) `confusion_pair_low_confidence_total`

- Trigger: repeated low-confidence volume in configured confusion pairs.
- Owner: Primary.
- Triage:
  1. Inspect `confusion_pair_signals` block.
  2. Sample mismatched pair examples.
  3. Confirm whether issue is data coverage or rule behavior.
- Remediation:
  - prioritize confusion pair in weekly labeling run
  - avoid narrow phrase patches unless benchmark-backed
- Verification commands:
  - `scripts/weekly_labeling_cycle.sh --append-tracker --confusion-share-cap 0.40 --target-signal-limit 25`
  - `scripts/monitoring_cycle.sh --days 7 --append-history`

## Triage Workflow (Alert to Action)

1. Monitoring workflow generates report artifacts.
2. If alerts exist, workflow prepares issue payload using:
   - `python -m jobtracker.scripts.prepare_ml_monitoring_alert_issue ...`
3. Workflow creates a GitHub issue (`monitoring`, `ml` labels) unless same-title issue is already open.
4. Owner follows this runbook and updates issue with:
   - root cause
   - remediation
   - verification output
5. Close issue only after close criteria are met.

## Simulation Path (Required Validation)

Use aggressive thresholds to force an alert and validate end-to-end issue payload flow:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.generate_ml_monitoring_report \
  --days 7 \
  --output-md /tmp/ml_monitoring_sim.md \
  --output-json /tmp/ml_monitoring_sim.json \
  --low-confidence-growth-alert-pct 0 \
  --low-confidence-delta-alert-count 0 \
  --distribution-drift-alert-pp 0 \
  --confusion-pair-alert-count 0

.venv311/bin/python -m jobtracker.scripts.prepare_ml_monitoring_alert_issue \
  --monitoring-json /tmp/ml_monitoring_sim.json \
  --title-out /tmp/ml_monitoring_alert_title.txt \
  --body-out /tmp/ml_monitoring_alert_body.md
```

Expected simulation result:

- `HAS_ALERTS=true`
- generated title/body files are non-empty and triage-ready.

## Close Criteria

- Alert condition cleared in latest monitoring output, or threshold update approved and documented.
- Required verification commands completed and logged in issue.
- Any long-tail follow-up work split into dedicated issue(s).

