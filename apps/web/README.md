# JobTracker web (`apps/web/`)

Next.js 16 (App Router) frontend for the cloud deployment of JobTracker.
Scaffolded in issue #24 (C9). This package is intentionally **not** wired
into a pnpm workspace — treat it as a standalone app for now.

## Stack

- **Next.js 16** (App Router, Turbopack) + **React 19.2**
- **TypeScript** strict mode
- **Tailwind CSS 4**
- **Supabase Auth** via `@supabase/ssr` (SSR-safe cookie handling)
- **TanStack Query 5** (installed; real API client lands in C10)
- **zod** for runtime env validation
- **shadcn/ui** compatible (`components.json` in place, `Button` added)

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
| `SUPABASE_SERVICE_ROLE_KEY` | server, optional | admin-only tasks |

### Day-to-day scripts

```bash
pnpm dev          # next dev (Turbopack) on http://localhost:3000
pnpm build        # next build (Turbopack)
pnpm start        # serve the production build
pnpm typecheck    # tsc --noEmit
pnpm lint         # eslint (next defaults)
```

## Layout

```
apps/web/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx         # email+password form
│   │   ├── signup/page.tsx        # email+password form
│   │   └── callback/route.ts      # Supabase PKCE exchange
│   ├── (app)/
│   │   ├── layout.tsx             # protected shell (AppShell)
│   │   └── dashboard/page.tsx     # placeholder
│   ├── layout.tsx                 # root html + fonts
│   └── globals.css
├── components/
│   ├── shell/
│   │   ├── AppShell.tsx
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx             # includes sign-out
│   └── ui/button.tsx              # shadcn-compatible
├── lib/
│   ├── env.ts                     # zod-validated process.env
│   ├── utils.ts                   # cn() helper
│   └── supabase/
│       ├── client.ts              # browser client
│       ├── server.ts              # server client (async cookies())
│       └── middleware.ts          # updateSession() for proxy.ts
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

## Not yet in scope

- Real backend API client (comes in C10).
- Playwright E2E tests (separate issue).
- shadcn/ui kit beyond `Button`.
- Monorepo tooling (`pnpm-workspace.yaml`, `turbo.json`).

See `docs/WEB_ARCHITECTURE.md` at the repo root for the broader web
migration plan.
