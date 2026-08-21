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
2. Migrations — **bootstrap only**. Ongoing revisions are applied by the
   `DB migrate` workflow on every push to main that touches
   `backend/alembic/**`; see `docs/MIGRATIONS.md`, which is the contract for
   schema changes (including why destructive ones need two merges). To bring a
   brand-new project up from empty:
   `cd backend && ./.venv311/bin/pip install -r ../requirements.txt -r requirements-migrate.txt &&
   DIRECT_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" ./.venv311/bin/alembic upgrade head`
   (direct 5432 URL — the 6543 pooler breaks DDL).
   Then set that same URL as the `DIRECT_URL` secret on the repo's `production`
   environment so the workflow can take over.
3. Vercel: two projects as above; env per matrix; deploy; smoke
   `GET /health`, `GET /health/schema` (must report `ok: true`), then signed-in
   `GET /auth/me` + `POST/GET /applications`.

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

### `JOBTRACKER_TRAINING_ALLOWED_USER_IDS` — leave it unset

| Variable | API project (repo root) | Web project (`apps/web`) |
|---|---|---|
| `JOBTRACKER_TRAINING_ALLOWED_USER_IDS` | **deliberately unset** — comma-separated UUIDs when a local run needs it | — |

SetFit training refuses to read anybody's `training_data` rows unless their
user id is named in this variable, or the corpus it loaded is entirely
synthetic (`mock_seed*`, `external_dataset`). **Empty is the default and the
correct production value**: nothing hosted retrains, so the deployed API
should be structurally unable to train on a user — including on the owner.
Enforced in `backend/jobtracker/classifier/setfit_model.py`
(`_assert_training_allowed`), pinned by
`backend/tests/test_training_is_owner_only.py`.

Two things about it that are load-bearing rather than fussy:

- **It fails closed.** Unset, misspelt, or dropped from the environment, the
  answer is "refused", never "allowed". Setting it in the hosted deployment is
  a policy change, not a fix for a failing retrain.
- **A malformed entry stops config load** with a
  `TrainingAllowedUserIdsError` that names the failing **index** and withholds
  the value, because it reaches build logs. Same treatment, and the same
  reason, as `JOBTRACKER_CRON_SYNC_USER_IDS`.

Why the gate exists on top of the single-user scoping that was already there:
scoping only buys *single-user*, which a run aimed at one stranger's mailbox
satisfies perfectly. Gmail's restricted `gmail.readonly` scope permits
training only a model personalized to one end user, so whose mail a model may
see has to be a configured fact rather than a caller's argument.

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

A branch's first preview always builds, so the e2e browser pass always has a
preview URL.

`scripts/test_vercel_ignore_build.mjs` pins every one of these answers against
real commits from this repository's history, and
`scripts/negative_control_ignore_build.mjs` breaks the guard ten ways to prove
that suite can go red. Both run in CI (`.github/workflows/vercel-ignore-build.yml`)
on any change to the guard, to either `vercel.json`, or to `.vercelignore`. If
you change the allowlist, change the suite in the same commit.

### An environment-variable change cannot trigger a build

**Adding, changing or enabling an environment variable will not deploy itself,
and the attempt fails silently.** Vercel injects environment variables at deploy
time, so a new variable is inert until a build picks it up — but `vercel
redeploy` of the current production deployment sets `VERCEL_GIT_PREVIOUS_SHA`
to the very commit being redeployed. The guard then diffs a commit against
itself, finds nothing, and skips.

Observed exactly that on 2026-08-14 while activating
`SUPABASE_SERVICE_ROLE_KEY`: deployment `jobtracker-2g3prxucv` went straight to
**CANCELED**, production kept serving the old build, and the variable stayed
inert with nothing anywhere reporting a problem.

The guard is right by its own contract — it answers "did this commit touch
anything this project builds from", and for a redeploy of an unchanged commit
the honest answer is no. The gap is that **the question it asks is not the only
reason a build is needed.** Config lives outside the tree and a path diff cannot
see it.

