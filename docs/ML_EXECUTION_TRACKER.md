# ML Execution Tracker

This file records ML implementation cycles and verification results.

## Cycle A (Original 10-step plan) - Completed

## Step Status

1. Close current benchmark misses (`interview`, `offer`) - `completed`
2. Add explicit regression tests for those misses - `completed`
3. Expand evaluation set to v2 + baselines - `completed`
4. Add category-performance-over-time tracking - `completed`
5. Import mock dataset as controlled seed and verify - `completed`
6. Improve class balance workflow with real-data priority tooling - `completed`
7. Standardize retrain + evaluate workflow - `completed`
8. Add hybrid CI signal (non-blocking) - `completed`
9. Add post-retrain metadata/provenance artifact - `completed`
10. Add monitoring loop script for production usage - `completed`

## Verification Log (Cycle A)

- v1 baselines established and passing for rules/hybrid.
- v2 corpus and baselines added and passing at the time of completion.
- Full backend test suite passed at completion.

## Cycle B (February 26, 2026): De-hardcode + Retrain Refresh - Completed

Goal:
- Remove narrow phrase-level shortcuts.
- Keep only broad safety guards in rules for newsletter/promotions/security style content.
- Retrain SetFit on broader mixed data (real + external + mock) with confidence-driven behavior.

### Step B1 - Roll back narrow phrase-level logic (`completed`)

Changes:
- Removed targeted regex additions and tactical follow-up intent shortcut branches introduced as patch fixes.
- Removed narrow brand/one-off safety patterns from rules.

Verification:
- Immediate regression check showed expected temporary drops, confirming shortcut removal took effect.

### Step B2 - Expand neutral mock data before retrain (`completed`)

Changes:
- Enhanced synthetic generator diversity and neutrality.
- Generated `backend/data/external/mock_training_data_v3.jsonl` (`640` rows, `80` per label across 8 labels).
- Imported with source `mock_seed_v3`.

Verification:
- Import summary: `inserted=640`, `skipped_duplicate=0`, `skipped_invalid=0`.

### Step B3 - Improve SetFit data mixing (`completed`)

Changes:
- Updated sampler to use source-aware quotas + round-robin fill.
- Increased training cap to `24` examples per label.
- Added training artifact provenance for `source_counts` and `label_source_counts`.

Verification:
- Latest model metadata confirms mixed-source training rather than single-source dominance.

### Step B4 - Retrain SetFit with broader mixed data (`completed`)

Run:
- Model: `setfit_model_20260226_120511`
- Train examples: `192` (`24` per label)
- Runtime: `392.8567s`
- Train loss: `0.0282`

### Step B5 - Cross-check all behavior after retrain (`completed`)

Evaluation:
- v1 rules: `accuracy=1.0000`, `macro_f1=1.0000`
- v1 hybrid: `accuracy=1.0000`, `macro_f1=1.0000`
- v2 rules: `accuracy=0.9688`, `macro_f1=0.9686`
- v2 hybrid: `accuracy=0.9844`, `macro_f1=0.9843`

Tests:
- Full backend suite: `122 passed`.

Outcome:
- Cleanup objective achieved with no benchmark/test regression vs baselines.
- Rules are less shortcut-heavy, while hybrid quality is preserved/improved through broader retraining and confidence arbitration.

## Cycle C (February 26, 2026): Real Inbox Labeling Batch - Completed

Goal:
- Increase real correction signal after iCloud sync, without blindly pseudo-labeling uncertain predictions.

### Step C1 - Sync iCloud and measure review queue (`completed`)

Verification:
- iCloud sync result: `emails_fetched=88`, `emails_saved=88`, `errors=0`.
- Review queue (needs_review + low-confidence job categories): `0`.

### Step C2 - Build real labeling batch (`completed`)

Artifacts:
- `backend/data/evaluation/real_labeling_batch_20260226.csv`
- `backend/data/evaluation/real_labeling_batch_20260226_with_snippets.csv`
- `backend/data/evaluation/real_labeling_batch_20260226_summary.md`

Prepared mix:
- `applied=41`, `rejection=8`, `assessment=1` (50 total).

### Step C3 - Safe approvals only (`completed`)

Policy:
- Auto-approve only candidates in batch classified by `rules`.
- Skip non-rules predictions to avoid reinforcing uncertain pseudo-labels.

Result:
- selected: `44`
- updated emails: `44`
- inserted `training_data` rows (`source=user_correction`): `44`
- mix approved: `applied=40`, `rejection=3`, `assessment=1`
- skipped non-rules: `6`

### Step C4 - Retrain and cross-check (`completed`)

