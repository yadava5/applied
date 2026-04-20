# Deployment & CI Matrix

This document describes the CI workflows that gate merges into
`integration/web-migration`, `develop`, and `main`, plus the deployment
surfaces each workflow protects.

The workflows live under [`.github/workflows/`](../.github/workflows/)
and are all path-filtered so unrelated changes don't trigger noisy
runs.

## CI workflows

| Workflow | File | Trigger (paths) | Runtime | Gates |
|---|---|---|---|---|
| **Backend CI** | `backend-ci.yml` | `backend/**`, `scripts/install.sh`, `scripts/start_backend.sh`, itself | ubuntu-latest, Python 3.11 | pytest + classifier rules-v3 gate + hybrid v3 deterministic gate + cloud-smoke |
| **Frontend CI** | `frontend-ci.yml` | `apps/web/**`, itself | ubuntu-latest, Node 20 + pnpm 10 | `pnpm install --frozen-lockfile` -> `typecheck` -> `lint` -> `build` |
| **E2E CI** | `e2e-ci.yml` | `apps/web/**`, `backend/**`, `api/**`, itself | ubuntu-latest, Node 20 + Python 3.11 | Boots uvicorn + Next.js dev, runs Playwright chromium smoke, uploads `playwright-report` + `test-results` (videos, traces) as artifacts |
| **macOS CI** | `macos-ci.yml` | `apps/macos/**`, `scripts/bundle.sh`, `scripts/generate_icons.sh`, itself | macos-latest, Xcode | `xcodebuild` Debug build of the SwiftUI app |
| **ML monitoring (weekly)** | `ml-monitoring-weekly.yml` | cron | ubuntu-latest | Rolling classifier drift check |

All workflows also respond to `workflow_dispatch` so maintainers can
re-run a green gate on demand (e.g. after a flake).

## Triggers

Every workflow runs on:

- `pull_request` against any branch, filtered by the paths above.
- `push` to `main` or `develop` (no PR fired there, so this catches
  direct-push emergencies).
- Manual `workflow_dispatch`.

Concurrency is scoped per ref (`group: <workflow>-${{ github.ref }}`
with `cancel-in-progress: true`) so a force-push mid-run cleans up the
stale job.

## Backend CI deep dive

`backend-ci.yml` runs two jobs in sequence:

1. **`test`** — the status quo. Installs Python 3.11 + pip cache,
   pulls CPU-only torch from the PyTorch index, runs `pytest tests -q`,
   then both classifier evaluation gates (rules v3 and hybrid v3
   deterministic) against frozen baselines in
   `backend/data/evaluation/`. Any macro-F1 regression beyond
   `--tolerance 0.001` fails the job.
2. **`cloud-smoke`** (new in issue #28 / C17) — `needs: test`. Imports
   `jobtracker.main_cloud:app` under `JOBTRACKER_DEPLOYMENT=cloud`,
   probes `/health` via `httpx.ASGITransport` (no network), and runs
   the focused `tests/test_main_cloud.py` suite. This catches two
   regression classes unit tests miss:

   - A new `backend/` module sneaks a `keyring` / `aiosqlite` / heavy
     ML import into the cloud app's import graph, blowing Vercel's
     250 MB function budget.
   - A route that only exists in desktop mode (e.g.
     `/ws/sync-status`) accidentally registers in cloud mode.

## Frontend CI deep dive

`frontend-ci.yml` runs a single `build` job:

- pnpm 10 via `pnpm/action-setup@v4`, Node 20 via `actions/setup-node@v4`
  with the built-in pnpm cache keyed off `apps/web/pnpm-lock.yaml`.
- Placeholder public env vars (`NEXT_PUBLIC_SUPABASE_URL` etc.) are
  injected via `env:` because `apps/web/lib/env.ts` validates them at
  module import time with zod; missing values would crash `next build`.
- Steps: `pnpm install --frozen-lockfile` ->
  `pnpm typecheck` (`tsc --noEmit`) ->
  `pnpm lint` (Next.js ESLint defaults) ->
  `pnpm build` (Next.js 16 Turbopack production build).

Any non-zero exit fails the job. `--frozen-lockfile` ensures
`pnpm-lock.yaml` drift (e.g. a hand-edited `package.json`) is caught.

## E2E CI deep dive

`e2e-ci.yml` is broader because it protects both sides of the web stack:

1. Installs backend + frontend dependencies (same caches as the other
   jobs).
2. `pnpm exec playwright install --with-deps chromium` fetches the
   browser and its Linux system libs.
3. Boots `uvicorn jobtracker.main:app` on `127.0.0.1:8000` in the
   background (with `JOBTRACKER_ENVIRONMENT=test` so the backend uses
   the in-memory SQLite fixture) and polls `/health` up to 60 s.
4. Boots `pnpm dev` on `127.0.0.1:3000` in the background and polls
   `/login` up to 90 s so Next.js has time to Turbopack-compile the
   first route.
5. Runs `pnpm exec playwright test --project=chromium`. The suite
   currently contains one smoke test (`tests/e2e/smoke.spec.ts`) that
   visits `/login` and asserts the form renders.
6. On both success and failure, uploads:
   - `apps/web/playwright-report` — the HTML report.
   - `apps/web/test-results` — per-test folders with `.webm` videos,
     screenshots, and trace zips.
   - `backend.log` + `frontend.log` — server stdout/stderr for
     post-mortem.

We do **not** set `continue-on-error` on the Playwright step: a red
test fails the workflow, which is the whole point of having the gate.

## Deployment surfaces

| Surface | Trigger | Gate |
|---|---|---|
| Vercel (Preview) — `apps/web/` + `api/index.py` | Every PR push (via the Vercel GitHub integration) | **frontend-ci** + **e2e-ci** green are required before merge |
| Vercel (Production) — `main` branch | Merge to `main` | All of the above + **backend-ci** (both `test` and `cloud-smoke` jobs) |
| macOS `.app` bundle | Manual release tag | **macos-ci** (Debug build on every PR), release script on tag |

`PLAYWRIGHT_BASE_URL` is wired as an env var on the E2E job so a
follow-up change can point the smoke suite at a real Vercel Preview
deployment instead of a locally-booted dev server. That wiring is
out-of-scope for C17 and tracked separately.

## Local dry-run

To reproduce each CI workflow locally:

```bash
# Frontend CI
cd apps/web
pnpm install --frozen-lockfile
pnpm typecheck && pnpm lint && pnpm build

# E2E CI
# (Terminal 1) Boot backend
cd backend
JOBTRACKER_ENVIRONMENT=test python -m uvicorn jobtracker.main:app --port 8000

# (Terminal 2) Boot frontend
cd apps/web
pnpm dev

# (Terminal 3) Run Playwright
cd apps/web
pnpm exec playwright install chromium
pnpm e2e

# Backend cloud-smoke
cd backend
JOBTRACKER_DEPLOYMENT=cloud JOBTRACKER_CORS_ALLOWED_HOSTS=jobtracker.app \
  pytest tests/test_main_cloud.py -q
```
