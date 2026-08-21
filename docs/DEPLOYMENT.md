# Deployment & CI Matrix

This document describes the CI workflows that gate merges into
`integration/web-migration`, `develop`, and `main`, plus the deployment
surfaces each workflow protects.

The workflows live under [`.github/workflows/`](../.github/workflows/).
Most are path-filtered so unrelated changes don't trigger noisy runs;
**six carry no path filter at all** — `readme-facts.yml`, `codeql.yml`,
`gitleaks.yml`, `scorecard.yml`, `learning-gate.yml` and
`ml-monitoring-weekly.yml`. See Triggers below.

## CI workflows

| Workflow | File | Trigger (paths) | Runtime | Gates |
|---|---|---|---|---|
| **Backend CI** | `backend-ci.yml` | `backend/**`, `scripts/check_expand_only.py`, `scripts/schema_fingerprint.sql`, itself | ubuntu-latest, Python 3.11 | pytest + classifier rules-v3 gate + hybrid v3 deterministic gate + RLS/migration suites on real Postgres + expand-only + cloud-smoke |
| **Frontend CI** | `frontend-ci.yml` | `apps/web/**`, itself | ubuntu-latest, Node 22 + pnpm 10 | `pnpm install --frozen-lockfile` -> `typecheck` -> `lint` -> `test:unit` -> `build` |
| **E2E CI** | `e2e-ci.yml` | `apps/web/**`, `backend/**`, `api/**`, `scripts/generate_api_schema.sh`, itself | ubuntu-latest, Node 22 + Python 3.11 | API schema drift gate, then Playwright against a Next.js dev server **and** a real production build; uploads `playwright-report` + `test-results` (videos, traces) as artifacts |
| **ML monitoring (weekly)** | `ml-monitoring-weekly.yml` | cron | ubuntu-latest | Rolling classifier drift check |
| **README facts** | `readme-facts.yml` | **no path filter** | ubuntu-latest, stdlib only | Every number the README asserts still agrees with the code |

`macos-ci.yml` is gone. It built the SwiftUI app in `apps/macos/`, which was
de-scoped on 2026-08-12 and deleted.

All workflows also respond to `workflow_dispatch` so maintainers can
re-run a green gate on demand (e.g. after a flake).

## Triggers

Most workflows run on:

- `pull_request` against any branch, filtered by the paths above.
- `push` to `main` or `develop` (no PR fired there, so this catches
  direct-push emergencies).
- Manual `workflow_dispatch`.

**`ml-monitoring-weekly.yml` is the exception and has no `pull_request`
trigger at all** — it is `schedule` (`0 14 * * 1`) plus `workflow_dispatch`, so
a change to it is never exercised by the PR that makes it. `learning-gate.yml`
is `workflow_dispatch`-only, deliberately: it scores a checkpoint and a weekly
red build is a build people mute. `codeql.yml`, `gitleaks.yml` and
`scorecard.yml` do run on `pull_request` but carry **no path filter**, along
with `readme-facts.yml` — six workflows in total have none.

Concurrency is scoped per ref (`group: <workflow>-${{ github.ref }}`
with `cancel-in-progress: true`) so a force-push mid-run cleans up the
stale job.

## Backend CI deep dive

`backend-ci.yml` runs **four** jobs, and only three of them are in sequence:

1. **`test`** — the status quo. Installs Python 3.11 + pip cache,
   pulls CPU-only torch from the PyTorch index, runs `pytest tests -q`,
   then both classifier evaluation gates (rules v3 and hybrid v3
   deterministic) against frozen baselines in
   `backend/data/evaluation/`. Any macro-F1 regression beyond
   `--tolerance 0.001` fails the job.
2. **`rls-postgres`** — `needs: test`. Runs `tests/test_rls_postgres.py`
   against its own `postgres:16` service container, then parses the JUnit
   XML and **fails if the suite reports zero tests or any skip**. That guard
   is the point of the job: these tests once waited on a database URL no
   workflow set, and a skip is green. The migration suite
   (`tests/test_migrations_postgres.py`) rides along under the same guard.
