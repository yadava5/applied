# ML Strategy

## Goal

Classify synced emails into job-pipeline categories so they can be linked to applications and routed to the review queue when uncertain.

## Categories

- `applied`
- `pending_application`
- `interview`
- `rejection`
- `offer`
- `assessment`
- `follow_up`
- `needs_review`
- `other`

## Hybrid Pipeline

Classifier implementation: `backend/jobtracker/classifier/hybrid.py`

Decision order:

1. Rules layer
2. Embedding similarity layer
3. SetFit layer
4. Fallback (with `needs_review` safety net)

Main confidence behavior:

- rules shortcut when confidence `>= 0.90`
- embeddings accepted when similarity `>= 0.85`
- SetFit accepted when confidence `>= 0.70`
- review queue threshold: `< 0.85` for job-relevant/uncertain items

Content guards force obvious non-application content (newsletters/job-alert digests/promotions/security codes) to `other`.

## Data Sources for Learning

### 1. User Corrections

When a user corrects classification:

- email row is updated
- training sample is inserted into `training_data`
- embedding is stored in `email_embeddings`

This immediately improves similarity matching and contributes to SetFit training eligibility.

### 2. Approved Review Queue Items

Approving a queued item also feeds a correction sample into training.

### 3. Optional Seed Data

`POST /classify/seed-training-data` can bootstrap `training_data` from high-confidence rule outputs.

## SetFit Training Lifecycle

SetFit implementation: `backend/jobtracker/classifier/setfit_model.py`

Training gates:

- minimum total examples: `40`
- at least `3` categories with enough samples
- minimum examples per category: `5`

Operational behavior:

- training runs in background
- models are saved under `~/Library/Application Support/JobTracker/models/setfit/`
- latest model is loaded on startup
- only recent model versions are retained
- each trained model directory includes `training_metadata.json` provenance
  (timestamp, label counts, split sizes, label mapping)

If no trained SetFit model exists, classifier still runs with rules + embeddings.

## Runtime Controls

- `GET /classify/status`
- `GET /classify/lite-mode`
- `PUT /classify/lite-mode`
- `POST /classify/retrain`

## Evaluation and Non-Regression

Classifier evaluation harness:

- `python -m jobtracker.scripts.evaluate_classifier`

Versioned benchmark assets:

- `backend/data/evaluation/classifier_eval_v1.jsonl`
- `backend/data/evaluation/baseline_rules_v1.json`
- `backend/data/evaluation/baseline_hybrid_v1.json`

Core output metrics:

- per-class precision/recall/F1
- overall accuracy
- macro-F1
- weighted-F1
- confusion matrix

CI (`.github/workflows/backend-ci.yml`) runs this harness in `rules` mode and fails on
baseline regressions (with configured tolerance) or when macro-F1 drops below floor.
This protects against silent quality regressions from rule or pipeline changes.

Hybrid benchmark track is available for full pipeline checks:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v1.jsonl
```

Hybrid checks are intentionally not in CI yet because they depend on local model state
(SetFit model availability/version and embedding model warmup), which can reduce run determinism.

Category performance history artifacts can be generated from all baseline files:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.build_benchmark_history
```

Generated outputs:

- `backend/data/evaluation/benchmark_history.jsonl`
- `backend/data/evaluation/benchmark_history.md`

Standardized end-to-end ML cycle command:

```bash
scripts/ml_cycle.sh
```

Optional flags:

- `--import-mock` (imports `mock_training_data.jsonl` as `source=mock_seed`)
- `--retrain` (forces SetFit retraining before evaluations)

Lite mode disables SetFit inference for lower-resource setups while keeping rules + embeddings active.

## Practical Guidance

For better accuracy:

1. Correct misclassified emails in the app regularly
2. Approve valid review-queue items instead of leaving them pending
3. Keep labels consistent (especially `pending_application` vs `applied`)
4. Trigger `POST /classify/retrain` after substantial new corrections if auto-train has not run yet

## External Data Ingestion

### Purpose

Bootstrap the classifier with labeled examples from free, commercially-safe public datasets to reach the SetFit training gate (40 examples, 3+ categories, 5+ each) faster than relying solely on user corrections.

### Datasets Used

| Dataset | License | Role |
|---------|---------|------|
| Berkeley Enron subset (~1703 emails) | Public domain (FERC release) | Employment-category emails → auto-labeled via rules engine |
| SpamAssassin Public Corpus (~6047 msgs) | Apache 2.0 | Spam → `other` negatives; Ham → `other` negatives |
| Charlie9 Enron Intent Dataset (MIT) | MIT | `intent_pos` → `follow_up` seeds; `intent_neg` → `other` |
| Kaggle Job Application Emails (497 rows) | CC0 1.0 | Auto-labeled → `applied`, `interview`, `rejection`, `assessment`, `offer` via regex |
| Kaggle Application Rejection Emails (129 rows) | CC0 1.0 | `reject` → `rejection`; `not_reject` → rules engine fallback |

All datasets are stored locally (`backend/data/external/`, gitignored) and never committed.

### Pipeline

```
scripts/download_datasets.sh     # one-time download (~30 MB, 3 open datasets)
kaggle datasets download ...     # one-time download (2 Kaggle datasets, requires kaggle CLI)
scripts/train_pipeline.sh        # parse → review → import → retrain
```

Three Python scripts in `backend/jobtracker/scripts/`:

1. **`ingest_datasets.py`** — Parses raw files into `backend/data/processed/candidates.jsonl`. Auto-labels using rules engine and regex heuristics, applies quality filters, deduplicates, and caps class balance (max 60 `other`, 30 per job category). Includes parsers for all 5 datasets: Berkeley Enron (per-email `.cats` files), SpamAssassin, Charlie9 (plain text `intent_pos`/`intent_neg`), Kaggle Job Application Emails (CSV with regex category assignment), and Kaggle Rejection Emails (CSV with reject/not_reject labels).

2. **`review_candidates.py`** — Terminal UI for manually reviewing ambiguous auto-labels. Shows subject + body preview, lets you press 1–8 to assign a label or Enter to accept.

3. **`import_to_db.py`** — Inserts verified candidates into `training_data` table (tagged `source='external_dataset'`). Checks SetFit training gates and triggers retraining automatically if met.

### Bulk Import API

`POST /classify/import-training-data` — Accepts JSON array of `{subject, body_text, label}` objects. Validates, deduplicates, inserts into `training_data`, and optionally triggers SetFit retraining. Useful for future drag-and-drop UI.

### Mock Seed Import (Local Script)

To import the local mock dataset as controlled seed examples:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.import_jsonl_training_data \
  --input data/external/mock_training_data.jsonl \
  --source mock_seed
```

Notes:

- rows with label `needs_review` are skipped (invalid for training import)
- imported rows can be filtered by `source='mock_seed'` in `training_data`

### Removing External Data

External training rows are tagged with `source='external_dataset'`. To remove:

```sql
DELETE FROM training_data WHERE source = 'external_dataset';
```

Then retrain: `POST /classify/retrain`.
