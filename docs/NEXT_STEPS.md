# Next Steps for JobTracker ML

Updated: **February 28, 2026**

This checklist starts from the current post-cleanup state (broad rules + mixed-source SetFit retrain).

## Current State

- Rules/hybrid v1 baselines pass.
- Rules/hybrid v2 baselines pass.
- Full backend tests pass.
- Training data rows: `1,249` (latest recorded run).
- Real user-correction rows: `81` (latest recorded run; still lower than synthetic volume).
- Current review queue count: `0`.

## Priority 1: Increase Real-Signal Share

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

## Priority 2: Monitor Drift and Confidence Health

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

## Priority 3: Keep Retrain Provenance Strict

- Enforced in code/tests via `validate_training_metadata_contract(...)`.
- Every retrain artifact now includes:
  - `schema_version`
  - label/source distribution
  - train/eval split sizes
  - timestamp and base model
- Keep this contract versioned and explicit for future schema changes.

## Priority 4: Expand Evaluation Coverage (Next Implementation Target)

- Build `classifier_eval_v3` with stronger edge-case and confusion-pair coverage.
- Generate and commit `baseline_rules_v3.json` and `baseline_hybrid_v3.json`.
- Add regression tests for known historical misses.
- Add CI gate policy for v3 rules benchmark (or document staged rollout rationale).
- This maps to GitHub issue `#4`.

## Priority 5: Guard Against Shortcut Reintroduction

- Avoid narrow phrase/brand-based rule patches unless clearly broad and justified.
- Prefer fixes through:
  - representative data
  - confidence calibration
  - benchmark-backed validation

## Standard Verification Commands

- Rules v1:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_rules_v1.json`
- Hybrid v1:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_hybrid_v1.json`
- Rules v2:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_rules_v2.json`
- Hybrid v2:
  - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_hybrid_v2.json`
- Full backend tests:
  - `.venv311/bin/pytest -q`
