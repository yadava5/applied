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
| **Frontend CI** | `frontend-ci.yml` | `apps/web/**`, itself | ubuntu-latest, Node 22 + pnpm 10 | `pnpm install --frozen-lockfile` -> `typecheck` -> `lint` -> `test:unit` -> `build` |
| **E2E CI** | `e2e-ci.yml` | `apps/web/**`, `backend/**`, `api/**`, itself | ubuntu-latest, Node 22 + Python 3.11 | Boots uvicorn + Next.js dev, runs Playwright chromium smoke, uploads `playwright-report` + `test-results` (videos, traces) as artifacts |
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

- pnpm 10 via `pnpm/action-setup@v6`, Node 22 via `actions/setup-node@v7`
  with the built-in pnpm cache keyed off `apps/web/pnpm-lock.yaml`.
- **The Node major is load-bearing.** `pnpm test:unit` runs `.mjs` test
  files that import `.ts` modules directly, on the runtime's built-in
  type stripping — Node **22.6 or newer** — plus the built-in glob
  (21+). This job used to pin Node 20, where those imports raise
  `ERR_UNKNOWN_FILE_EXTENSION`: the tests existed and no job ran them.
  So "restoring consistency" by pinning back to 20 does not turn the
  job red, it silently deletes a suite. Change the pin only together
  with `test:unit`.
- Placeholder public env vars (`NEXT_PUBLIC_SUPABASE_URL` etc.) are
  injected via `env:` because `apps/web/lib/env.ts` validates them at
  module import time with zod; missing values would crash `next build`.
- Steps: `pnpm install --frozen-lockfile` ->
  `pnpm typecheck` (`tsc --noEmit`) ->
  `pnpm lint` (Next.js ESLint defaults, `--max-warnings 0`) ->
  `pnpm test:unit` (`node --test`, the suite the Node pin exists for) ->
  `pnpm build` (Next.js 16 Turbopack production build).
- `--max-warnings 0` lives on the `lint` script in
  `apps/web/package.json`, not on the workflow step, so a local
  `pnpm lint` returns the verdict CI returns. It promotes every
  warn-level rule `eslint-config-next` ships, not only the six
  `jsx-a11y/*`; before #179 the step ran bare `eslint`, which exits 0
  on warnings, and the whole accessibility ruleset was decorative.

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

## Scheduled sync (Vercel Cron)

