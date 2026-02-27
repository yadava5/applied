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
