# Architecture

> **This document described the desktop architecture until the SwiftUI app was
> de-scoped (2026-08-12) and deleted.** Applied is web-only now: a Next.js app
> on Vercel over a FastAPI serverless function over Supabase Postgres. The
> deployment-level view — environments, secrets, what runs where — is in
> [`WEB_ARCHITECTURE.md`](WEB_ARCHITECTURE.md); this file is the code-level map.

## High-Level Design

One deployed system, three pieces:

1. **Next.js 16 web app** (`apps/web/`) — the only user interface. Server
   components and route handlers hold the Supabase JWT and `BACKEND_API_URL`;
   neither ever reaches the browser.
2. **FastAPI serverless function** (`api/index.py` → `backend/jobtracker/`).
   Vercel detects the ASGI callable at `api/index.py`, which puts `backend/` on
   `sys.path`, forces `JOBTRACKER_DEPLOYMENT=cloud`, and imports
   `jobtracker.main_cloud`.
3. **Supabase** — Postgres for data (with RLS enforced) and Auth for identity.

Communication is HTTPS throughout. There is no local process, no WebSocket and
no SQLite in the deployed path.

## Backend Components

The deployed app mounts **29 routes**. Four routers are *registered*
(`applications`, `gmail_oauth`, `account`, `cron` — the `include_router`
calls in `main_cloud.py`),
but **five modules define routes**, because `main_cloud` owns five itself.

**Auth, stated exactly, because the blanket version of this sentence was
false.** Two of the four routers carry a router-level `require_user()`: the
module-level `router` in `applications.py` and in `account.py`. The
module-level `router` in `gmail_oauth.py` and in `cron.py` is created with no
`dependencies=`, deliberately — the callback arrives from Google carrying no
JWT and is bound by its signed `state`, and Vercel Cron carries none at all
and is gated on a shared secret. Each mount in `main_cloud.py` says so in its
own comment. Which routes that leaves public is enforced rather than
described: the `PUBLIC` allowlist in
`backend/tests/test_cloud_routes_carry_auth.py` names every one with its
reason, and `test_every_public_route_on_the_allowlist_still_exists` reds on a
stale entry. Of the 29 routes, **23 require a Supabase
JWT** and **6 do not**.

A route here is **one entry in the walked route table**, which is the unit
`API_SPEC.md` counts in too: `/cron/sync` declares both its verbs on one
handler, so it is one route object and counts once. Counting `(method, path)`
pairs or distinct paths instead gives different totals, so a figure quoted
here cannot be checked by counting either of those.

The visible consequence is that the `PUBLIC` allowlist in
`backend/tests/test_cloud_routes_carry_auth.py` holds **7 entries** while the
count above says six, because it is keyed on `(method, path)` and
`/cron/sync` appears under both verbs. A reader who checks the public count
against the allowlist and finds one more has counted the other noun, not
found an error.

The bold figures above and the **7** here are registered facts
(`scripts/readme_facts.py`), each computed by an AST census of the route
decorators, so they red when a route is added rather than going quietly
stale. The census agrees with the live route table on this tree and counts in
the same unit; it is a syntactic proxy for that walk rather than the walk
itself, and `backend/tests/test_cloud_routes_carry_auth.py` is what ties the
two together:

| Public route | What stands in for the JWT |
| --- | --- |
| `GET /` | nothing — it returns API metadata only |
| `GET /health` | nothing — no DB hit, no credential probe, so uptime monitors can poll it |
| `GET /health/schema` | nothing — reports `{expected, applied, ok}` |
| `GET /health/gmail-capacity` | nothing — a count of enrolled mailboxes against the beta ceiling |
| `GET /auth/gmail/callback` | the HS256-signed `state` parameter, verified by `_verify_state()` before any identity is bound |
| `GET\|POST /cron/sync` | `JOBTRACKER_VERCEL_CRON_SECRET`, compared with `hmac.compare_digest` in `_authorize()` and **failing closed** when unconfigured |

The other six `gmail_oauth` routes declare `Depends(current_user)` per
endpoint rather than at the router. So a handler added to `gmail_oauth.py` or
`cron.py` is **not** protected by its mount and must declare its own
dependency — the mount is not the guarantee there that it is for
`applications.py` and `account.py`. Every authenticated handler additionally
filters on `user_id`, and RLS enforces it a third time.

