# ML Weekly Operations SOP

Updated: **March 4, 2026**
Owner: ML maintainer on weekly rotation

This runbook defines the weekly sparse-label review cycle for real-signal growth,
with a repeatable command bundle, review rubric, and verification checklist.

## Goals

- Increase real correction coverage for `offer`, `interview`, `pending_application`.
- Keep weekly labeling artifacts privacy-safe (IDs + aggregate counts only).
- Run retrain and non-regression checks before closing the weekly cycle.

## Weekly Cadence

- Run once per week (recommended: Tuesday or Wednesday).
- Run an extra cycle only when monitoring alerts or major classifier changes warrant it.

## Preflight Checklist

1. Ensure backend dependencies are available (`backend/.venv311` preferred).
2. Ensure backend DB is accessible.
3. Confirm a clean working tree before generating artifacts.

## Command Bundle (End-to-End)

### Step 1: Generate weekly candidate batch + KPI snapshot

```bash
scripts/weekly_labeling_cycle.sh \
  --append-tracker \
  --days 7 \
  --limit 60 \
  --target-per-label 25 \
  --target-signal-limit 20 \
  --target-signal-max-confidence 0.92 \
  --confusion-share-cap 0.50
```

Expected artifacts:

- `backend/data/evaluation/weekly_labeling/weekly_labeling_candidates_YYYYMMDD.csv`
- `backend/data/evaluation/weekly_labeling/weekly_labeling_summary_YYYYMMDD.{md,json}`
- `backend/data/evaluation/weekly_labeling/weekly_kpi_YYYYMMDD.md`
- tracker append in `docs/ML_EXECUTION_TRACKER.md`

### Step 2: Manual review rubric

Use `weekly_labeling_candidates_YYYYMMDD.csv` and review each row:

- Fill `reviewed_label` only when you are confident.
- Leave `reviewed_label` blank when still ambiguous.
- Use `notes` for ambiguity rationale.

Label decision rules:

- `offer`: explicit compensation/start date/offer acceptance language.
- `interview`: interview scheduling, recruiter/hiring manager interview coordination.
- `pending_application`: action-required/incomplete application states before submission.
- `applied`: confirmation of completed submission.
- `rejection`: explicit rejection outcome.
- `other`: non-job content, newsletters, promotions, unrelated updates.

### Step 3: Apply corrections

Apply reviewed labels through correction endpoint (one row at a time):

```bash
curl -X PUT "http://127.0.0.1:8000/classify/email/<EMAIL_ID>/correct" \
  -H "Content-Type: application/json" \
  -d '{"category":"<REVIEWED_LABEL>"}'
```

### Step 4: Trigger retrain

```bash
curl -X POST "http://127.0.0.1:8000/classify/retrain"
```

Wait for retrain completion before gate verification.

### Step 5: Gate verification checklist

```bash
cd backend
.venv311/bin/python -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_rules_v3.json \
  --tolerance 0.001 \
  --min-macro-f1 0.95

.venv311/bin/python -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_hybrid_v3.json \
  --hybrid-profile deterministic \
  --tolerance 0.001 \
  --min-macro-f1 0.95

.venv311/bin/pytest -q
```

### Step 6: Commit cycle artifacts

Commit:

- new weekly labeling artifacts for the run date
- tracker update entry
- any accompanying docs/runbook updates

## Weekly KPI Targets

Minimum weekly confirmed corrections (initial operating targets):

| Label | Weekly Minimum | Escalation Trigger |
|------|------:|------|
| `offer` | 2 | `<1` for 2 consecutive weeks |
| `interview` | 3 | `<2` for 2 consecutive weeks |
| `pending_application` | 3 | `<2` for 2 consecutive weeks |

Secondary KPI targets:

- `user_correction_weekly_delta` should be positive.
- `real_signal_share_latest_retrain` should be non-decreasing trend over 4-week windows.

## Standard Tracker Entry Format

Each weekly tracker block in `docs/ML_EXECUTION_TRACKER.md` must include:

1. `## Weekly KPI Snapshot (YYYY-MM-DD)` heading
2. `### Weekly KPI Snapshot` section
3. required KPI fields:
   - `generated_at_utc`
   - `real_sources`
   - `user_correction_total`
   - `user_correction_last_<window>_days`
   - `user_correction_prev_<window>_days`
   - `user_correction_weekly_delta`
   - `real_signal_share_latest_retrain`
4. `#### Per-Label Real-Signal Totals`
5. `### Weekly Labeling Batch` summary with:
   - `total_candidates`
   - `reason_counts`
   - `category_counts`
   - `candidate_ids`
6. artifact paths (csv, summary md, summary json)

## Rollback and Escalation

- If rules or hybrid gate fails:
  - stop release/merge of classifier-related changes
  - inspect confusion matrix + per-class deltas
  - revert only the offending classifier/rule change (avoid tactical phrase patches)
- If sparse-label weekly minimums are missed for 2 consecutive cycles:
  - increase `--target-signal-limit`
  - relax `--target-signal-max-confidence` by up to `+0.03`
  - expand lookback window to `--days 14`
  - record rationale in tracker entry
- If candidate pool is still confusion-heavy:
  - lower `--confusion-share-cap` (for example `0.40`)

