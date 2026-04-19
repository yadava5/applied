# Web Architecture

> **Status:** Stub created by issue #14 (C1 cloud shim). Filled in
> incrementally by C2–C18. Until this banner is removed, most sections
> describe *intended* state, not shipped state.

## Deployment modes

JobTracker runs in one of two modes, selected by
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

## Cloud entrypoints

- `api/index.py` — Vercel Python runtime entry. Prepends `backend/` to
  `sys.path`, forces `JOBTRACKER_DEPLOYMENT=cloud`, re-exports
  `jobtracker.main_cloud.app`.
- `vercel.json` — routes every path to `api/index.py`, pins Python 3.11,
  declares the placeholder cron for `/cron/sync` (implemented in C7).
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
| Supabase Auth + user_id + RLS | C3 |
| Encrypted credentials | C4 |
| Gmail web OAuth | C5 |
| Rules-only cloud classifier | #17 (C6) |
| WebSocket → polling + cron | C7 |
| test_cloud pytest marker | C8 |
| Next.js scaffold | C9 |
| Typed API client | C10 |
| Web screens | C11–C16 |
| CI pipelines | C17 |
| Docs finalization | C18 |
