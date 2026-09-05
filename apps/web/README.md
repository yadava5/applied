# Applied web (`apps/web/`)

Next.js 16 (App Router) frontend for the cloud deployment of Applied.
Scaffolded in issue #24 (C9). This package is intentionally **not** wired
into a pnpm workspace — treat it as a standalone app for now.

## Stack

- **Next.js 16** (App Router, Turbopack) + **React 19.2**
- **TypeScript** strict mode
- **Tailwind CSS 4**
- **Supabase Auth** via `@supabase/ssr` (SSR-safe cookie handling)
- **`openapi-fetch`** over `openapi-typescript`-generated types — the real API
  client, shipped in C10 (`lib/api/`). TanStack Query is **not** installed and
  appears in neither `package.json` nor `pnpm-lock.yaml`; this line used to say
  it was
- **zod** for runtime env validation (`lib/env.ts`, `lib/env.server.ts`)
- **shadcn/ui** compatible (`components.json` in place; `Button`, `Dialog`,
  `Disclosure` and `Segmented` committed under `components/ui/`)

## Web dev

### One-time setup

```bash
cd apps/web
cp .env.example .env.local      # fill in Supabase + backend URLs
pnpm install --frozen-lockfile
```

Required env vars (see `.env.example` for full descriptions):

| Key | Scope | Purpose |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | public | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | public | Supabase anon key |
| `BACKEND_API_URL` | server | FastAPI backend base URL |
| `SUPABASE_SERVICE_ROLE_KEY` | server, optional | admin-only tasks — **without it "Delete account" cannot run** |

`SUPABASE_SERVICE_ROLE_KEY` is optional in the schema so a deployment without
it still boots, but it is not cosmetic: `auth.admin.deleteUser` needs it, so
Settings → Delete account refuses with a 501 on any deployment that lacks it.
That state is surfaced rather than hidden — the Settings page reads the
capability server-side and says so before the typed confirmation, and
`GET /api/account/delete` answers `{ "deletionEnabled": <bool> }` for anything
that wants to assert it against a deployed origin. Setting the key requires a
redeploy: Vercel injects environment variables at build/deploy time, so a value
added afterwards does not reach a running deployment.

### Day-to-day scripts

```bash
pnpm dev          # next dev (Turbopack) on http://localhost:3000
pnpm build        # next build (Turbopack)
pnpm start        # serve the production build
pnpm typecheck    # tsc --noEmit
pnpm lint         # eslint, --max-warnings 0 (next's a11y rules ship as warnings)
```

## Layout