`GET|POST /cron/sync` (`backend/jobtracker/cloud/cron.py`, issue #23 / C7)
syncs a bounded batch of users' mailboxes on a schedule. It is the only
route on the cloud app without `require_user()`, because the platform's
scheduler carries no JWT.

**What it is for.** *Not* "the board never refreshes" — the web shell
already runs a staleness auto-sync when a tab opens
(`apps/web/components/dashboard/SyncBar.tsx`). What does not happen
without a cron is anything **while the user is away**: the change ledger
can only report changes the open tab itself just fetched, and a
notification signal has nothing to fire on.

### Schedule

```json
"crons": [{ "path": "/cron/sync", "schedule": "*/15 * * * *" }]
```

Declared in the **repo-root** `vercel.json`, which is the config for the
`jobtracker-api` project (Root Directory = repo root). `apps/web` has its
own `vercel.json`, so this does not install a cron on the web project.

`*/15 * * * *` needs a paid plan, and this account is on **Pro**, where
"cron jobs will be invoked within the minute specified".

Issue #23 offers `0 * * * *` as the "Hobby hourly" fallback. That is not
available: on Hobby, "cron jobs can only run once per day. Expressions
that run more frequently **will fail deployment**", and Vercel may fire
the job anywhere inside the specified hour. A Hobby fallback would have
to be once-daily (e.g. `0 6 * * *`), which is a different product — a
daily digest, not a background refresh. Noted so nobody "restores" the
hourly expression believing it is a safe downgrade.

### The secret — set this before the cron can work

| Env var | Who reads it |
|---|---|
| `JOBTRACKER_VERCEL_CRON_SECRET` | The app (`settings.vercel_cron_secret`) |
| `CRON_SECRET` | **Vercel**, to build the `Authorization: Bearer …` header; also read by the app as a fallback |

Setting **`CRON_SECRET` alone is sufficient and is the simplest
configuration**: Vercel sends it, and the handler falls back to it. Set
it in the Vercel dashboard (Project → Settings → Environment Variables)
for Production, then **redeploy** — Vercel injects env at deploy time, so
a variable added without a following deployment does not reach the
running function.

A random string of at least 16 characters. The value never appears in
this repo, in a log line, or in a response body.

**Until it is set, every invocation is refused with 403.** That is the
deliberate fail-closed behaviour, and it is the failure mode to watch
for: the Cron Jobs page will show the job firing on schedule and the
runtime log will show a tidy 403, which looks far more like "configured"
than it is.

### Verifying it

```bash
# Refused (no secret) — this is the gate working.
curl -i -X POST https://<api-host>/cron/sync

# Authorised. Both carriers are accepted; Vercel itself sends the Bearer.
curl -s -X POST -H "x-vercel-cron-secret: $CRON_SECRET" https://<api-host>/cron/sync
curl -s -H "Authorization: Bearer $CRON_SECRET" https://<api-host>/cron/sync
# -> {"users_synced":N,"errors":[],"candidates":N,"stopped_by":"complete"}
```

`users_synced: 0` with `candidates: 0` means the enumeration found
nobody. See the **known limitation** below before concluding that nobody
has connected a mailbox.

### What bounds a run

| Bound | Value | Effect |
|---|---|---|
| `settings.sync_batch_size` | 100 | Ceiling on users enumerated per invocation |
| `_CRON_PER_USER_TIMEOUT_SECONDS` | 10 s | One slow mailbox cannot hold the batch |
| `_CRON_RUN_BUDGET_SECONDS` | 45 s | Checked *before* each user starts, under the function's `maxDuration: 60` |

The **run budget is what actually binds**: at 10 s per user it stops the
batch after ~4–5 users, long before a cap of 100. Candidates are ordered
never-synced-first, then oldest-sync-first, so users a run could not
reach sort to the front of the next one rather than starving.

**A first sync may need several cron iterations.** A user with no history
cursor gets a full scan of up to 750 messages against a 30 s scan budget,
which can exceed the 10 s per-user timeout; that run is cancelled, writes
no cursor, and reports `"<user_id>: TimeoutError"` in `errors`. The path
that reliably completes a first backfill is the user's own "Sync now"
button, which gets the whole 60 s function budget. Once a cursor exists,
each cron run is an incremental `users.history.list` delta and finishes
in well under the timeout.

Runs are idempotent — the merge is the additive upsert — which is what
Vercel's cron delivery contract requires, since it "can also occasionally
invoke the same scheduled run more than once".

### Worst-case cost of one run

Five users start inside the 45 s budget; each hits the full-scan path and
reads the 750-message target before its 10 s timeout:

- **Gmail quota** — 750 messages × ~5 units per metadata get ≈ 3,750
  units per user, plus `messages.list` and `getProfile`; ≈ **19k units
  per run**, ≈ 1.8M/day at 96 runs. Metadata batches are paced by
  `gmail_batch_pause_seconds` to stay under the ~250 units/sec per-user
  quota.
- **Vercel** — 96 invocations/day of up to ~55 s. At 1 GB that is ~1.5
  GB-hours/day worst case, ~45 GB-hours/month, inside Pro's allowance.
  Cron invocations themselves are not separately metered.
- **Supabase** — one connection for the enumeration plus a handful per
  user under NullPool. Well inside the free tier's pooler limits at this
  user count.

Realistically production runs one user on an incremental delta: two Gmail
calls and a couple of seconds per run.

### Known limitation — the enumeration returns nobody on Postgres

`list_syncable_user_ids` reads `user_credentials`, which has RLS ENABLEd
and FORCEd with `USING (user_id = auth.uid())` against a NOBYPASSRLS
runtime role. A cron has no JWT, so `auth.uid()` is NULL and the policy
matches no row. **Verified against a real Postgres**:
`tests/test_rls_postgres.py::test_cron_enumeration_sees_no_users_without_identity`
asserts the empty result, with a positive control proving the same query
returns the user when an identity *is* bound.

SQLite has no RLS, so the unit tests in `tests/test_cron_sync.py` are
green regardless — which is why the Postgres test exists. Closing the gap
is a change to a security boundary (a GUC-gated SELECT policy, or a
privileged non-pooler read) and is deliberately not made here.

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
