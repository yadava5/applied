# JobTracker Detailed Timeline

As of **March 3, 2026**.

This is the continuity document for product and ML behavior. It records what changed, why it changed, what was verified, and what remains open.

## Why this file exists

- Prior sessions lost critical context due context-window limits.
- Classifier quality depended on interactions between rules, embeddings, SetFit, and data ingestion; isolated notes were insufficient.
- Regressions were often caused by good-intention changes without a durable historical record of rationale.

## Current Snapshot (March 3, 2026)

- Architecture remains local-first: SwiftUI macOS app + local FastAPI backend + SQLite.
- Classification stack remains hybrid: `rules -> embeddings -> SetFit -> fallback/needs_review`.
- Categories: `applied`, `pending_application`, `interview`, `rejection`, `offer`, `assessment`, `follow_up`, `needs_review`, `other`.
- Rules no longer contain narrow brand/one-off marketing phrase patches; only broad safety guard families are retained for newsletter/promo/security content.
- SetFit retraining now uses balanced per-label sampling with mixed source quotas (not single-source dominance).
- Current training data footprint in DB:
  - total rows: `1,249` (latest recorded run)
  - sources: `mock_seed_v3=640`, `mock_seed_v2=320`, `external_dataset=192`, `user_correction=81`, `mock_seed=16`
- Latest SetFit model:
  - path: `setfit_model_20260228_131948`
  - trained at: `2026-02-28T18:19:48Z`
  - training examples: `192` (`24` per label across 8 labels)
  - source mix used for this train: stored in model artifact metadata
- Quality gates currently passing:
  - eval v1 rules: `1.0000 accuracy / 1.0000 macro-F1`
  - eval v1 hybrid: `1.0000 accuracy / 1.0000 macro-F1`
  - eval v2 rules: `0.9688 accuracy / 0.9686 macro-F1` (latest spot run)
  - eval v2 hybrid: `0.9531 accuracy / 0.9526 macro-F1` (latest spot run)
  - eval v3 rules baseline: `0.9792 accuracy / 0.9791 macro-F1`
  - eval v3 hybrid baseline (deterministic profile): `0.9792 accuracy / 0.9791 macro-F1`
  - backend tests: `145 passed`

## Chronology

## 2025 (Foundation)

### Phase 0: Local-first architecture

Context:
- Product goal required privacy and responsiveness for personal job-search email data.

Decision:
- Keep processing local: SwiftUI desktop app + local FastAPI backend + SQLite.

Impact:
- Fast iteration and easier debugging without cloud dependencies.

### Phase 1: Initial hybrid classifier and review loop

Context:
- Needed useful day-1 classification before enough user corrections existed.

What shipped:
- Three-layer hybrid (rules/embeddings/SetFit) with conservative fallback and review queue.
- Correction pipeline into `training_data` for continual improvement.

Impact:
- Immediate baseline utility + long-term learning mechanism.

## February 2026 (ML hardening)

### Phase 2: Ingestion parser fixes and reproducibility

Context:
- External datasets were required to accelerate cold-start model quality.

What changed:
- Fixed Enron/Charlie9 parser mismatches and ingestion edge cases.
- Pinned `transformers` compatibility to avoid SetFit breakage.

Impact:
- Deterministic ingestion and reproducible dataset loading.

### Phase 3: External dataset expansion

What changed:
- Added Kaggle job-email/rejection datasets and label mapping.
- Re-ingested all supported public sources.

Impact:
- Training set reached thresholds for SetFit activation.

### Phase 4: First SetFit activation

What changed:
- Triggered retrain after data thresholds passed.

Impact:
- SetFit became active, improving non-rule phrasing coverage.
- Spot checks improved but were not yet a locked benchmark.

### Phase 5: Real-stream regression hardening

Context:
- Production email streams exposed failure cases not present in seed datasets.

What changed:
- Added regressions for classification/extraction flows.
- Tightened handling for alerts/newsletters/promotional mail routing to `other`.

Impact:
- Fewer repeated false positives on real inbox traffic.

### Phase 6: Continuity documentation

What changed:
- Added project continuity docs (`timeline.md`, `NEXT_STEPS.md`) and mock seed dataset.

Impact:
- Sessions could resume with lower context-loss risk.

### Phase 7: Quantitative regression gate (CI)

What changed:
- Added evaluator + versioned eval corpora + baseline checks in CI.

Impact:
- Classifier changes became measurable and enforceable, not ad-hoc.

### Phase 8: Hybrid eval baseline and SetFit prediction compatibility

What changed:
- Added separate rules/hybrid baselines.
- Fixed SetFit output parsing to support string + numeric labels.

