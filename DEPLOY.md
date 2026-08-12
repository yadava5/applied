# Deploying Applied (free tier, minimal owner effort)

> Product name: **Applied**. The repo, backend project, and `JOBTRACKER_*`
> environment variables keep the original `jobtracker` identifier — those are
> real config keys and infra names, not the product brand.

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
| `JOBTRACKER_SUPABASE_JWT_SECRET` | ✔ (Supabase **legacy HS256** JWT secret) | — |
| `JOBTRACKER_SUPABASE_JWKS_URL` | ✔ **if the project signs with ES256** — `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` | — |
| `JOBTRACKER_DATABASE_URL_OVERRIDE` | ✔ `postgresql+asyncpg://…pooler.supabase.com:6543/postgres` | — |
| `JOBTRACKER_CORS_ALLOWED_HOSTS` | ✔ web project domain | — |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | — | ✔ |
| `BACKEND_API_URL` | — | ✔ API project URL |

> **ES256 vs HS256 (the #1 live-auth trap).** Supabase projects created since
> 2025 sign user JWTs with **ES256** (asymmetric) keys, published at
> `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`. The backend
> verifies ES256 against that JWKS and HS256 against the legacy secret — but it
> can only do the ES256 path if `JOBTRACKER_SUPABASE_JWKS_URL` is set. If your
> project is ES256 and that var is missing, **every** authenticated backend call
> returns 401, which the web app surfaces as "Can't connect Gmail" and an inbox
> that won't load. Check your project's `.well-known/jwks.json`: if it lists an
> `ES256` key, set `JOBTRACKER_SUPABASE_JWKS_URL`.

Steps:
1. Supabase: create free project; copy URL, anon key, JWT secret, DB
   password; disable email confirmation (portfolio friction).
2. Migrations (local, once):
   `cd backend && ./.venv311/bin/pip install -r requirements-migrate.txt &&
   DIRECT_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" ./.venv311/bin/alembic upgrade head`
   (direct 5432 URL — the 6543 pooler breaks DDL).
3. Vercel: two projects as above; env per matrix; deploy; smoke
   `GET /health`, then signed-in `GET /auth/me` + `POST/GET /applications`.

## Path C — real Gmail connection (C5: connect → read → classify)

This turns on the actual "Connect Gmail → read inbox → classify → show
verdicts" path for signed-in users (backend router
`jobtracker/cloud/gmail_oauth.py`, web `/settings` + `/inbox`). It needs
**Path B already working** (auth + Postgres), plus a Google OAuth *Web*
client and one extra key. **You (the owner) create the Google credentials
and paste the secret into Vercel — it never goes in the repo or in chat.**

### Owner steps in Google Cloud Console

A Google Cloud project already exists from TaskFlow (`taskflow-502817`).
**Use a *dedicated* OAuth client for Applied** (ideally a dedicated
project, e.g. `jobtracker`) so Gmail's restricted-scope verification and
test-user list don't entangle TaskFlow. The consent screen is per-project,
so a separate project is the cleanest boundary.

1. **APIs & Services → Enable APIs** → enable **Gmail API**.
2. **OAuth consent screen** → User type **External** → fill app name /
   support email → **Scopes**: add exactly
   `https://www.googleapis.com/auth/gmail.readonly` (nothing broader) →
   **Test users**: add each email you want to let connect (max 100 while
   unverified) → keep **Publishing status = Testing**.
3. **Credentials → Create credentials → OAuth client ID → Application type
   = Web application**. Under **Authorized redirect URIs** add, byte-for-byte,
   the API callback:
   `https://<your-api-project>.vercel.app/auth/gmail/callback`
   (add the localhost variant too if you run `vercel dev`).
4. Copy the generated **Client ID** and **Client secret**.

### Env — API project (repo root), added to Path B's matrix

| Variable | Value | Notes |
|---|---|---|
| `JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID` | the Web client ID | public by design |
| `JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET` | the Web client secret | **secret — paste in Vercel only; never commit / never share in chat** |
| `JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI` | `https://<api>.vercel.app/auth/gmail/callback` | must equal the console entry exactly |
| `JOBTRACKER_WEB_APP_URL` | `https://<web>.vercel.app` | fixed post-callback redirect target (no open redirect) |
| `JOBTRACKER_SECRET_ENCRYPTION_KEY` | Fernet key (already set in C4) | encrypts the refresh token **and** signs the OAuth `state` |

`JOBTRACKER_SECRET_ENCRYPTION_KEY` is generated with:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

No new **web** env is needed — the web app reaches these endpoints through
the existing `BACKEND_API_URL`.

### Verify

1. Redeploy the API project. `GET /auth/gmail/status` (with a signed-in
   JWT) should return `{"configured": true, "connected": false}`. Until the
   env is set it honestly returns `configured: false` (HTTP 200) and
   `/auth/gmail/authorize` returns **503**, not a 500.
2. In the web app, sign in → **Settings → Connect Gmail** → Google consent →
   land back on `/settings?gmail=connected` → **Inbox** shows real, classified
   mail. **Disconnect** revokes at Google and deletes the stored token.

### Scale reality (state this plainly; don't over-claim)

`gmail.readonly` is a Google **restricted** scope. While the app is
unverified it can authorize **at most 100 test users** added on the consent
screen; broad public use requires Google **OAuth verification + a CASA
security assessment**. So the direct connection above is real and secure but
gated to invited testers.

The path that scales publicly **without** restricted-scope verification is
**forwarding ingestion**: the user sets a Gmail filter that auto-forwards
job-related mail to a per-user Applied ingest address, and the same
classifier labels what arrives (no account access, no restricted scope).
For "deploy only things good to scale," **forwarding ingestion is the
recommended public path**; the OAuth connection fits a small invited group
and the desktop app. Forwarding ingestion is not yet built — it is the
recommended next increment.

