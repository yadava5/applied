# Phase 8 End-to-End Fresh-Install Test Report

## Date
- February 19-20, 2026

## Environment
- macOS (local development machine)
- Backend: `FastAPI` on `127.0.0.1:8000`
- DB path: `~/Library/Application Support/JobTracker/jobtracker.db`

## Scope
Validated end-to-end flow:
1. install
2. connect account
3. sync
4. classify
5. track

## Test Steps and Results

1. Install backend dependencies and initialize DB
- Command: `./scripts/install.sh` (dev deps prompt answered `N`)
- Result: PASS
- Notes: venv and model setup complete; DB initialization and import verification passed.

2. Start backend service
- Command: `uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000`
- Result: PASS

3. Verify account connection state
- Command: `GET /auth/status`
- Result: PASS
- Response snapshot:
  - Gmail: disconnected
  - iCloud: connected (`aesh_1055@icloud.com`)

4. Trigger sync
- Command: `POST /sync` with `{"accounts":["icloud"],"full_sync":false}`
- Result: PASS
- Response snapshot:
  - `success: true`
  - `emails_fetched: 1`
  - `emails_saved: 1`
  - `duration_seconds: 1.619882`

5. Verify classification/review queue
- Command: `GET /classify/needs-review?limit=1&offset=0`
- Result: PASS
- Response snapshot:
  - `total_count: 8`
  - Returns classified review item payload including confidence and normalized category.

6. Verify tracking/application state
- Command: `GET /applications`
- Result: PASS
- Response snapshot:
  - `total: 89`
  - Application list includes status, position, and linked email counts.

7. Validate overall backend health after sync
- Command: `GET /health`
- Result: PASS
- Response snapshot:
  - `status: ok`
  - `db_connected: true`
  - `emails: 517`
  - `applications: 89`
  - `classifier_status.active_layers: ["rules", "embeddings"]`

## Outcome
Phase 8 end-to-end flow is working for daily local usage:
- install -> connect -> sync -> classify -> track is operational.

## Notes
- This run used existing iCloud credentials in Keychain for the account connection step.
- SetFit is currently not trained in this local dataset (`setfit_trained: false`), which is expected until sufficient corrected examples accumulate.