- `jobtracker/main_cloud.py`
  - app lifecycle, CORS, the cloud exception handlers
  - `GET /`, `GET /auth/me`, `GET /health`, `GET /health/schema`,
    `GET /health/gmail-capacity`
- `jobtracker/cloud/applications.py`
  - application CRUD, listing, summary, statuses vocabulary
  - the review queue and per-message classification
  - dismiss / restore, deadline, role, split
- `jobtracker/cloud/gmail_oauth.py`
  - Gmail OAuth authorize / callback / status / disconnect
  - inbox listing, `POST /gmail/sync`, `POST /gmail/pipeline`
- `jobtracker/cloud/cron.py`
  - `/cron/sync`, the scheduled ingestion entrypoint
- `jobtracker/cloud/account.py`
  - `DELETE /account`, which cascades across every table
- `jobtracker/cloud/pipeline.py`
  - not a router: the classification → status reconciler the others call

`jobtracker/api/` and `jobtracker/services/` are **gone** (issue #73). They were
a second, unmounted set of routers with no user scoping at all — every read was
`select(Application).where(Application.id == id)` against a multi-tenant table —
kept alive only for a desktop build that no longer exists.
`backend/tests/test_the_deployed_app_is_the_cloud_app.py` holds an allowlist
over every mounted handler's defining module so a replacement cannot arrive
unnoticed.

## Classifier Architecture

Hybrid pipeline in `backend/jobtracker/classifier`:

1. Rules layer (regex/domain heuristics)
2. Embedding similarity layer (`intfloat/e5-small-v2`)
3. SetFit layer (enabled once enough training data exists)

**The cloud runs the rules layer only.** Layers 2 and 3 need torch and a model
on disk, which do not fit a serverless function under a 250 MB ceiling. A cloud
rules miss collapses to `{category: "other", confidence: 0.0, method: "rules"}`
and does not escalate.

Current categories:

- `applied`
- `pending_application`
- `interview`
- `rejection`
- `offer`
- `assessment`
- `follow_up`
- `needs_review`
- `other`

`needs_review` is the typed null of that vocabulary, not a verdict. The auto-file
gate (`0.85`) and the review floor (`0.70`) are held in lock-step across their
Python copies by `backend/tests/test_confidence_gate_lockstep.py`, and across
the language boundary into TypeScript by `scripts/readme_facts.py`.

## Data Model Highlights

Core DB entities (`backend/jobtracker/database/models.py`):

- `Application`
- `Email`
- `TrainingData`
- `EmailEmbedding`
- `SyncState`
- `Contact`
- `Interview`

Notable behavior:

- every one of these tables is `user_id`-scoped and carries FORCE'd RLS policies
- an application is soft-dismissed (`dismissed_at` / `dismissed_reason`) rather
  than destroyed; the cloud read paths exclude dismissed rows
- application identity is employer + req-id-or-role, so one company can hold
  many applications

## Repository Boundaries

```text
api/            the Vercel Python entrypoint (ASGI callable, ~30 lines)
backend/        FastAPI app, DB, migrations, ML, tests
apps/web/       the Next.js web app — the only UI
apps/mobile/    a README placeholder, reserved
ml/             training, evaluation and the demo ports
booklet/        the system-card booklet
scripts/        gates and local tooling
```

CI workflows:

- `.github/workflows/backend-ci.yml` — pytest, the classifier gates, RLS and
  migration suites against a real Postgres, the expand-only gate, cloud smoke
- `.github/workflows/frontend-ci.yml`
- `.github/workflows/e2e-ci.yml` — Playwright against both a dev server and a
  real production build
- `.github/workflows/readme-facts.yml` — no path filter, because a claim in
  the README can be invalidated from anywhere. It is not the only one:
  `codeql.yml`, `gitleaks.yml`, `scorecard.yml`, `learning-gate.yml` and
  `ml-monitoring-weekly.yml` also carry none, the last two because they are
  dispatch- and schedule-only and have no pull-request trigger to filter.

`macos-ci.yml` was deleted with the app it built.
