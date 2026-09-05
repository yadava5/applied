# Web Architecture

> **Status, re-read 2026-08-21.** This file began as a stub for issue #14 (C1)
> and was filled in through C2–C18. The C-series has shipped: the sections
> describing deployment modes, auth, the classifier, credentials, sync and the
> cloud entrypoints describe **shipped** state and are meant to be read as
> claims about the code.
>
> Two sections are **historical migration planning and are not descriptions of
> the system**: "Intended request flow (cloud, once C3–C7 land)" — the flow it
> draws is live; the heading's tense is not — and the "Issue map", which is a
> record of which issue delivered what rather than a list of outstanding work.
> Nothing else on this page is pre-excused: a claim below that turns out to be
> false is a defect, not an intention.

## Deployment modes

Applied ships in **one** mode. `JOBTRACKER_DEPLOYMENT` still selects
between two values, and `desktop` is still the default the settings
object falls back to — but there is no longer a desktop application to
build, so `cloud` is the only mode with a UI, an app builder or a
deployment:

| Mode | Host | UI | DB | Auth | Secrets | Classifier |
|---|---|---|---|---|---|---|
| `cloud` | Vercel serverless | Next.js on Vercel (`apps/web/`) | Supabase Postgres | Supabase Auth (JWT) | Fernet-encrypted Postgres rows | rules only |
| `desktop` (default value, **no app**) | — | deleted 2026-08-12 | SQLite paths still in `database/connection.py` | — | `keyring` still importable | rules + embeddings + SetFit |

The setting is not vestigial: `api/index.py` forces it to `cloud`
before importing the app precisely because a stray `desktop` value
would still select SQLite over Postgres and the Keychain over the
encrypted-row store. That forcing line is pinned by
`backend/tests/test_the_deployed_app_is_the_cloud_app.py`.

What used to be the divergence:
- `backend/jobtracker/main.py` (desktop app builder) — **deleted**,
  along with the unmounted, unscoped routers under
  `backend/jobtracker/api/` and `backend/jobtracker/services/`
  (issue #73). `backend/jobtracker/main_cloud.py` is the only app
  builder.
- `backend/jobtracker/credentials.py` (to be split in C4).
- `backend/jobtracker/database/connection.py` (to be dialect-gated in C2).
- `backend/jobtracker/classifier/hybrid.py` — C6 now short-circuits to
  rules-only when `settings.deployment == "cloud"` and lazy-imports
  `embeddings` / `setfit_model` inside method bodies so neither
  `torch`, `sentence-transformers`, nor `setfit` enters the cloud
  import graph. The `jobtracker.classifier` package itself uses PEP
  562 `__getattr__` so heavy re-exports resolve only on demand.

## Auth (cloud)

- **Identity provider.** Supabase Auth. Users sign up / sign in via
  `supabase-js` in the Next.js frontend (C9); the browser exchanges
  email+password for a JWT which is then attached as
  `Authorization: Bearer <JWT>` on every request to the cloud
  FastAPI backend.
- **Token format.** A Supabase JWT, signed either ES256 with the
  project's asymmetric signing key (the default for projects created
  since 2025, and what this project uses) or HS256 with the shared
  secret (`JOBTRACKER_SUPABASE_JWT_SECRET` on Vercel). Supabase default
  claims: `sub` (UUID of `auth.users.id`), `aud` = `"authenticated"`,
  plus `exp` / `iat` / `role`.
- **Verification.** `backend/jobtracker/auth/supabase_jwt.py` decodes
  the token with `pyjwt[crypto]` against a two-algorithm whitelist. It
  dispatches on the unverified header `alg`: `ES256` verifies against
  the key fetched from `JOBTRACKER_SUPABASE_JWKS_URL`, anything else
  against the shared secret with `algorithms=["HS256"]`. The header only
  selects a fully-verified path and never relaxes verification, each
  branch carries its own key material, and the list handed to
  `jwt.decode` holds exactly one algorithm. So `alg: none` and
  `alg: RS256` are still rejected, and an ES256 token is refused
  outright when no JWKS URL is configured rather than falling back to
  the secret. Verification also applies `audience="authenticated"` and
  `require=["exp", "sub", "aud"]`.
  The `sub` claim is parsed as `uuid.UUID` and returned by the
  `current_user` dependency.