Impact:
- Hybrid track became stable across environments.

## February 26, 2026 (Model-first cleanup cycle)

### Phase 9: Roll back targeted phrase-level rule shortcuts

Context:
- Several narrowly targeted regex additions had been introduced to patch specific misses.
- Risk: brittle behavior and hidden maintenance debt.

What changed:
- Removed narrow phrase-level additions and follow-up intent shortcut logic added as tactical fixes.
- Kept broad safety families only for non-job content in rules (newsletter/promotional/security).

Why:
- Move decision quality back toward model confidence and representative training data.
- Avoid overfitting behavior to a handful of observed strings.

### Phase 10: Larger neutral synthetic dataset (v3)

Context:
- Existing mock set was balanced but lexically narrow.

What changed:
- Expanded generator template diversity per category with neutral/random variation.
- Generated `mock_training_data_v3.jsonl` with `640` rows (`80` per label, 8 labels).
- Imported as new source `mock_seed_v3`.

Bias controls:
- No demographic/protected attributes in generation.
- Neutral company/role pools with seeded randomness.
- Balanced per-label output.

### Phase 11: SetFit sampling redesign for broader source coverage

Context:
- Prior sampler could overuse high-priority sources and underuse diverse mock/real mix.

What changed:
- Increased cap to `24` examples per label.
- Added source-aware per-label targets + round-robin fill.
- Added provenance metadata in model artifacts:
  - `source_counts`
  - `label_source_counts`

Impact:
- Retraining now blends `user_correction`, `external_dataset`, and multiple mock sources instead of effectively single-source slices.

### Phase 12: Confidence arbitration in hybrid layer

Context:
- Semantic layer occasionally overrode valid low/medium-confidence non-`other` rules outcomes with `other`.

What changed:
- Added confidence-based guard:
  - ignore semantic `other` override when rules already predict a non-`other` class with sufficient confidence.

Impact:
- Reduced avoidable lifecycle->`other` flips without adding narrow phrase hacks.

### Phase 13: Retrain + full verification after cleanup

Retrain:
- model: `setfit_model_20260226_120511`
- runtime: ~`392.9s`
- train loss: `0.0282`

Verification:
- `evaluate_classifier` v1 rules/hybrid: pass baseline.
- `evaluate_classifier` v2 rules/hybrid: pass baseline.
- full backend test suite: `122 passed`.

Result:
- Cleanup objective achieved: no narrow shortcut-heavy rules, broader mixed-source retrain, and no benchmark/test regression.

### Phase 14: Real inbox labeling pass after iCloud sync (February 26, 2026)

Context:
- After sync, the explicit review queue was empty (`0`), so there were no low-confidence candidates to review in the normal flow.
- Real-signal growth still mattered because user-correction volume was the smallest high-value source.

What changed:
- Ran iCloud sync and ingested `88` new emails.
- Built a real 50-email labeling batch artifact with snippets for fast review.
- Applied conservative auto-approval policy:
  - approve only `rules`-classified items from the batch
  - skip non-rules items to avoid reinforcing uncertain pseudo-labels
- Approved/learned from `44` real emails and inserted `44` new `user_correction` training rows.
- Retrained SetFit again and validated all gates.

Outcome:
- `user_correction` rows increased from `29` to `73`.
- `emails.user_corrected` increased to `73`.
- Review queue remained `0` after processing.
- New model `setfit_model_20260226_122427` trained successfully and passed all test/eval gates.

### Phase 15: Manual correction of deferred non-rules items (February 26, 2026)

Context:
- Six deferred items from the real-labeling batch were flagged as suspicious.
- User review confirmed that most were not rejections.

What changed:
- Audited all 6 bodies manually.
- Corrected labels to:
  - `pending_application`: 224, 260
  - `applied`: 225, 278, 1
  - `rejection`: 589
- Inserted all 6 as `user_correction` training signals.
- Retrained SetFit and re-ran evaluation + test gates.

Outcome:
- User-correction signal increased again (`79` total).
- New model `setfit_model_20260226_125304` passed all gates.

### Phase 16: Weekly labeling workflow automation (February 28, 2026)

Context:
- Real-signal growth needed a repeatable operational cadence, especially for rare lifecycle classes.

What changed:
- Added weekly workflow tooling and wrapper command:
  - `python -m jobtracker.scripts.weekly_labeling_workflow`
  - `scripts/weekly_labeling_cycle.sh --append-tracker`
- Added privacy-safe weekly artifacts:
  - candidates CSV (IDs + predicted metadata)
  - JSON/Markdown summary
  - KPI markdown snapshot
- Appended KPI snapshots into `docs/ML_EXECUTION_TRACKER.md`.

