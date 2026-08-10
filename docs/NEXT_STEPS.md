# Next Steps for Applied ML

Updated: **March 5, 2026**

This checklist starts from the current post-cleanup state (broad rules + mixed-source SetFit retrain).

## Current State

- Rules/hybrid v1 baselines pass.
- Rules/hybrid v2 baselines pass.
- Rules/hybrid v3 baselines committed.
- v3 rules benchmark gate is active in CI.
- v3 hybrid benchmark gate is active in CI (deterministic profile).
- Weekly labeling workflow now includes:
  - target-label signal mining for sparse classes
  - gap-aware per-label quotas (`--target-per-label`)
  - confusion-share cap in final batch selection
- Full backend tests pass.
- Training data rows: `1,249` (latest recorded run).
- Real user-correction rows: `81` (latest recorded run; still lower than synthetic volume).
- Current review queue count: `0`.

## Issue Status Snapshot (March 5, 2026)

- Closed (implemented): `#2`, `#3`, `#4`, `#5`, `#6`, `#7`, `#8`
- Open (remaining): `#9`, `#10`

## Priority 1: Execute Weekly Sparse-Label SOP (Ongoing Ops)

- Run the SOP every week and keep evidence in tracker + artifacts.
- Canonical runbook:
  - `docs/ML_WEEKLY_OPERATIONS.md`
- Keep weekly artifacts privacy-safe (IDs + aggregate counts only).

## Priority 2: Increase Real-Signal Share

- Collect more true user-correction examples, especially for:
  - `offer`
  - `interview`
  - `pending_application`
- Track weekly delta in `user_correction` source counts.
- Keep synthetic data as support, not primary authority.
- Latest deferred manual items are now labeled; next target is fresh real `offer/interview/pending_application` corrections from new syncs.
- Run the weekly real-signal batch command (privacy-safe IDs + counts only):
  - `scripts/weekly_labeling_cycle.sh --append-tracker`
- Weekly command outputs:
  - `backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_YYYYMMDD.csv`
  - `backend/data/evaluation/weekly_labeling/weekly_labeling_summary_YYYYMMDD.{md,json}`
  - `backend/data/evaluation/weekly_labeling/weekly_kpi_YYYYMMDD.md`
  - tracker append: `docs/ML_EXECUTION_TRACKER.md`

## Priority 3: Monitoring Alert Ops (Ongoing)

- Run periodic monitoring snapshots (single command):
  - `scripts/monitoring_cycle.sh --days 7 --append-history`
- Artifacts:
  - `backend/data/evaluation/ml_monitoring_report.md`
  - `backend/data/evaluation/ml_monitoring_report.json`
  - `backend/data/evaluation/ml_monitoring_history.jsonl`
- Watch for:
  - increasing low-confidence volume
  - repeated confusion pairs (for example `assessment` vs `follow_up`)
  - label distribution drift spikes
- Alert thresholds:
  - low-confidence growth: `>=25%` window-over-window (with previous volume >= 5)
  - low-confidence absolute delta: `>=10`
  - max label distribution drift: `>=12 pp`
  - confusion-pair low-confidence volume: `>=3`
- Scheduled automation:
  - `.github/workflows/ml-monitoring-weekly.yml` runs weekly and uploads artifacts.
- Canonical runbook:
  - `docs/ML_MONITORING_RUNBOOK.md`
- Alert issue flow assets:
  - `backend/jobtracker/scripts/prepare_ml_monitoring_alert_issue.py`
  - `.github/ISSUE_TEMPLATE/ml-monitoring-alert.md`
- Keep weekly alert issues triaged to closure with verification evidence.

## Priority 4: Define Real-Signal-Heavy Eval v4 (`#9`)

- Create `classifier_eval_v4` contract + dataset with stronger real-signal representation.
- Commit v4 rules/hybrid baselines and wire migration plan for CI gating.
- Keep v1/v2/v3 for continuity during staged rollout.

## Priority 5: Guard Against Shortcut Reintroduction (`#10`)

- Avoid narrow phrase/brand-based rule patches unless clearly broad and justified.
- Add governance policy + PR evidence requirements for classifier rule edits.
- Keep fixes benchmark-backed and data-driven.

## Priority 6: Keep Retrain Provenance Strict (Maintenance from `#5`)

- Enforced in code/tests via `validate_training_metadata_contract(...)`.
- Every retrain artifact now includes:
  - `schema_version`
  - label/source distribution
  - train/eval split sizes
  - timestamp and base model
- Keep this contract versioned and explicit for future schema changes.

## Standard Verification Commands

- Rules v1:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_rules_v1.json`
- Hybrid v1:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_hybrid_v1.json`
- Rules v2:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_rules_v2.json`
- Hybrid v2:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_hybrid_v2.json`
- Rules v3:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_rules_v3.json`
- Hybrid v3:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_hybrid_v3.json --hybrid-profile deterministic`
- Weekly sparse-label batch (enhanced):
  - `scripts/weekly_labeling_cycle.sh --append-tracker --target-per-label 25 --target-signal-limit 20 --confusion-share-cap 0.50`
- Regenerate baselines for any eval version:
  - `scripts/generate_eval_baselines.sh --version 3`
- Full backend tests:
  - `.venv311/bin/pytest -q`
