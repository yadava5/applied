# ML Weekly Operations SOP

Updated: **March 4, 2026**
Owner: ML maintainer on weekly rotation

> **Scope, added 2026-08-15 — this SOP is a local operator procedure. None of it
> runs in the hosted deployment.**
>
> The "Updated" stamp above is an edit date, not a claim that this cycle is being
> run. Every command here is a shell script invoked by hand against a backend on
> the operator's own machine (`scripts/weekly_labeling_cycle.sh`,
> `scripts/monitoring_cycle.sh`); none appears in a GitHub Actions workflow and
> none is reachable from the deployed app, which is **rules-only** —
> `HybridClassifier.classify` short-circuits to the rules layer whenever
> `settings.deployment == "cloud"` (`backend/jobtracker/classifier/hybrid.py:326`).
>
> Where the steps below say "retrain": training is default-deny since #357. It
> refuses unless the corpus is wholly synthetic or its single owner is on an
> explicit allowlist that is empty unless configured, and nothing in the hosted
> deployment configures it
> (`backend/jobtracker/classifier/setfit_model.py:38-75`). Applied reads mail
> under Gmail's restricted `gmail.readonly` scope, and Google's Workspace API
> user-data policy permits training only a model personalized to one end user
> with no co-mingling; production therefore trains on nobody, by design.
>
> A user correction collected by this cycle is written to `training_data` and
> flagged reviewed. It does not change any future classification in the hosted
> app, because no deployed path reads that table back.

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

### Steps 3 and 4: apply corrections, then retrain

> **The `/classify/*` HTTP surface these steps used to call does not exist in
> this tree.** `PUT /classify/email/<id>/correct` and `POST /classify/retrain`
> belonged to the desktop FastAPI app (`backend/jobtracker/main.py` and the
> routers under `backend/jobtracker/api/`), de-scoped and deleted in August
> 2026 — issue #73. No module declares them; the deployed app registers four
> routers, applications, Gmail, account and cron
> (`backend/jobtracker/main_cloud.py:667-684`). The only classification route
> that exists is `POST /applications/review/{message_id}/classify`
> (`backend/jobtracker/cloud/applications.py:3487`), and it records a decision
> — it does not train. [`ML_STRATEGY.md`](ML_STRATEGY.md) states the same thing
> at its head; this page contradicted it until 2026-08-21.

**Apply corrections** through the review surface in the running app, or by
writing the corrected rows into `training_data` directly against a local
database. There is no HTTP correction endpoint to curl.

**Retrain** with the shell wrapper, which is now the only caller of the
training path that `POST /classify/retrain` used to reach:

```bash
./scripts/ml_cycle.sh --retrain
```

It resolves `backend/.venv311/bin/python` when that exists, falling back to
`backend/.venv` and then `python3`.

Training is **default-deny** — it refuses unless the corpus is wholly synthetic
or its single owner is on an explicit allowlist that is empty unless configured
(`backend/jobtracker/classifier/setfit_model.py:38-75`). An unconfigured
machine therefore trains on nobody, and that is the intended state, not a
failure of this step. Wait for retrain completion before gate verification.

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

