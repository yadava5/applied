# ML Strategy

> **Scope, added 2026-08-15 — none of the training in this document runs in the
> hosted deployment.**
>
> This file describes the full three-layer design and the local operator loop
> around it. The deployed app is **rules-only**: `HybridClassifier.classify`
> short-circuits to the rules layer whenever `settings.deployment == "cloud"`
> (`backend/jobtracker/classifier/hybrid.py:284`), which is every hosted request,
> so layers 2 and 3 never load and no hosted path retrains anything. A user
> correction is written to `training_data` and flagged reviewed, and that is
> where it stops — no deployed reader consumes the table, so a correction does
> not change any future classification.
>
> Read the imperatives below as addressed to an operator running a backend on
> their own machine, not as a description of production. Two specifics worth
> knowing before following them:
>
> - **`POST /classify/retrain` and `POST /classify/import-training-data` are not
>   routes in this tree.** No module defines them; the production app registers
>   four routers — applications, Gmail, account, cron
>   (`backend/jobtracker/main_cloud.py:667-684`). The desktop client that served
>   them was de-scoped in August 2026. The shell scripts named here
>   (`scripts/ml_cycle.sh`, `scripts/train_pipeline.sh`,
>   `scripts/weekly_labeling_cycle.sh`, `scripts/monitoring_cycle.sh`) do still
>   exist and are run by hand; none runs in CI or on Vercel.
> - **Training is default-deny even locally.** Since #357 every training entry
>   point refuses unless the corpus is wholly synthetic or its single owner is on
>   an explicit allowlist, which is empty unless configured
>   (`backend/jobtracker/classifier/setfit_model.py:38-75`). Applied reads mail
>   under Gmail's restricted `gmail.readonly` scope, and Google's Workspace API
>   user-data policy permits training only a model personalized to one end user,
>   with no co-mingling — so an unconfigured deployment training on nobody is the
>   intended state, not a gap.
>
> The machinery is documented rather than deleted because it exists and ships in
> the repository; what it is not is reachable.

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
- review queue: lifecycle verdicts from `0.70` up to the `0.85` auto-file gate,
  **plus** verdicts that clear the gate but whose employer could not be named or
  whose application could not be picked. The gate is not the only condition for
  auto-filing, so the queue is not the sub-gate band — see
  [ML_CORPUS_INTEGRITY.md](ML_CORPUS_INTEGRITY.md#what-actually-reaches-the-review-queue)

Content guards force obvious non-application content (newsletters/job-alert digests/promotions/security codes) to `other`.

## Data Sources for Learning

### 1. User Corrections

When a user corrects the classification **of a message**:

- email row is updated
- training sample is inserted into `training_data`
- embedding is stored in `email_embeddings`

This immediately improves similarity matching and contributes to SetFit training eligibility.

Only a per-message decision writes a training sample. Whole-row actions — a
stage correction (`PATCH /applications/{id}`) and a dismissal — deliberately
write none: a stage is a fact about an application, not a label for any of its
messages. See [ML_CORPUS_INTEGRITY.md](ML_CORPUS_INTEGRITY.md) for what the old
behaviour put in the production corpus and which rows are suspect.

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

If no trained SetFit model exists, classifier still runs with rules + embeddings.

### Training Metadata Contract

`training_metadata.json` is validated by `validate_training_metadata_contract(...)` in
`backend/jobtracker/classifier/setfit_model.py`. CI tests enforce the contract so refactors
cannot silently drop provenance fields.

Required fields:

- `schema_version` (integer, currently `1`)
- `trained_at` (ISO-8601 timestamp string)
- `base_model` (string)
- `total_examples` (integer)
- `train_split_size` (integer)
- `eval_split_size` (integer)
- `max_saved_models` (integer > 0)
- `label_counts` (object: `label -> count`)
- `source_counts` (object: `source -> count`)
- `label_source_counts` (object: `label -> source -> count`)
- `label_to_id` (object: `label -> id`)
- `id_to_label` (object: `id -> label`)

Contract invariants:

- `sum(label_counts) == total_examples`
- `sum(source_counts) == total_examples`
- `train_split_size + eval_split_size == total_examples`
- `label_source_counts` must roll up exactly to both `label_counts` and `source_counts`
- `label_to_id` and `id_to_label` must be exact inverses

Example:

```json
{
  "schema_version": 1,
  "trained_at": "2026-02-28T10:30:00",
  "base_model": "sentence-transformers/paraphrase-MiniLM-L6-v2",
  "total_examples": 48,
  "label_counts": {
    "applied": 18,
    "pending_application": 12,
    "rejection": 18
  },
  "source_counts": {
    "external_dataset": 20,
    "user_correction": 28
  },
  "label_source_counts": {
    "applied": {
      "external_dataset": 8,
      "user_correction": 10
    },
    "pending_application": {
      "external_dataset": 4,
      "user_correction": 8
    },
    "rejection": {
      "external_dataset": 8,
      "user_correction": 10
    }
  },
  "label_to_id": {
    "applied": 0,
    "pending_application": 1,
    "rejection": 2
  },
  "id_to_label": {
    "0": "applied",
    "1": "pending_application",
    "2": "rejection"
  },
  "train_split_size": 43,
  "eval_split_size": 5,
  "max_saved_models": 3
}
```

Backward compatibility note:

- legacy artifacts without `schema_version` are accepted only when explicitly loaded with
  `allow_legacy_without_schema_version=True`
- unknown future schema versions fail fast until compatibility is intentionally added

## Runtime Controls

**None of these four routes is defined in this tree** (checked 2026-08-15). They
belonged to the desktop FastAPI app that was de-scoped in August 2026; no module
declares them and the production app registers four routers — applications,
Gmail, account, cron (`backend/jobtracker/main_cloud.py:667-684`). The only
classification route that exists is `POST
/applications/review/{message_id}/classify` (`cloud/applications.py:3459`), which
records a decision and does not train. Kept listed because the underlying
capabilities still exist as Python (`HybridClassifier.get_status`, the
`lite_mode` setting, `SetFitClassifier.train`); what is gone is the HTTP surface.

- `GET /classify/status`
- `GET /classify/lite-mode`
- `PUT /classify/lite-mode`
- `POST /classify/retrain`

## Evaluation and Non-Regression

Classifier evaluation harness:

- `python -m jobtracker.scripts.evaluate_classifier`

Versioned benchmark assets:

- `backend/data/evaluation/classifier_eval_v1.jsonl`
- `backend/data/evaluation/classifier_eval_v2.jsonl`
- `backend/data/evaluation/classifier_eval_v3.jsonl`
- `backend/data/evaluation/classifier_eval_v3_spec.json`
- `backend/data/evaluation/baseline_rules_v1.json`
- `backend/data/evaluation/baseline_hybrid_v1.json`
- `backend/data/evaluation/baseline_rules_v2.json`
- `backend/data/evaluation/baseline_hybrid_v2.json`
- `backend/data/evaluation/baseline_rules_v3.json`
- `backend/data/evaluation/baseline_hybrid_v3.json`

Core output metrics:

- per-class precision/recall/F1
- overall accuracy
- macro-F1
- weighted-F1
- confusion matrix

CI (`.github/workflows/backend-ci.yml`) runs blocking v3 gates for both rules and hybrid:
- rules gate uses the default runtime profile
- hybrid gate uses `--hybrid-profile deterministic`

Both fail on baseline regressions (with configured tolerance) or when macro-F1 drops below
the configured floor. This protects against silent quality regressions from rule or pipeline changes.

Hybrid benchmark track supports profiles:
- `full`: normal runtime behavior with available semantic layers
- `deterministic`: disables stateful semantic layers for machine-stable CI gating

Use deterministic profile for reproducible gates:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --hybrid-profile deterministic
```

Use full profile for exploratory local checks against your current semantic-layer state:

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --hybrid-profile full
```

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

Baseline update workflow for versioned evaluation sets:

```bash
scripts/generate_eval_baselines.sh --version 3
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
4. ~~Trigger `POST /classify/retrain` after substantial new corrections if auto-train has not run yet~~ — **not available.** That route is not defined in this tree (see Runtime Controls), and no auto-train runs in the hosted app. Steps 1–3 still help: they make the board correct and the corrections durable. They do not make the classifier better, because nothing reads the corpus back.

## Monitoring and Drift

Monitoring command (single command, emits markdown + JSON):

```bash
scripts/monitoring_cycle.sh --days 7 --append-history
```

Artifacts:

- `backend/data/evaluation/ml_monitoring_report.md`
- `backend/data/evaluation/ml_monitoring_report.json`
- `backend/data/evaluation/ml_monitoring_history.jsonl`

Default alert thresholds:

- low-confidence growth: `>=25%` window-over-window (only when previous volume >= 5)
- low-confidence absolute delta: `>=10`
- max label distribution drift: `>=12 pp` (only when each window has >= 20 samples)
- confusion-pair low-confidence volume: `>=3`

Scheduled automation:

- `.github/workflows/ml-monitoring-weekly.yml`
- workflow prepares alert issue payload files when alerts are present
- workflow can open a monitoring triage issue (`monitoring`, `ml`) with duplicate-title guard

Operational triage runbook:

- `docs/ML_MONITORING_RUNBOOK.md`
- issue template: `.github/ISSUE_TEMPLATE/ml-monitoring-alert.md`

## Weekly Real-Signal Workflow

To keep `user_correction` growth consistent for rare lifecycle classes, run:

```bash
scripts/weekly_labeling_cycle.sh --append-tracker
```

Operational SOP (cadence, rubric, gates, escalation) lives in:

- `docs/ML_WEEKLY_OPERATIONS.md`

Common tuning flags (no code edits needed):

- `--low-confidence-threshold`
- `--confusion-max-confidence`
- `--confusion-share-cap`
- `--target-labels`
- `--target-per-label`
- `--target-signal-limit`
- `--target-signal-max-confidence`
- `--confusion-pairs`
- `--query-overfetch-multiplier`

This command creates privacy-safe weekly artifacts (IDs + aggregate counts only, no email snippets/body content):

- `backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_YYYYMMDD.csv`
- `backend/data/evaluation/weekly_labeling/weekly_labeling_summary_YYYYMMDD.{md,json}`
- `backend/data/evaluation/weekly_labeling/weekly_kpi_YYYYMMDD.md`

It targets:

1. Lowest-confidence job predictions
2. Known confusion pairs (`assessment` vs `follow_up`, `applied` vs `pending_application`)
3. Low-support labels (`offer`, `interview`, `pending_application`) using gap-aware quotas
4. Target-label signal mining in subject/body text to surface likely sparse-label items even when currently misclassified

Selection behavior notes:

- `target_label_signal` candidates are prioritized ahead of confusion-pair-only items.
- `--confusion-share-cap` limits how much of the final batch can be driven primarily by confusion-pair focus, preventing `applied`-heavy batches from crowding out sparse-label discovery.

When `--append-tracker` is used, it appends KPI snapshots into `docs/ML_EXECUTION_TRACKER.md` including:

- weekly `user_correction` delta
- per-label real-signal counts
- real-signal share in latest retrain sample metadata

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

3. **`import_to_db.py`** — Inserts verified candidates into `training_data` table (tagged `source='external_dataset'`). Checks SetFit training gates and calls `SetFitClassifier.train` in-process if met. This is an operator command run by hand against a local backend; it is in no workflow and the hosted app never invokes it. The train call is itself default-deny — `external_dataset` counts as synthetic, so an import of public corpora proceeds, but a corpus holding any real `user_correction` row is refused unless that user is allowlisted.

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

Then retrain — but note that `POST /classify/retrain` is not a route in this tree
(see Runtime Controls). Retraining is reachable only in-process, by an operator
calling `SetFitClassifier.train(user_id=…)` on a local backend, and it refuses
unless the corpus is synthetic or the owner is allowlisted.