- **Router contract, and its two exceptions.** Every router lives
  under `backend/jobtracker/cloud/`; `backend/jobtracker/api/` and
  `backend/jobtracker/services/` were deleted with the desktop app
  (issue #73), so there is no second, unauthenticated package tree
  any more. Two of the four routers declare
  `dependencies=[require_user()]` at the router level —
  `applications.py:266` and `account.py:61`. `gmail_oauth.py:122`
  and `cron.py:159` declare none, deliberately: the OAuth callback
  arrives from Google carrying no JWT and is bound by its signed
  `state` instead, and Vercel Cron carries no JWT at all and is
  gated on a shared secret (`main_cloud.py:679-680`). In those two
  modules auth is declared per endpoint, so the mount is not the
  guarantee — see [`API_SPEC.md`](API_SPEC.md) for the six routes
  that carry no user token and what stands in for one.
- **Per-row scoping.** Every entity table carries a
  `user_id UUID NOT NULL` column (Alembic rev `6e64c46d32fd`).
  Handlers read the authenticated UUID from
  `Depends(current_user)` and use it both for reads
  (`WHERE user_id = :uid`) and writes (`Application(user_id=uid,
  ...)`). Clients cannot spoof `user_id` because the cloud Pydantic
  request models do not expose it.
- **Defence-in-depth (RLS).** Alembic rev `a8d4ec5fba26` enables
  PostgreSQL Row-Level Security on every tenant-scoped table with
  per-operation policies of the form
  `USING (user_id = (SELECT auth.uid()))` (and `WITH CHECK` for
  writes). The migration is a no-op on SQLite so `alembic upgrade
  head` runs cleanly in CI; on Supabase it guarantees the DB rejects
  any query that forgets the application-level filter.
  The sub-select is a performance requirement, not style: bare
  `auth.uid()` is `STABLE` and so re-evaluated **once per row**, while
  the sub-select is hoisted into an `InitPlan` evaluated **once per
  query** (Supabase's `auth_rls_initplan` lint). Rev
  `c6_rls_initplan_hoist` applied that to all 32 policies. On a
  *synthetic* 200k-row sequential scan in a throwaway `postgres:16`,
  that cut `auth.uid()` invocations from 200,001 to 1 and the query
  from 126 ms to 10 ms. Treat the millisecond figures as an upper
  bound on the benefit, not a production measurement — Applied's real
  tables are far smaller, and the win scales with rows scanned. What
  does hold at any size is the invocation count: one per query instead
  of one per row. The comparison is unchanged either way, so the
  isolation guarantee is identical.
- **Desktop.** No longer applicable. The desktop app builder never
  imported the auth module and its rows were owned by a fixed sentinel
  UUID (`00000000-0000-0000-0000-000000000000`). That constant,
  `jobtracker.database.models.LOCAL_USER_ID`, still exists and is still
  the default for a row written without a user — which is why the RLS
  policies, not the application code, are the thing that actually
  enforces isolation.

## Classifier (cloud)

- **Layers available.** Rules only. Embeddings (Layer 2) and SetFit
  (Layer 3) are disabled; `settings.deployment == "cloud"` implies
  `lite_mode = True` regardless of the explicit `JOBTRACKER_LITE_MODE`
  value.
- **Response shape.** `HybridClassifier.classify()` returns
  `{category, confidence, method: "rules", …}`. Rules hits keep the
  rules layer's category + confidence; rules misses (no category scored
  above zero) collapse to `{category: "other", confidence: 0.0,
  method: "rules"}` — the cloud path never escalates to semantic
  layers.
- **Why rules-only.** The combined torch + sentence-transformers +
  setfit wheel set exceeds Vercel's 250 MB unzipped function budget,
  and even on Pro the cold-start cost blows the 60 s wall clock.
- **Corrections.** User-corrected labels persist to `TrainingData`
  and stop there. There is no macOS client to sync back to — it was
  de-scoped on 2026-08-12 and deleted — and no deployed path reads
  that table back, so a correction records a human decision and does
  not change any later hosted classification. The full three-layer
  hybrid runs only on an operator's own machine; see
  [`ML_STRATEGY.md`](ML_STRATEGY.md).
- **Guard test.** `backend/tests/test_main_cloud.py::
  test_cloud_classifier_is_rules_only_and_skips_heavy_ml_imports`
  subprocess-invokes `get_classifier()` under
  `JOBTRACKER_DEPLOYMENT=cloud` and asserts neither `torch`,
  `sentence_transformers`, `setfit`, nor `transformers` entered
  `sys.modules`.

## Frontend scaffold (C9)

Greenfield `apps/web/` lives as a standalone pnpm project (no workspace
tooling yet). Stack:

- **Next.js 16** (App Router, Turbopack default) + **React 19.2**.
- **TypeScript** strict mode.
- **Tailwind CSS 4**.
- **Supabase Auth** via `@supabase/ssr` — SSR-safe cookie handling with
  `getAll` / `setAll` methods (the only supported shape going forward).
- **`openapi-fetch`** over types generated by `openapi-typescript` — the
  typed API client that landed in C10. TanStack Query was considered and is
  **not** installed; it appears in neither `apps/web/package.json` nor
  `apps/web/pnpm-lock.yaml`.
- **zod** for runtime env validation (`lib/env.ts`, `lib/env.server.ts`).
- **shadcn/ui**-compatible scaffold: `components.json` in place,
  `components/ui/button.tsx` committed; further primitives are added via
  `pnpm dlx shadcn@latest add ...`.

File layout, read from the tree on 2026-08-21. The C9 scaffold this section
once described (two component directories, a placeholder dashboard) is long
gone; what is below is the shipped app:

```
apps/web/
├── app/
│   ├── (auth)/                 # login, signup, callback, forgot/reset-password
│   ├── (app)/
│   │   ├── (protected)/        # dashboard, inbox, settings + error boundary
│   │   ├── import/             # the public import route
│   │   ├── privacy/
│   │   └── layout.tsx          # auth-gated shell
│   ├── api/                    # route handlers: account, applications, auth, gmail
│   ├── demo/                   # the signed-out product demo
│   ├── landing-a/ landing-c/   # landing variants
│   ├── fonts/  layout.tsx  page.tsx  not-found.tsx  globals.css
├── components/                 # 16 directories, not 2: applications, auth, beta,
│                               # boot, brand, dashboard, demo, gmail, import,
│                               # landing, mail, marketing, settings, shell, ui, viz
├── lib/
│   ├── env.ts / env.server.ts  # zod-validated public + server env
│   ├── api/{client,server,schema.d.ts,serverTiming}.ts
│   ├── supabase/{client,server,admin,auth,middleware,protectedRoutes,…}.ts
│   └── account, applications, boot, dashboard, demo, gmail, import, mail,
│       security, settings, shell, ambient, theme.ts, utils.ts
├── tests/{e2e,unit}/           # 21 Playwright specs + the node --test unit suite
├── scripts/                    # csp-gate.mjs, no-session-census.mjs, footage/
├── proxy.ts                    # session refresh + auth gate
└── components.json             # shadcn config
```

Auth flow:

1. Unauthenticated visitor hits any `/(app)/...` URL (e.g. `/dashboard`).
2. `proxy.ts` calls `updateSession(request)` which constructs a Supabase
   server client, invokes `auth.getUser()` to refresh near-expiry
   tokens, and redirects missing sessions to `/login?redirect=...`.
3. The `/login` Client Component calls `supabase.auth.signInWithPassword`
   in the browser. Supabase writes session cookies via `document.cookie`.
4. `router.refresh()` + `router.replace(redirect)` re-runs the proxy with
   the new cookies, which now pass the auth gate.
5. `app/(app)/layout.tsx` re-checks `auth.getUser()` server-side
   (defence-in-depth) and hydrates the `AppShell` with the user's email.
6. Sign-out from `TopBar` calls `supabase.auth.signOut()` and redirects
   back to `/login`.

> **Next.js 16 note.** The `middleware.ts` convention was renamed to
> `proxy.ts` in v16. The behaviour is identical; only the file/function
> name changed.

The real backend API client **shipped** in C10 and is what the app
uses: `lib/api/client.ts` wraps `openapi-fetch` over the generated
`lib/api/schema.d.ts`, and `lib/api/server.ts` binds `BACKEND_API_URL`
and reads the Supabase JWT from cookies for Server Components. The
bindings are regenerated from `jobtracker.main_cloud` by
`scripts/generate_api_schema.sh`, and `e2e-ci.yml` fails the build on
any diff — so a stale contract is a red build, not a silent drift.

## Credentials (cloud)

- **Package layout.** `backend/jobtracker/credentials/` is the package
  introduced by issue #21 (C4). It contains `types.py` (shared
  `GmailCredentials` / `ICloudCredentials` dataclasses), `desktop.py`
  (macOS Keychain via `keyring`, sync API), and `cloud.py`
  (Supabase Postgres + Fernet, async API taking `user_id`).