**So after changing an environment variable, push a commit that touches that
project's allowlist.** It is the only route verified to work here, and it has
the side benefit of leaving a record of when the variable took effect.

Two things that look like shortcuts and are not:

- **`--force` is about the build cache, not this guard.** Vercel documents
  `vercel deploy --force` as bypassing the *build cache*; nothing in the docs
  says it bypasses the Ignored Build Step. Do not assume it does — the observed
  behaviour above is a redeploy reaching the guard and being CANCELED by it.
- **A CLI `vercel --prod` is not a proven way round it either.** Whether a CLI
  deployment supplies `VERCEL_GIT_PREVIOUS_SHA` has not been checked here. If it
  does not, the guard takes its documented production fallback and measures
  `HEAD^` — a one-commit window that skips just as readily when the tip commit
  touches nothing the project builds from. Treat the CLI as untested for this
  purpose rather than as the escape hatch.

Do not "fix" this by making a same-SHA diff build. That would mean the guard can
never skip anything, which is the entire feature. `scripts/test_vercel_ignore_build.mjs`
pins the current behaviour so a change to it is a decision rather than an
accident.

### The ignore step does not save quota — read this before "optimising" it

An Ignored Build Step skip still costs a deployment. This is the opposite of
the intuitive reading, so here it is verbatim, from
<https://vercel.com/docs/project-configuration/project-settings#ignored-build-step>:

> Canceled builds are counted as full deployments as they execute a build
> command in the build step. This means that any canceled builds initiated
> using the ignore build step will still count towards your deployment quotas
> and concurrent build slots.

The Hobby cap is 100 deployments per day, and this repo has hit it. What a skip
buys is build minutes, the single Hobby concurrent-build slot released in well
under a second instead of a full Next.js build, and a production deployment
that no-op commits stop replacing. Worth having — but it is not the cap.

### `git.deploymentEnabled` is the part that saves quota

Both `vercel.json` files carry a `git.deploymentEnabled` block, and **the two
are no longer the same** — `apps/web/vercel.json` still filters only Dependabot,
while the root (api) config now refuses every branch except `main`:

```json
// apps/web/vercel.json — web previews are looked at by a human before merge
"git": { "deploymentEnabled": { "dependabot/**": false, "dependabot/*": false } }
```

```json
// vercel.json — the api takes no previews at all
"git": { "deploymentEnabled": { "**": false, "main": true } }
```

Vercel never *triggers* a deployment for a disabled branch, so nothing is
created and nothing is counted. That is the part that saves quota; the ignore
step is not.

