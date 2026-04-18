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