Impact:
- Real-signal growth is now operationalized as a repeatable weekly process.

### Phase 17: Monitoring automation and metadata-contract enforcement (February 28, 2026)

Context:
- Needed machine-readable confidence/drift monitoring and strict provenance contract guarantees for SetFit retrains.

What changed:
- Monitoring:
  - Expanded monitoring report script to emit markdown + JSON + optional JSONL history.
  - Added alert thresholds for low-confidence growth/delta, distribution drift, and confusion pairs.
  - Added scheduled workflow `.github/workflows/ml-monitoring-weekly.yml`.
- Metadata contract:
  - Added strict validator for `training_metadata.json` with schema version checks.
  - Enforced required keys/types/invariants and source/label rollup consistency.
  - Retrain metadata writer now emits `schema_version` and validates before write.
  - Added regression tests and docs contract example.

Impact:
- Weekly monitoring became automated and auditable.
- Retrain artifact provenance is now strict and CI-protected against contract regressions.

### Phase 18: Evaluation v3 + baseline workflow + CI gate refresh (March 2, 2026)

Context:
- Evaluation coverage needed stronger edge-case/confusion-pair representation and explicit reproducible baseline refresh commands.

What changed:
- Added `classifier_eval_v3.jsonl` and machine-readable contract `classifier_eval_v3_spec.json`.
- Added baseline workflow script `scripts/generate_eval_baselines.sh`.
- Generated and committed `baseline_rules_v3.json` and `baseline_hybrid_v3.json`.
- Refreshed benchmark history artifacts from all baseline versions.
- Updated backend CI to use v3 rules blocking gate and v3 hybrid non-blocking signal.
- Added dataset contract tests for v3 coverage/historical-miss presence.

Impact:
- Evaluation corpus quality and governance moved from ad-hoc updates to explicit contract + repeatable generation workflow.
- CI rules protection now reflects the latest high-coverage benchmark set.

### Phase 19: Deterministic hybrid benchmark gating (March 2, 2026)

Context:
- Hybrid benchmark output varied by machine because local semantic-layer state (especially SetFit artifacts) could influence results.

What changed:
- Added hybrid evaluator profiles:
  - `full` (runtime state aware)
  - `deterministic` (state-independent for CI)
- Hybrid v3 baseline regenerated with deterministic profile.
- Backend CI hybrid step switched from non-blocking signal to blocking gate using deterministic profile and macro-F1 floor.
- Added evaluator tests covering deterministic-profile behavior.

Impact:
- Hybrid benchmark gate is now reproducible and safe to enforce in CI.

### Phase 20: Real-signal sparse-label coverage expansion (March 3, 2026)

Context:
- Weekly batches could become dominated by confusion-pair candidates (often `applied`), which limited discovery of true sparse-label corrections for `offer`, `interview`, and `pending_application`.

What changed:
- Added gap-aware sparse-label quotas (`--target-per-label`) in weekly labeling workflow.
- Added target-label signal mining from subject/body text for sparse classes:
  - `--target-signal-limit`
  - `--target-signal-max-confidence`
- Added final-batch balancing guard:
  - `--confusion-share-cap`
- Added workflow tests covering quota bias, signal-mining selection, and cap behavior.

Impact:
- Weekly candidate generation now explicitly optimizes for sparse real-signal growth while preserving privacy-safe artifact outputs.

## Open Risks / Remaining Work

- Real user-correction volume is still modest (`81`) relative to synthetic and external data.
- `offer` remains low in real-world examples; synthetic helps coverage but cannot replace true distribution.
- Real-signal coverage for sparse labels remains the main model-quality bottleneck.

## Immediate Priorities

1. Increase real correction volume for rare classes (`offer`, `assessment`, `pending_application`).
2. Execute weekly review loop on generated candidates and apply confirmed corrections.
3. Continue avoiding narrow phrase patches unless backed by broad data and evaluation.

## Resume Checklist

1. Read this file first.
2. Read `docs/ML_STRATEGY.md` and `docs/NEXT_STEPS.md`.
3. Run evaluator locally:
   - `cd backend`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_rules_v1.json`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v1.jsonl --baseline data/evaluation/baseline_hybrid_v1.json`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_rules_v2.json`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v2.jsonl --baseline data/evaluation/baseline_hybrid_v2.json`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode rules --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_rules_v3.json`
   - `.venv311/bin/python -m jobtracker.scripts.evaluate_classifier --mode hybrid --dataset data/evaluation/classifier_eval_v3.jsonl --baseline data/evaluation/baseline_hybrid_v3.json --hybrid-profile deterministic`
4. Run tests:
   - `.venv311/bin/pytest -q`
