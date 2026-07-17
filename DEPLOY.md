# Deploying JobTracker (free tier, minimal owner effort)

Topology: **two Vercel projects from this one repo** + optional Supabase.
The web app and the Python API are structurally separate — the root
`vercel.json` routes everything to `api/index.py`, so the web app must
be its own project rooted at `apps/web`.

## Path A — recruiter-ready demo (1 login, ~10 min)

The web app's `/` (landing) and `/demo` (fixture data) run with **no
backend and no Supabase**.

1. Vercel → import repo → **root directory `apps/web`** → deploy.
2. Set `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` to
   URL-valid placeholders and `BACKEND_API_URL=https://example.com`
   (zod env validation needs values; auth pages are reachable but
   unused by the demo path).

## Path B — real auth + applications API (2 logins, ~40 min)

| Variable | API project (repo root) | Web project (`apps/web`) |
|---|---|---|
| `JOBTRACKER_DEPLOYMENT=cloud` | already in vercel.json | — |
| `JOBTRACKER_SUPABASE_JWT_SECRET` | ✔ (Supabase **legacy HS256** JWT secret — verify the project isn't ES256-only) | — |
| `JOBTRACKER_DATABASE_URL_OVERRIDE` | ✔ `postgresql+asyncpg://…pooler.supabase.com:6543/postgres` | — |
| `JOBTRACKER_CORS_ALLOWED_HOSTS` | ✔ web project domain | — |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | — | ✔ |
| `BACKEND_API_URL` | — | ✔ API project URL |

Steps:
1. Supabase: create free project; copy URL, anon key, JWT secret, DB
   password; disable email confirmation (portfolio friction).
2. Migrations (local, once):
   `cd backend && ./.venv311/bin/pip install -r requirements-migrate.txt &&
   DIRECT_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" ./.venv311/bin/alembic upgrade head`
   (direct 5432 URL — the 6543 pooler breaks DDL).
3. Vercel: two projects as above; env per matrix; deploy; smoke
   `GET /health`, then signed-in `GET /auth/me` + `POST/GET /applications`.

## Known limits of the cloud build (by design, today)

Cloud serves auth + applications CRUD only. Email sync, classification,
review queue, and analytics are desktop-only routers not yet mounted in
`main_cloud` — the classifier's public story is carried by the ML demo
(`ml/demo`, Hugging Face Spaces) and the web `/demo` fixture until the
cloud routers land.
