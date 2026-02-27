# Next Steps for JobTracker ML

Updated: **February 26, 2026**

This checklist starts from the current post-cleanup state (broad rules + mixed-source SetFit retrain).

## Current State

- Rules/hybrid v1 baselines pass.
- Rules/hybrid v2 baselines pass.
- Full backend tests pass.
- Training data rows: `1,247`.
- Real user-correction rows: `79` (improved, but still lower than synthetic volume).
- Current review queue count: `0`.

## Priority 1: Increase Real-Signal Share

- Collect more true user-correction examples, especially for:
  - `offer`
  - `interview`
  - `pending_application`
- Track weekly delta in `user_correction` source counts.
- Keep synthetic data as support, not primary authority.
- Latest deferred manual items are now labeled; next target is fresh real `offer/interview/pending_application` corrections from new syncs.

## Priority 2: Monitor Drift and Confidence Health

- Run periodic monitoring snapshots:
  - `cd backend`
  - `.venv311/bin/python -m jobtracker.scripts.generate_ml_monitoring_report --days 7 --output data/evaluation/ml_monitoring_report.md`
- Watch for:
  - increasing low-confidence volume
  - repeated confusion pairs (for example `assessment` vs `follow_up`)

## Priority 3: Keep Retrain Provenance Strict

- Ensure every retrain artifact contains:
  - label distribution
  - source distribution
  - train/eval split sizes
  - timestamp and base model
- Continue storing this in `training_metadata.json` under model artifact directories.

## Priority 4: Guard Against Shortcut Reintroduction

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