Retrain:
- Model: `setfit_model_20260226_122427`
- Runtime: `369.5407s`
- Train loss: `0.0285`
- Training source mix used: `user_correction=35`, `external_dataset=50`, `mock_seed_v3=59`, `mock_seed_v2=44`, `mock_seed=4`

Verification:
- v1 rules: `1.0000` / `1.0000`
- v1 hybrid: `1.0000` / `1.0000`
- v2 rules: `0.9688` / `0.9686`
- v2 hybrid: `0.9688` / `0.9686`
- full backend tests: `122 passed`

Current counts after Cycle C:
- `training_data` total: `1241`
- `training_data(source='user_correction')`: `73`
- `emails.user_corrected=1`: `73`
- review queue count: `0`

## Cycle D (February 26, 2026): Manual Audit of 6 Deferred Items - Completed

Goal:
- Resolve 6 deferred non-rules items that were suspected to be misclassified as `rejection`.

### Step D1 - Content audit (`completed`)

Findings:
- 5 items were indeed not rejection (`applied`/`pending_application`).
- 1 item (Adobe) was a true rejection.

### Step D2 - Apply manual labels (`completed`)

Applied labels:
- `224 -> pending_application`
- `225 -> applied`
- `278 -> applied`
- `260 -> pending_application`
- `589 -> rejection`
- `1 -> applied`

Result:
- `emails_updated=6`
- `training_rows_inserted=6` (`source=user_correction`)
- Labeled artifact written:
  - `backend/data/evaluation/real_labeling_batch_20260226_remaining_manual_labeled.csv`

### Step D3 - Retrain + verify (`completed`)

Retrain:
- Model: `setfit_model_20260226_125304`
- Train loss: `0.0285`
- Training source mix included `user_correction=37` in sampled train set.

Verification:
- v1 rules/hybrid: `1.0000 / 1.0000`
- v2 rules/hybrid: `0.9688 / 0.9686`
- full backend tests: `122 passed`

Current counts after Cycle D:
- `training_data` total: `1247`
- `training_data(source='user_correction')`: `79`
- `emails.user_corrected=1`: `79`
- review queue count: `0`

## Cycle E (February 28, 2026): Weekly Real-Signal Workflow - Completed

Goal:
- Establish a repeatable weekly process for real-signal growth focused on rare lifecycle classes and known confusion pairs.

### Step E1 - Workflow tooling added (`completed`)

Implemented:
- New weekly workflow module:
  - `python -m jobtracker.scripts.weekly_labeling_workflow`
- New root runner command:
  - `scripts/weekly_labeling_cycle.sh --append-tracker`

Outputs:
- `backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_YYYYMMDD.csv`
- `backend/data/evaluation/weekly_labeling/weekly_labeling_summary_YYYYMMDD.{md,json}`
- `backend/data/evaluation/weekly_labeling/weekly_kpi_YYYYMMDD.md`

Privacy guardrails:
- Artifact schema stores IDs + aggregate counts only.
- No subject/body/snippet fields are emitted by the weekly batch CSV.

### Step E2 - KPI tracker integration (`completed`)

Added KPI snapshot generation suitable for weekly appends to `docs/ML_EXECUTION_TRACKER.md`, including:
- `user_correction` weekly delta
- per-label real-signal totals and weekly deltas
- latest retrain real-signal share from `training_metadata.json` source mix

### Step E3 - Data collection run (`completed`)

Run details:
- Initial weekly run selected only high-confidence `applied` items.
- Full iCloud sync attempted and failed once due stale backend process enum mismatch, then succeeded after backend restart:
  - `emails_fetched=852`
  - `emails_saved=154`
  - `emails_skipped=698`
- Re-generated rare-label-focused batch over larger lookback window:
  - selected IDs: `801 (pending_application)`, `766 (interview)`
- Manual corrections applied:
  - `801 -> pending_application` (confirmed)
  - `766 -> other` (newsletter false-positive correction)

Post-run state:
- `training_data(source='user_correction')`: `81` (from `79`)
- per-label delta from this run:
  - `pending_application`: `+1`
  - `other`: `+1`
- Re-generated weekly batch (same settings): `0` remaining candidates.

## Cycle F (February 28, 2026): Monitoring Automation - Completed

Goal:
- Automate weekly confidence/drift monitoring with machine-readable artifacts and thresholded alert signals.

### Step F1 - Monitoring script expanded (`completed`)

Implemented:
- `jobtracker.scripts.generate_ml_monitoring_report` now emits:
  - markdown summary
  - JSON payload
  - optional JSONL history append
- Added trend indicators for:
  - low-confidence window-over-window movement
  - uncorrected label distribution drift
  - confusion-pair signal counts
