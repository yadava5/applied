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

If no trained SetFit model exists, classifier still runs with rules + embeddings.

## Runtime Controls

- `GET /classify/status`
- `GET /classify/lite-mode`
- `PUT /classify/lite-mode`
- `POST /classify/retrain`

Lite mode disables SetFit inference for lower-resource setups while keeping rules + embeddings active.

## Practical Guidance

For better accuracy:

1. Correct misclassified emails in the app regularly
2. Approve valid review-queue items instead of leaving them pending
3. Keep labels consistent (especially `pending_application` vs `applied`)
4. Trigger `POST /classify/retrain` after substantial new corrections if auto-train has not run yet
