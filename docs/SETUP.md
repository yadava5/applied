# Setup Guide

> This guide described the macOS + local-SQLite setup until the desktop app was
> de-scoped (2026-08-12) and deleted. Applied is web-only: a Next.js app and a
> FastAPI serverless function, both deployed on Vercel over Supabase.

## Requirements

- Node 22 and pnpm 10
- Python 3.11+
- Git
- A Supabase project (Postgres + Auth)

There is no Xcode requirement and no local model download: the deployed
classifier runs its rules layer only. The embedding and SetFit layers are still
in the tree and still exercised by the backend suite, but only the ML workflows
under `ml/` need their weights.

## 1. Clone

```bash
git clone <your-repo-url>
cd applied
```

## 2. Web app

```bash
cd apps/web
cp .env.example .env.local      # fill in Supabase + backend URLs
pnpm install --frozen-lockfile
pnpm dev                        # http://localhost:3000
```

`apps/web/README.md` is the authoritative reference for the environment
variables, the day-to-day scripts, and what `SUPABASE_SERVICE_ROLE_KEY` gates.

## 3. Backend

The backend is served by Vercel as a Python function from `api/index.py`; there
is no local process to start for normal web development — point
`BACKEND_API_URL` at a deployment.

To run the suite locally:

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r ../requirements.txt \
    pytest pytest-asyncio pytest-cov httpx aiosqlite alembic keyring numpy
JOBTRACKER_ENVIRONMENT=test \
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
    .venv/bin/python -m pytest tests -q \
        --ignore=tests/test_setfit_model.py \
        --ignore=tests/test_evaluate_classifier.py
```

Notes on that command, each of which has cost someone an afternoon:

- It installs the **root** `requirements.txt` — the cloud one. `backend/`'s own
  requirements pull torch + sentence-transformers + setfit (~800 MB) and are
  needed only for the two excluded files. CI installs those and runs them.
- `alembic`, `keyring` and `numpy` are **not** in the root requirements and must
  be added by hand. Without them about 16 tests fail in ways that read like real
  product bugs — an "alembic upgrade head failed", four health-endpoint
  failures, six OAuth resync failures — every one a `ModuleNotFoundError`
  swallowed by a subprocess or an exception handler. Grep a local red for
  `ModuleNotFoundError` before believing it.

To serve the cloud app locally (rarely needed):

```bash
cd backend
JOBTRACKER_DEPLOYMENT=cloud python -m uvicorn jobtracker.main_cloud:app --port 8000
```

## 4. Connect a Gmail account

Sign in to the running web app and use Settings → Connect Gmail. The OAuth flow
is server-side (`/auth/gmail/authorize` → `/auth/gmail/callback`); credentials
are stored as encrypted rows in Postgres, not in a system keychain. The scope
requested is `gmail.readonly` and nothing else.

## Useful Commands

```bash
./scripts/generate_api_schema.sh   # regenerate apps/web/lib/api/schema.d.ts
python3 scripts/readme_facts.py --check   # every number the README asserts
pnpm -C apps/web lint
pnpm -C apps/web test:unit
pnpm -C apps/web build
```

## Common Issues

**`BACKEND_API_URL is required` at boot.** `apps/web/lib/env.server.ts`
validates the server env with zod and refuses to start without it.

**Settings → Delete account answers 501.** The deployment has no
`SUPABASE_SERVICE_ROLE_KEY`. Vercel injects environment variables at deploy
time, so adding it needs a redeploy before it takes effect.
