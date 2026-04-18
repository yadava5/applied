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
- `backend/jobtracker/classifier/hybrid.py` (lazy SetFit import in C6).

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
| Rules-only cloud classifier | C6 |
| WebSocket → polling + cron | C7 |
| test_cloud pytest marker | C8 |
| Next.js scaffold | C9 |
| Typed API client | C10 |
| Web screens | C11–C16 |
| CI pipelines | C17 |
| Docs finalization | C18 |