- Added threshold-based alert output with optional `--fail-on-alert`.

### Step F2 - Scheduled workflow (`completed`)

Added:
- `.github/workflows/ml-monitoring-weekly.yml`
  - weekly schedule + manual dispatch
  - monitoring artifact generation
  - artifact upload (`md`, `json`, `jsonl`)

### Step F3 - Baseline historical run committed (`completed`)

Artifacts:
- `backend/data/evaluation/ml_monitoring_report.md`
- `backend/data/evaluation/ml_monitoring_report.json`
- `backend/data/evaluation/ml_monitoring_history.jsonl`

## Weekly KPI Snapshot (2026-02-28)

### Weekly KPI Snapshot

- generated_at_utc: `2026-02-28T09:40:58.770145`
- real_sources: `user_correction`
- user_correction_total: `79`
- user_correction_last_7_days: `51`
- user_correction_prev_7_days: `21`
- user_correction_weekly_delta: `+30`
- real_signal_share_latest_retrain: `19.27%` (37/192)
- latest_model: `setfit_model_20260226_125304`
- latest_model_trained_at: `2026-02-26T17:53:04.241243`

#### Per-Label Real-Signal Totals
- applied: total=51, last_7d=43, delta_vs_prev_window=+37
- assessment: total=1, last_7d=1, delta_vs_prev_window=+1
- other: total=10, last_7d=0, delta_vs_prev_window=-8
- pending_application: total=2, last_7d=2, delta_vs_prev_window=+2
- rejection: total=15, last_7d=5, delta_vs_prev_window=-2

### Weekly Labeling Batch
- total_candidates: `7`
- reason_counts: confusion_pair_focus=7
- category_counts: applied=7
- candidate_ids: `621, 613, 612, 611, 610, 609, 608`

Artifacts:
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_20260228.csv`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260228.md`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260228.json`

## Cycle G (February 28, 2026): Training Metadata Contract Enforcement - Completed

Goal:
- Make SetFit retrain artifacts auditable with strict provenance contract checks and schema versioning.

### Step G1 - Contract validator enforcement (`completed`)

Implemented:
- Added strict contract validation for `training_metadata.json`:
  - required keys and types
  - scalar consistency (`total_examples`, split sizes)
  - `label_counts`, `source_counts`, and `label_source_counts` rollup integrity
  - exact inverse checks for `label_to_id` and `id_to_label`
- Added explicit schema compatibility guard:
  - `schema_version` required for current artifacts
  - unknown schema versions fail fast
  - legacy compatibility path available only when explicitly enabled

### Step G2 - Retrain artifact emission hardened (`completed`)

Implemented:
- Retrain metadata writer now emits `schema_version`.
- Metadata is validated before it is written to disk to prevent malformed provenance artifacts.

### Step G3 - Contract tests + docs (`completed`)

Implemented:
- Expanded metadata tests to cover:
  - generated metadata contract conformance
  - missing schema version rejection
  - legacy compatibility allowance
  - unsupported schema version rejection
  - source rollup mismatch rejection
- Added metadata contract policy + JSON example in `docs/ML_STRATEGY.md`.

Verification:
- targeted metadata tests: `5 passed`
- full backend suite: `138 passed`

## Cycle H (March 2, 2026): Evaluation v3 Dataset + Baseline Workflow - Completed

Goal:
- Complete issue `#4` by adding a stronger v3 evaluation corpus, reproducible baseline generation workflow, and CI gate coverage for rules.

### Step H1 - Add v3 dataset spec + corpus (`completed`)

Implemented:
- Added machine-readable dataset contract:
  - `backend/data/evaluation/classifier_eval_v3_spec.json`
- Added expanded corpus with edge/noise/confusion coverage:
  - `backend/data/evaluation/classifier_eval_v3.jsonl`

Coverage shape:
- total rows: `96`
- per label: `12` across 8 labels
- includes explicit historical-miss subjects and confusion-pair tagging metadata

### Step H2 - Add baseline generation workflow (`completed`)

Implemented:
- Added reusable root command:
  - `scripts/generate_eval_baselines.sh --version 3`
- Workflow behavior:
  - updates `baseline_rules_v<version>.json`
  - updates `baseline_hybrid_v<version>.json` (optional skip flag)
  - rebuilds benchmark history artifacts

### Step H3 - Generate and commit v3 baselines (`completed`)

Artifacts:
- `backend/data/evaluation/baseline_rules_v3.json`
- `backend/data/evaluation/baseline_hybrid_v3.json`
- refreshed:
  - `backend/data/evaluation/benchmark_history.jsonl`
  - `backend/data/evaluation/benchmark_history.md`