3. **`expand-only`** — deliberately **not** `needs: test`, unlike the two
   jobs around it. It walks the Alembic chain one revision at a time against
   a `postgres:16` service and fails a revision that drops or narrows
   anything without a module-level `CONTRACT_STEP` saying why.
4. **`cloud-smoke`** (new in issue #28 / C17) — `needs: test`. Imports
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
2. `.github/actions/playwright-browsers` restores the chromium binary from
   the `~/.cache/ms-playwright` cache, keyed on the Playwright version
   `apps/web/pnpm-lock.yaml` resolves, and downloads it under a bounded retry
   only on a miss. It never runs `apt-get`: `--with-deps` is what stalled two
   jobs against `archive.ubuntu.com` on 2026-08-19, and the `ubuntu-latest`
   image already ships Chrome and Chromium, so chromium's system libs are
   present. If one ever is not, Playwright fails at browser launch naming the
   missing libs — loud, not silent.
3. Regenerates `apps/web/lib/api/schema.d.ts` from `jobtracker.main_cloud` and
   fails on any diff — the API schema drift gate. **No backend server is
   booted.** This step used to boot `uvicorn jobtracker.main:app` on
   `127.0.0.1:8000`; that was the desktop app, deleted with the unmounted
   desktop routers (issue #73). Every route the specs visit is public or
   redirects at the protected layout before any API call, which the sibling
   `playwright-production` job — same suite, no backend, green — demonstrates.
4. Boots `pnpm dev` on `127.0.0.1:3000` in the background and polls
   `/login` up to 90 s so Next.js has time to Turbopack-compile the
   first route.
5. Runs `pnpm exec playwright test --project=chromium`. The suite is
   **18 spec files** under `apps/web/tests/e2e/` — auth, beta, boot,
   connect, dashboard, demo, file-application, import, inbox-geometry,
   landing, navigation, production, sample-inbox, scan-correct,
   session-edge, settings, shell, smoke. `smoke.spec.ts` is one of them,
   not the whole suite; that sentence was true when the file was the only
   spec and has not been true for a long time.
6. On both success and failure, uploads:
   - `apps/web/playwright-report` — the HTML report.
   - `apps/web/test-results` — per-test folders with `.webm` videos,
     screenshots, and trace zips.
   - `frontend.log` — the dev server's stdout/stderr for post-mortem.
     There is no `backend.log`: step 3 boots no backend.

We do **not** set `continue-on-error` on the Playwright step: a red
test fails the workflow, which is the whole point of having the gate.

## Deployment surfaces

| Surface | Trigger | Gate |
|---|---|---|
| Vercel (Preview) — `apps/web/` + `api/index.py` | Every PR push (via the Vercel GitHub integration) | **frontend-ci** + **e2e-ci** green are required before merge |
| Vercel (Production) — `main` branch | Merge to `main` | All of the above + **backend-ci** (both `test` and `cloud-smoke` jobs) |

There is no third surface. The macOS `.app` bundle used to be one, cut by
`scripts/bundle.sh` and notarised by `scripts/notarize.sh`; the app, both
scripts and `macos-ci.yml` were deleted when the desktop client was de-scoped.

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
nobody. Two different causes, and the logs separate them: an empty
`gmail_sync_enrollment` (nobody has connected a mailbox on this
deployment) or an enrolled population whose grants have all been revoked
at Google. See [Who gets synced](#who-gets-synced) below.

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
- **Vercel** — 96 invocations/day of up to ~55 s ≈ ~1.5 GB-hours/day
  worst case, ~45 GB-hours/month at 1 GB. Cron jobs are "included in all
  plans" and they "invoke Vercel Functions … the same usage and pricing
  limits will apply", so this is ordinary function usage rather than a
  second meter. Whether ~45 GB-hours/month sits inside this account's
  included allowance has **not** been checked against the plan's own
  numbers — see [Cron usage and
  pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing) before
  budgeting on it. Pro allows 100 cron jobs per project at a
  once-per-minute minimum interval, so one job at `*/15` is well inside
  the schedule limits.
- **Supabase** — **two** connections for the whole enumeration, however
  many users are enrolled (one for the membership query, one held open
  across every cursor probe), plus a handful per user actually synced
  under NullPool. Well inside the free tier's pooler limits.

Realistically production runs one user on an incremental delta: two Gmail
calls and a couple of seconds per run.

### Who gets synced

**Nothing to configure.** Connecting a Gmail mailbox enrolls that user in
the schedule, in the same transaction as the token itself.

**The cron cannot read `user_credentials` to discover its users.** That
table has RLS ENABLEd and FORCEd with `USING (user_id = auth.uid())`
against a NOBYPASSRLS runtime role; a cron carries no JWT, so
`auth.uid()` is NULL and an identity-less `SELECT` matches no row. The
first implementation did exactly that and enumerated zero users in
production while returning a tidy `200`.

So the *membership fact* is published to a table that holds nothing else
— `gmail_sync_enrollment` (revision `e2b6f0a4d517`, issue #291): a user
id and when it was enrolled, no ciphertext and no address, with a
`SELECT` policy scoped to the runtime role rather than to `auth.uid()`.
The enumeration is one query with no identity bound. `save_gmail_
credentials` writes that row and `delete_gmail_credentials` removes it,
both in the same transaction as the credential, so the two cannot drift.

Each candidate's *cursor* still has to be read under that user's own
identity, because `sync_state` is FORCE-RLS too. Those probes share one
connection and re-bind the identity per transaction (bind, read,
`ROLLBACK`, bind the next) — the same `is_local => true` guarantee that
makes the shared PgBouncer safe for ordinary requests. Under NullPool a
*session* is a fresh ~216 ms connection, so a probe per user cost 65 s of
a 45 s budget at 300 enrolled users and the run could sync nobody.

An empty enrollment table means the cron syncs nobody, which is the same
fail-closed default the old allowlist had without the operator step it
needed. Enrollment cannot see **revocation** — a grant withdrawn at
Google sets `user_credentials.revoked_at` and leaves the enrollment row
standing — so the per-user probe checks that too, and a revoked user
drops out of the candidate list rather than failing every run forever.

> **`JOBTRACKER_CRON_SYNC_USER_IDS` is no longer read.** It was the
> hand-maintained allowlist this replaced, and its honest cost was list
> rot: a second user who connected Gmail got no background sync until an
> operator edited the env var and redeployed. A deployment that still
> sets the variable is simply ignored; it can be deleted from the Vercel
> project at any time.

**Verified against a real Postgres**, in `tests/test_rls_postgres.py`:
`test_cron_enumeration_uses_the_enrollment_table` (the enumeration
returns the enrolled users with no ambient identity, controlled against a
raw unscoped read of `user_credentials` that returns nothing),
`test_the_probe_loop_rebinds_identity_per_transaction` **and its negative
twin**, which removes the `ROLLBACK` and shows the next user's read runs
under the previous user's identity, and
`test_cron_syncs_only_the_enrolled_user_and_leaks_no_identity` (a run for
one user sees only that user's rows, leaves the other user's rows
byte-identical, and leaves no identity bound afterwards). SQLite has no
RLS, so the unit tests in `tests/test_cron_sync.py` cannot prove any of
that — which is why the Postgres tests exist.

## Local dry-run

To reproduce each CI workflow locally:

```bash
# Frontend CI
cd apps/web
pnpm install --frozen-lockfile
pnpm typecheck && pnpm lint && pnpm build

# E2E CI
# (Terminal 1) The API schema drift gate — no server involved
./scripts/generate_api_schema.sh
git diff --exit-code apps/web/lib/api/schema.d.ts

# (Terminal 2) Boot frontend. No backend: CI boots none either.
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