- **Backward compatibility.** `__init__.py` re-exports every
  symbol from `desktop.py` at the top level, so historical
  desktop imports like
  `from jobtracker.credentials import save_gmail_credentials` compile
  unchanged. Cloud routers import from
  `jobtracker.credentials.cloud` explicitly.
- **Storage table.** `user_credentials` (Alembic rev `22cefa34bc94`).
  Composite PK `(user_id, kind)`; `kind ∈ {'gmail_oauth',
  'icloud_mail'}`. Ciphertext is an opaque Fernet token; `nonce`
  reserved for a future AEAD upgrade (Fernet embeds its own IV).
- **Encryption.** `cryptography.fernet.Fernet` keyed by
  `settings.secret_encryption_key` (urlsafe base64, 32 bytes).
  Generate with `python -c "from cryptography.fernet import Fernet;
  print(Fernet.generate_key().decode())"`. Active key is named
  `v1`; the `key_id` column supports rotation (multi-key decrypt
  scaffolded but not wired for v1).
- **Defence-in-depth.** Alembic rev `c4user_creds_rls` enables
  Postgres Row-Level Security on `user_credentials` with per-op
  policies `USING (user_id = (SELECT auth.uid()))` (named
  `user_credentials_owner_*`, hoisted by `c6_rls_initplan_hoist`) and
  the FK
  `FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE`.
  Migration is a no-op on SQLite.