## Path D — "Sign in with Google" (Supabase Auth social login)

This adds a **Continue with Google** button to `/login` and `/signup` so users
can authenticate with a Google account instead of email + password. It is a
**Supabase Auth provider** and is entirely distinct from Path C:

| | Path C — Connect Gmail | Path D — Sign in with Google |
|---|---|---|
| What it does | reads the user's inbox (`gmail.readonly`) | authenticates the user into the app |
| Who owns the OAuth flow | the **FastAPI backend** | **Supabase Auth (GoTrue)** |
| Google redirect URI | `https://<api>.vercel.app/auth/gmail/callback` | `https://jbyvatoodyqqvkqbsrju.supabase.co/auth/v1/callback` |
| Where the client secret lives | Vercel env on the **API** project | **Supabase dashboard** (never Vercel, never the repo) |
| Scopes | `gmail.readonly` (restricted) | `openid email profile` (Supabase defaults; no verification needed) |

No code, web env, or backend env changes are required to turn this on — the
button and the `/callback` code-exchange are already shipped. **Until an owner
completes the steps below, the button is graceful: clicking it shows an inline
"Google sign-in isn't configured yet." and never navigates to a broken page.**

### Owner steps (≈10 min; you do these, not the repo)

1. **Google Cloud Console → APIs & Services → Credentials.** Use a **Web
   application** OAuth client. You *may reuse* the existing JobTracker Web
   client from Path C (or make a dedicated one — cleaner separation). To the
   client's **Authorized redirect URIs** add, byte-for-byte:

   ```
   https://jbyvatoodyqqvkqbsrju.supabase.co/auth/v1/callback
   ```

   (This is Supabase's own auth callback — Google returns here first, then
   Supabase redirects on to the app's `/callback` route. Do **not** put the app
   domain here.) Copy the **Client ID** and **Client secret**.
   - No consent-screen scope changes are needed: "Sign in with Google" only
     uses the basic `openid email profile` scopes, which are non-sensitive, so
     this does **not** drag in Gmail's restricted-scope verification.

2. **Supabase → Authentication → Providers → Google.** Toggle **Enable**, paste
   the **Client ID** and **Client secret**, **Save**. *The secret is entered
   only here — it is never committed to the repo and never shared in chat.*

3. **Supabase → Authentication → URL Configuration.** Confirm:
   - **Site URL** = `https://getapplied.vercel.app`
   - **Redirect URLs** allowlist includes `https://getapplied.vercel.app/**`
     (and `http://localhost:3000/**` for local dev). The web app sends
     `redirectTo=<origin>/callback`, which must match this allowlist or Supabase
     rejects the redirect.

### Verify

- Provider **off**: `/login` → **Continue with Google** shows the inline
  "Google sign-in isn't configured yet." message (no crash, no JSON page). This
  is driven by a pre-flight against
  `…/auth/v1/authorize?provider=google&skip_http_redirect=true`, which answers
  `400 {"msg":"Unsupported provider: provider is not enabled"}` while disabled.
- Provider **on**: clicking **Continue with Google** redirects to Google
  consent → back through Supabase → the app's `/callback` route exchanges the
  PKCE code for a session → lands on `/dashboard` (or the `?redirect=` path a
  protected page bounced through). Email + password sign-in is unaffected.

## Known limits of the cloud build (by design, today)

Cloud serves auth + applications CRUD **and** the Gmail web-OAuth read →
classify path (C5, Path C above; rules-only classifier). Email sync
persistence, the review queue, SetFit, and analytics remain desktop-only
routers not yet mounted in `main_cloud` — the full-model classifier story is
carried by the ML demo (`ml/demo`, Hugging Face Spaces) and the web `/demo`
fixture. Until an owner completes Path C's Google setup, the deployed
`/settings` page honestly reports Gmail as "not enabled on this deployment."

## Which commits deploy

Both Vercel projects build from this one repo, so every commit used to trigger
two deployments — including workflow bumps and backend dependency updates that
can change neither bundle. `vercel-ignore-build.sh` is now the Ignored Build
Step for both, wired up through `ignoreCommand`:

| Project          | Root Directory | Config                | Builds when these change                                             |
| ---------------- | -------------- | --------------------- | -------------------------------------------------------------------- |
| `jobtracker-api` | repo root      | `vercel.json`         | `api/`, `requirements.txt`, `backend/jobtracker/`, `vercel.json`, `.vercelignore` |
| `jobtracker-web` | `apps/web`     | `apps/web/vercel.json`| `apps/web/`, `.vercelignore`                                          |

`ignoreCommand` in `vercel.json` overrides whatever the dashboard's Ignored
Build Step says, so the guard is version-controlled rather than a dashboard
field — but JSON has no comments, and the exit codes are inverted (`exit 0`
skips, `exit 1` builds). **The reasoning lives in the header of
`vercel-ignore-build.sh`; read it before touching either config.** The path
lists are an allowlist: a new build input that is not added there will never
deploy.

Dependabot branches are still skipped by branch-name prefix, exactly as before.
A branch's first preview always builds, so the e2e browser pass always has a
preview URL.

Two things this does **not** do. It does not lower the Hobby plan's
100-deployments-per-day count: Vercel's docs are explicit that "canceled builds
are counted as full deployments … and will still count towards your deployment
quotas and concurrent build slots." What it saves is build minutes and the
single Hobby concurrent-build slot (seconds instead of a full Next.js build),
and it stops no-op commits from replacing a good production deployment. And it
does not replace `git.deploymentEnabled`, which is the only repo-side setting
that stops a deployment from being *created* at all.