Verification on v3:
- rules: `accuracy=0.9792`, `macro_f1=0.9791`, `misclassified=2`
- hybrid: `accuracy=0.9583`, `macro_f1=0.9583`, `misclassified=4`

### Step H4 - CI + regression coverage updates (`completed`)

Implemented:
- Backend CI rules gate moved to v3 dataset/baseline with macro-F1 floor.
- Hybrid CI signal moved to v3 dataset/baseline (still non-blocking).
- Added dataset contract tests:
  - `backend/tests/test_eval_v3_dataset_contract.py`

Verification:
- v3 rules gate command: `PASS`
- v3 hybrid signal command: `PASS`
- full backend suite: `140 passed`

## Cycle I (March 2, 2026): Deterministic Hybrid CI Stabilization - Completed

Goal:
- Complete issue `#6` by making hybrid benchmark behavior reproducible and safe to use as a blocking CI gate.

### Step I1 - Deterministic hybrid profile in evaluator (`completed`)

Implemented:
- Added `--hybrid-profile` to evaluator with:
  - `full` (default runtime behavior)
  - `deterministic` (disables SetFit + embedding-example state dependence)
- Added profile metadata into reports for hybrid runs.
- Evaluator now initializes DB schema before predictions, eliminating repeated table-missing noise in test environment runs.

### Step I2 - Baseline workflow alignment (`completed`)

Implemented:
- `scripts/generate_eval_baselines.sh` now supports `--hybrid-profile` and defaults hybrid baseline generation to `deterministic`.
- Regenerated `baseline_hybrid_v3.json` using deterministic profile.
- Refreshed benchmark history artifacts.

### Step I3 - CI gate rollout (`completed`)

Implemented:
- Updated backend CI hybrid step to:
  - use v3 dataset/baseline
  - run with `--hybrid-profile deterministic`
  - enforce `--min-macro-f1 0.95`
  - run as blocking gate (removed non-blocking mode)

### Step I4 - Regression tests (`completed`)

Implemented:
- Added evaluator unit coverage for deterministic profile behavior and invalid profile rejection in:
  - `backend/tests/test_evaluate_classifier.py`

Verification:
- v3 rules gate command: `PASS`
- v3 hybrid gate command (deterministic profile): `PASS`
- full backend suite: `142 passed`

## Cycle J (March 3, 2026): Real-Signal Labeling Coverage Expansion - Completed

Goal:
- Complete issue `#2` by improving weekly candidate discovery for sparse real-signal classes (`offer`, `interview`, `pending_application`) without unsafe pseudo-labeling.

### Step J1 - Gap-aware sparse-label prioritization (`completed`)

Implemented:
- Added per-label real-signal gap calculation against configurable target (`--target-per-label`, default `25`).
- Added quota allocation by gap size for low-support candidate sampling.

### Step J2 - Target-label signal mining (`completed`)

Implemented:
- Added `target_label_signal` pool that mines likely sparse-label candidates from subject/body patterns, even when currently classified as other labels.
- Added tunables:
  - `--target-signal-limit`
  - `--target-signal-max-confidence`
- Added `target_signal_labels` field in weekly candidate CSV (privacy-safe metadata only).

### Step J3 - Final-batch balancing safeguards (`completed`)

Implemented:
- Added `--confusion-share-cap` to prevent confusion-pair-only candidates from crowding out sparse-label candidates when alternatives exist.
- Reordered reason priority to favor sparse-label discovery:
  - `low_confidence` → `target_label_signal` → `low_support_category` → `confusion_pair_focus`

### Step J4 - Tests + artifacts (`completed`)

Implemented:
- Expanded weekly workflow tests for:
  - gap-based quota bias behavior
  - target-signal discovery path
  - confusion-share cap selection behavior
- Regenerated weekly artifacts:
  - `weekly_labeling_candidates_20260303.csv`
  - `weekly_labeling_summary_20260303.{md,json}`
  - `weekly_kpi_20260303.md`

Verification:
- `pytest -q tests/test_weekly_labeling_workflow.py` -> `10 passed`
- full backend suite -> `145 passed`

## Weekly KPI Snapshot (2026-03-03)

### Weekly KPI Snapshot

- generated_at_utc: `2026-03-03T00:14:21.801426`
- real_sources: `user_correction`
- user_correction_total: `81`
- user_correction_last_30_days: `81`
- user_correction_prev_30_days: `0`
- user_correction_weekly_delta: `+81`
- real_signal_share_latest_retrain: `19.79%` (38/192)
- latest_model: `setfit_model_20260228_131948`
- latest_model_trained_at: `2026-02-28T18:19:48.379662`