- **Failure modes.** If `JOBTRACKER_SECRET_ENCRYPTION_KEY` is unset,
  `cloud.save_*_credentials` raises `CredentialEncryptionError`
  immediately (loud failure). Invalid ciphertext (bad key or
  tampered row) causes `cloud.get_*_credentials` to log and return
  `None` — routers degrade gracefully.

## Sync (cloud) — three triggers, one code path

`POST /gmail/sync` (`jobtracker/cloud/gmail_oauth.py`) is the only sync
implementation. Everything below is a different way of *calling* it, not
a second sync:

| Trigger | Who fires it | Budget | Notes |
|---|---|---|---|
| "Sync now" | The user | 60 s | The path that completes a first backfill |
| Arrival auto-sync | `apps/web/components/dashboard/SyncBar.tsx` when the board is stale, with a per-tab cooldown | 60 s | Why "the board never refreshes" is no longer true |
| `GET\|POST /cron/sync` | Vercel Cron, `*/15 * * * *` | 10 s per user, 45 s per run | The only one that runs **while nobody is looking** |

The cron is what makes "something happened while you were gone" a real
event: the change ledger can otherwise only report changes the open tab
itself just fetched. It calls `gmail_sync` directly with an explicit
`user_id`, wrapped in `user_id_scope(user_id)` so every read inside runs
under that user's RLS identity — the endpoint has no JWT, but nothing
inside it is unscoped.

