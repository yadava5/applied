# Web Architecture

> **Status:** Stub created by issue #14 (C1 cloud shim). Filled in
> incrementally by C2–C18. Until this banner is removed, most sections
> describe *intended* state, not shipped state.

## Deployment modes

Applied runs in one of two modes, selected by
`JOBTRACKER_DEPLOYMENT`:

| Mode | Host | UI | DB | Auth | Secrets | Classifier |
|---|---|---|---|---|---|---|
| `desktop` (default) | local process, bundled .app | SwiftUI (`apps/macos/`) | SQLite (`~/Library/Application Support/JobTracker/`) | single-user, trust-local | macOS Keychain via `keyring` | rules + embeddings + SetFit |
| `cloud` | Vercel serverless | Next.js on Vercel (`apps/web/`) | Supabase Postgres | Supabase Auth (JWT) | Fernet-encrypted Postgres rows | rules only (v1) |

Both modes share the same `backend/jobtracker/` package. The divergence
is kept in:
- `backend/jobtracker/main.py` (desktop app builder) vs.
  `backend/jobtracker/main_cloud.py` (cloud app builder).
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
- **Token format.** HS256 JWT signed with `SUPABASE_JWT_SECRET` (the
  project-wide Supabase signing key, configured as
  `JOBTRACKER_SUPABASE_JWT_SECRET` on Vercel). Supabase default
  claims: `sub` (UUID of `auth.users.id`), `aud` = `"authenticated"`,
  plus `exp` / `iat` / `role`.
- **Verification.** `backend/jobtracker/auth/supabase_jwt.py` decodes
  the token with `pyjwt[crypto]`, pinned to `algorithms=["HS256"]`
  (rejects `alg: none` and `alg: RS256`), with
  `audience="authenticated"` and `require=["exp", "sub", "aud"]`.
  The `sub` claim is parsed as `uuid.UUID` and returned by the
  `current_user` dependency.
- **Router contract.** Cloud-only routers live under
  `backend/jobtracker/cloud/` and declare
  `dependencies=[require_user()]` at the router level. Desktop
  routers in `backend/jobtracker/api/` stay unauthenticated — the
  two package trees are separate so the cloud app's import graph
  never pulls in `jobtracker.credentials` / `keyring`.
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
- **Desktop.** Unchanged. `jobtracker.main` never imports the auth
  module; desktop rows are owned by a fixed sentinel UUID
  (`00000000-0000-0000-0000-000000000000`) declared in
  `jobtracker.database.models.LOCAL_USER_ID`.

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
- **Corrections.** User-corrected labels still persist to
  `TrainingData` and sync back to macOS, where the full 3-layer
  hybrid remains canonical.
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
- **TanStack Query 5** installed in preparation for C10 (real API client).
- **zod** for runtime env validation (`lib/env.ts`).
- **shadcn/ui**-compatible scaffold: `components.json` in place,
  `components/ui/button.tsx` committed; further primitives are added via
  `pnpm dlx shadcn@latest add ...`.

File layout:

```
apps/web/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx      # email+password form
│   │   ├── signup/page.tsx     # email+password form
│   │   └── callback/route.ts   # PKCE code-exchange handler
│   ├── (app)/
│   │   ├── layout.tsx          # protected AppShell wrapper
│   │   └── dashboard/page.tsx  # placeholder
│   ├── layout.tsx              # root html + Geist fonts
│   └── globals.css             # Tailwind entry
├── components/
│   ├── shell/{AppShell,Sidebar,TopBar}.tsx
│   └── ui/button.tsx
├── lib/
│   ├── env.ts                  # zod-validated process.env
│   ├── utils.ts                # cn() helper
│   └── supabase/{client,server,middleware}.ts
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

The scaffold intentionally does **not** wire the real backend API
client — that arrives in C10 as a typed `fetch` wrapper bound to
`BACKEND_API_URL` and the Supabase JWT.

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
cannot *discover* its users: `user_credentials` is FORCE-RLS on
`auth.uid()`, so an identity-less read of it matches no row. The users
come from `JOBTRACKER_CRON_SYNC_USER_IDS` instead, and each is probed and
synced inside its own `user_id_scope` — an identity, not an exemption, so
no policy, migration or extra database credential is involved. Setup,
bounds, cost and the list-rot cost of enumerating from config are in
[`DEPLOYMENT.md`](./DEPLOYMENT.md#scheduled-sync-vercel-cron).

**No WebSocket on cloud.** The Vercel Python runtime does not support it,
so `main_cloud.py` never includes `jobtracker/api/websocket.py` — and,
per `tests/test_desktop_routers_are_not_mounted.py`, never imports it.
`sync_ws_manager.broadcast()` is an explicit no-op wherever
`settings.deployment == "cloud"`, so the call sites in
`jobtracker/api/sync.py` are unconditional and identical in both
deployments. The web UI polls; progress after "Sync now" comes from the
sync response and `GET /auth/gmail/status`, not from a stream.

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
- macOS app removal — the desktop mode remains first-class.

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