The api's `"**": false` landed in `e4c72f0`, committed 2026-08-13 22:02 EDT
(2026-08-14 02:02 UTC) — hours after the api project spent its whole daily
allowance on previews that same day and then could not deploy production for
eleven hours. Nothing consumes an api preview: `e2e-ci.yml` boots **no backend
at all** — the `uvicorn jobtracker.main:app` step was removed with the desktop
app it started (issue #73), and the suite is green pointing at a `:8000` that
has nothing on it, because every route the specs visit is public or redirects
at the protected layout before any API call. `production.spec.ts` runs against
a local `next start`, and there is no UI on an api preview to look at.
**The `"main": true` key is load-bearing, not decorative.** Precedence here is not
most-specific-wins — "If a branch matches multiple rules and at least one rule
is `true`, a deployment will occur"
([docs](https://vercel.com/docs/project-configuration/git-configuration)) — so
`"**": false` alone would take production down with it.

The web project is deliberately left on the Dependabot-only filter: its
previews are looked at by a human before merge, which is a real use. Dependabot
branches never need a preview URL — the Claude-in-Chrome e2e pass only ever
runs against real feature work.

**In the web config, the `**` is what does the work.** These patterns are
[minimatch](https://github.com/isaacs/minimatch), where `*` does not cross a
`/`. Real branch names here look like
`dependabot/pip/backend/beautifulsoup4-gte-4.15.0` — three slashes — so a
lone `dependabot/*` would have matched *nothing* and silently done nothing.
`dependabot/*` is kept alongside `dependabot/**` only as insurance against a
matcher that treats `*` as crossing `/`; where rules conflict Vercel takes the
permissive one, and both of these are `false`, so they cannot fight.

`main` has no branch protection and no rulesets, so no Vercel status is a
required check and a missing or skipped one cannot block a merge.

**Do not rely on a Vercel commit status arriving at all.** The documentation
describes them as terminal — a status reports that a commit "successfully
deployed or failed, or skipped its Vercel deployment" — but that describes
statuses that get posted, not a guarantee that one will be. Measured on
2026-08-13 while the daily cap was exhausted (#174):

| commit    | what Vercel posted                                             |
| --------- | -------------------------------------------------------------- |
| `d3765b2` | `success` on both; api reads "Canceled by Ignored Build Step"   |
| `12b8aee` | `failure` on both: "Deployment rate limited — retry in 24 hours" |
| `9394485` | web `success`, api `failure` (rate limited)                     |
| `60fcec2` | **nothing at all** — no status, no deployment, `pending` forever |

So a merge to `main` really can sit at `pending` indefinitely with no deployment
behind it, and `gh pr checks` shows green because there is nothing red to show.
The absence of a signal is not success here. Checking that production actually
moved is a separate act from checking that CI went green.

### Something now performs that separate act

`.github/workflows/production-drift.yml` runs `scripts/check_production_drift.py`
twice an hour and fails when what production is **running** disagrees with
`main`'s tip for longer than 30 minutes — the grace window, and the deploy
timings it comes from, are the `DEPLOY_GRACE` constant in that script. It is
blind to the cause on purpose: a rate limit, a lost webhook and a CANCELED
redeploy all look the same from here, and all three have happened.

Three things keep it from crying wolf, and all three are pinned as fixtures in
`scripts/test_production_drift.py`: a window the Ignored Build Step legitimately
skips is green (`975d72e` was skipped on both projects and left production
behind main forever, by design), a deployment that is QUEUED or BUILDING is
green, and a tip younger than the window is green. The same suite aims the
detector at `12b8aee` and `60fcec2` — the two merges from #174 that genuinely
never deployed — and requires it to go red for both.

What it reads is deliberately **not** `GET /repos/:owner/:repo/deployments?sha=`,
which is empty for a healthy skip and for a silent miss alike. For the api it
reads `GET /health`, which reports the running commit from Vercel's own
`VERCEL_GIT_COMMIT_SHA` and needs no credential; for the web app it reads the
newest READY production deployment's `meta.githubCommitSha` from the Vercel REST
API, which needs a read-scoped token in the `VERCEL_TOKEN` repository secret.
**That secret does not exist yet**, so until an owner creates it the live job is
red with `UNKNOWN`, which is the honest answer for a check that cannot see.

### The dashboard "Skip deployments when there are no changes…" toggle is inert here

Do not bother enabling it. Vercel's built-in
[skipping of unaffected projects](https://vercel.com/docs/monorepos#skipping-unaffected-projects)
requires npm/yarn/pnpm/Bun **workspaces**, "detected using the lockfile at the
repository root". This repo has no root `package.json`, no root lockfile and no
`pnpm-workspace.yaml` — the lockfile is `apps/web/pnpm-lock.yaml`. The
documented fallback is that everything counts as a global change and "deploy
all applications in the repository", followed by: "If your project does not
meet these requirements, you can use the Ignored Build Step." That is exactly
what the guard above is.

If a root workspace definition is ever added, the toggle becomes the *better*
lever and should replace the guard: unlike the Ignored Build Step it "does not
occupy concurrent build slots".