#### Per-Label Real-Signal Totals
- applied: total=51, last_30d=51, delta_vs_prev_window=+51
- assessment: total=1, last_30d=1, delta_vs_prev_window=+1
- other: total=11, last_30d=11, delta_vs_prev_window=+11
- pending_application: total=3, last_30d=3, delta_vs_prev_window=+3
- rejection: total=15, last_30d=15, delta_vs_prev_window=+15

### Weekly Labeling Batch
- total_candidates: `20`
- reason_counts: confusion_pair_focus=19, target_label_signal=1
- category_counts: applied=19, other=1
- candidate_ids: `691, 704, 234, 233, 231, 195, 187, 186, 184, 128, 126, 103, 251, 79, 621, 613, 612, 611, 610, 609`

Artifacts:
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_20260303.csv`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260303.md`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260303.json`

## Cycle K (March 3, 2026): Issue Tracker Synchronization - Completed

Goal:
- Align GitHub issue status with completed code/doc work and create detailed remaining-work issues.

### Step K1 - Close completed implementation issues (`completed`)

Closed:
- `#2` real-signal labeling coverage expansion
- `#3` monitoring automation
- `#4` evaluation v3 + baselines + gates
- `#5` training metadata provenance contract
- `#6` deterministic hybrid benchmark CI gate

### Step K2 - Create detailed remaining-work issues (`completed`)

Opened:
- `#7` ML ops weekly sparse-label review SOP
- `#8` monitoring triage runbook + escalation workflow
- `#9` real-signal-heavy evaluation v4 + baselines
- `#10` classifier-rule governance guardrails

Verification:
- Open issues now represent only remaining execution backlog.

## Cycle L (March 4, 2026): Weekly Ops SOP Operationalization - Completed

Goal:
- Complete issue `#7` by shipping a reproducible weekly operating runbook and validating one full cycle.

### Step L1 - Weekly operations runbook (`completed`)

Implemented:
- Added canonical SOP:
  - `docs/ML_WEEKLY_OPERATIONS.md`
- Documented:
  - exact weekly command bundle
  - sparse-label KPI targets
  - manual review rubric
  - gate verification checklist
  - rollback/escalation actions

### Step L2 - Tracker format standardization (`completed`)

Implemented:
- Added explicit tracker entry format requirements in `docs/ML_WEEKLY_OPERATIONS.md`.
- Added tracker-format assertion coverage in:
  - `backend/tests/test_weekly_labeling_workflow.py`

### Step L3 - End-to-end cycle execution (`completed`)

Run:
- `scripts/weekly_labeling_cycle.sh --append-tracker --days 7 --limit 60 --target-per-label 25 --target-signal-limit 20 --target-signal-max-confidence 0.92 --confusion-share-cap 0.50`

Outputs:
- `backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_20260304.csv`
- `backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260304.{md,json}`
- `backend/data/evaluation/weekly_labeling/weekly_kpi_20260304.md`
- tracker snapshot appended below

Verification:
- v3 rules gate command: `PASS`
- v3 hybrid gate command (deterministic profile): `PASS`
- targeted weekly-workflow tests: `11 passed`
- full backend suite: `146 passed`

## Weekly KPI Snapshot (2026-03-04)

### Weekly KPI Snapshot

- generated_at_utc: `2026-03-04T17:24:11.809470`
- real_sources: `user_correction`
- user_correction_total: `81`
- user_correction_last_7_days: `52`
- user_correction_prev_7_days: `22`
- user_correction_weekly_delta: `+30`
- real_signal_share_latest_retrain: `19.79%` (38/192)
- latest_model: `setfit_model_20260228_131948`
- latest_model_trained_at: `2026-02-28T18:19:48.379662`

#### Per-Label Real-Signal Totals
- applied: total=51, last_7d=43, delta_vs_prev_window=+37
- assessment: total=1, last_7d=1, delta_vs_prev_window=+1
- other: total=11, last_7d=1, delta_vs_prev_window=-7
- pending_application: total=3, last_7d=3, delta_vs_prev_window=+3
- rejection: total=15, last_7d=4, delta_vs_prev_window=-4

### Weekly Labeling Batch
- total_candidates: `2`
- reason_counts: confusion_pair_focus=1, target_label_signal=1
- category_counts: applied=1, other=1
- candidate_ids: `691, 704`

Artifacts:
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_20260304.csv`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260304.md`
- `/Users/ayush/Documents/Projects/jobtracker/backend/data/evaluation/weekly_labeling/weekly_labeling_summary_20260304.json`