That identity is also what makes the enumeration work at all. A cron
cannot read `user_credentials` to *discover* its users: that table is
FORCE-RLS on `auth.uid()`, so an identity-less read of it matches no row.
The membership fact comes from `gmail_sync_enrollment` instead — one
query, no identity, written in the same transaction as the credential —
and each candidate is then probed and synced inside its own
`user_id_scope`: an identity, not an exemption, so no extra database
credential is involved. The probes share one connection and re-bind that
identity per transaction, because a session per user is a fresh ~216 ms
connection under NullPool and 300 users' worth of them exceeds the run's
whole budget. Setup, bounds and cost are in
[`DEPLOYMENT.md`](./DEPLOYMENT.md#who-gets-synced).

**No WebSocket on cloud, and no WebSocket anywhere.** The Vercel Python
runtime does not support it. The module that once served it,
`jobtracker/api/websocket.py`, was deleted with the rest of
`jobtracker/api/` (issue #73), as was the guard test that used to be
named `tests/test_desktop_routers_are_not_mounted.py`. What replaces
that guard is
`backend/tests/test_the_deployed_app_is_the_cloud_app.py`, which walks
every mounted handler and fails the build if any route arrives from a
module outside `jobtracker.cloud`. The web UI polls; progress after
"Sync now" comes from the sync response and `GET /auth/gmail/status`,
not from a stream.

## Cloud entrypoints

- `api/index.py` — Vercel Python runtime entry. Prepends `backend/` to
  `sys.path`, forces `JOBTRACKER_DEPLOYMENT=cloud`, re-exports
  `jobtracker.main_cloud.app`.
- `vercel.json` (repo root — the `jobtracker-api` project's config; the
  web project reads `apps/web/vercel.json`) — routes every path to
  `api/index.py`, caps it at `maxDuration: 60`, and declares the
  `*/15 * * * *` cron for `/cron/sync` (C7, shipped).
- `requirements.txt` (repo root) — Vercel-safe dependency set, no torch
  or keyring; `backend/requirements.txt` keeps the full desktop set.

## Intended request flow (cloud, once C3–C7 land)

```
browser
  ↓  supabase-js exchanges email+password for JWT
Next.js (apps/web/ on Vercel)
  ↓  Authorization: Bearer <JWT>
FastAPI (backend/jobtracker/main_cloud.py via api/index.py)
  ↓  Depends(current_user) validates Supabase JWT → UUID
Supabase Postgres (asyncpg, transaction-mode pooler)
  - All queries scoped by user_id; RLS policies defense-in-depth.
  - user_credentials rows decrypted with Fernet for Gmail/iCloud access.
```

## Out of scope (v1 migration)

- WebSocket on cloud (Vercel Python doesn't support it; polling only).
- SetFit inference on cloud (stays macOS-only; revisit via external
  service).
- ~~macOS app removal~~ — **no longer out of scope: it happened.** The
  SwiftUI client in `apps/macos/` and the desktop app builder
  `backend/jobtracker/main.py` were de-scoped on 2026-08-12 and deleted,
  along with `macos-ci.yml`. Applied is web-only. The `desktop` value of
  `JOBTRACKER_DEPLOYMENT` survives as a settings default and is why
  `api/index.py` forces `cloud` (see "Deployment modes" above), but it
  builds nothing. This line is kept rather than removed because it read
  the opposite way for months and a reader who saw it should be able to
  find the correction.

## Issue map

| Area | Issue |
|---|---|
| Deployment toggle + shim | #14 (C1) |
| Postgres + Alembic | C2 |
| Supabase Auth + user_id + RLS | #20 (C3) |
| Encrypted credentials | #21 (C4) |
| Gmail web OAuth | C5 |
| Rules-only cloud classifier | #17 (C6) |
| WebSocket → polling + cron | #23 (C7) |
| test_cloud pytest marker | C8 |
| Next.js scaffold | C9 |
| Typed API client | C10 |
| Web screens | C11–C16 |
| CI pipelines | C17 |
| Docs finalization | C18 |