Read from the tree on 2026-08-21 — except the `components/` line, whose count
and names are checked against `git ls-files` on every run of
`scripts/readme_facts.py` (#401). The C9 scaffold this block used to describe —
one placeholder dashboard, two component directories — is long gone.

```
apps/web/
├── app/
│   ├── (auth)/                    # login, signup, callback (PKCE),
│   │                              # forgot-password, reset-password
│   ├── (app)/
│   │   ├── (protected)/           # dashboard, inbox, settings, error.tsx
│   │   ├── import/                # the public import route
│   │   ├── privacy/
│   │   └── layout.tsx             # auth-gated shell
│   ├── api/                       # route handlers: account, applications,
│   │                              # auth, gmail
│   ├── demo/                      # signed-out product demo
│   ├── landing-a/ landing-c/      # landing variants
│   ├── fonts/  layout.tsx  page.tsx  not-found.tsx  globals.css
├── components/                    # 18 directories: applications, auth, beta,
│                                  # boot, brand, dashboard, demo, feedback,
│                                  # gmail, import, landing, mail, marketing,
│                                  # review, settings, shell, ui, viz
├── lib/
│   ├── env.ts / env.server.ts     # zod-validated public + server env
│   ├── api/                       # client.ts, server.ts, schema.d.ts,
│   │                              # serverTiming.ts
│   ├── supabase/                  # client, server, admin, auth, middleware,
│   │                              # protectedRoutes, pkceVerifierCookies
│   ├── utils.ts  theme.ts
│   └── account/ applications/ ambient/ boot/ dashboard/ demo/ gmail/
│       import/ mail/ security/ settings/ shell/
├── tests/
│   ├── e2e/                       # 21 Playwright spec files
│   └── unit/                      # node --test suite (`pnpm test:unit`)
├── scripts/                       # csp-gate.mjs, no-session-census.mjs,
│                                  # footage/
├── proxy.ts                       # Next 16 proxy (was middleware.ts)
├── components.json                # shadcn/ui config
└── .env.example
```

## Auth flow

1. Unauthenticated visitor hits any path under `/(app)/...` (i.e. `/dashboard`).
2. `proxy.ts` runs `updateSession(request)`:
   - Constructs a Supabase server client bound to the request cookie jar.
   - Calls `auth.getUser()` to refresh tokens if near expiry.
   - No user → redirects to `/login?redirect=<original>`.
3. User submits `/login` form → `supabase.auth.signInWithPassword` in the
   browser writes session cookies via `document.cookie`.
4. Client calls `router.refresh()` + `router.replace(redirect)`. The next
   server render sees the fresh cookies and the proxy lets them through.
5. `/(app)/layout.tsx` re-checks `auth.getUser()` as defence-in-depth.
6. Sign-out from `TopBar` calls `supabase.auth.signOut()` and redirects back
   to `/login`.

## Updating the API client

Typed bindings for the FastAPI backend live under `lib/api/`:

```
lib/api/
├── schema.d.ts   # GENERATED OpenAPI types — `paths` / `components` / `operations`
├── client.ts     # `createApiClient({ baseUrl, token? })` → typed openapi-fetch client
└── server.ts     # `createServerApiClient()` — reads Supabase JWT from cookies
```

`schema.d.ts` is committed so the app compiles without a live backend, and it
is **generated — never edited by hand**. Regenerate whenever the backend
contract changes:

```bash
pnpm -C apps/web api:gen        # `api:gen:local` is the same command
```

That runs `scripts/generate_api_schema.sh`, which builds the OpenAPI document
by importing `jobtracker.main_cloud` (the app `api/index.py` serves on Vercel)
and writes it through `openapi-typescript`. It needs the backend's Python
dependencies — `backend/.venv311` is used automatically when it exists,
otherwise `python3` from PATH, or set `PYTHON=…`.

No URL, and no running server. Both of the alternatives the old `api:gen` /
`api:gen:local` scripts pointed at were wrong: `:8000` used to be the desktop
app (`jobtracker.main`, booted by the e2e job), which served a *different*
contract — that is how the committed bindings drifted to cover 4 of the 20
paths the cloud app serves. A deployed URL is no better; it answers with
whatever was deployed last rather than what is in this checkout. The desktop
app has since been deleted and the e2e job boots no backend at all, which
removes the first trap but not the second.

`.github/workflows/e2e-ci.yml` runs the same script and fails on any diff, so
a stale `schema.d.ts` is a red build rather than a silent lie. After
regenerating, run `pnpm typecheck` — real shape changes surface there, and
every one of them is a call site that was reading something the backend does
not send.

Typical usage in a Server Component:

```tsx
import { createServerApiClient } from "@/lib/api/server";

export default async function Page() {
  const api = await createServerApiClient();
  const { data, error } = await api.GET("/auth/me");
  // `data` is typed as `{ user_id: string; authenticated: boolean } | undefined`
  if (error) return <p>Unauthorized</p>;
  return <p>{data.user_id}</p>;
}
```

## Not yet in scope

- Zod runtime validation layer on top of the static types. `zod` validates the
  environment (`lib/env.server.ts`); API responses are trusted as typed by the
  generated schema.
- Monorepo tooling. Neither `pnpm-workspace.yaml` nor `turbo.json` exists;
  `apps/web` is still a standalone pnpm project.

**Playwright shipped and is no longer on this list.** 21 spec files live under
`tests/e2e/` and two CI jobs run them — `playwright` against `pnpm dev` and
`playwright-production` against a real `next build` + `next start`
(`.github/workflows/e2e-ci.yml`). `pnpm e2e` runs them locally. The unit suite
is separate: `node --test` over `tests/unit/`, invoked by `pnpm test:unit`, and
it needs Node 22.6+ for the runtime's built-in TypeScript stripping.

See `docs/WEB_ARCHITECTURE.md` at the repo root for the broader web
migration plan.
