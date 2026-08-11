/**
 * Which URL prefixes require an authenticated Supabase session.
 *
 * Lives in its own module, dependency-free (no `next/server`, no `@supabase/ssr`,
 * no `@/` alias), for one reason: `tests/unit/` can then load it under Node's
 * type stripping and check it against the filesystem. Inside `middleware.ts`
 * this list could not be executed by a test at all, and it drifted — `/inbox`
 * and `/settings` were never added for as long as they have existed.
 *
 * The drift was not harmless. Both routes still redirected, but from the
 * protected layout's bare `redirect("/login")` rather than from the proxy, and
 * that path carries no `?redirect=` — so signing in after following a Settings
 * link landed you on the dashboard, while the identical journey through
 * `/dashboard` returned you where you meant to go. Measured against production
 * before the fix:
 *
 *     /dashboard  →  307  /login?redirect=%2Fdashboard
 *     /inbox      →  307  /login
 *     /settings   →  307  /login
 *
 * In the App Router the `(app)` and `(auth)` route groups are NOT part of the
 * URL, so gating has to happen on the literal prefix. Extend this list rather
 * than the negative matcher in `proxy.ts` when adding a protected page: the
 * proxy keeps running on every app route and only *redirects* for known ones.
 */
export const PROTECTED_PREFIXES: readonly string[] = ["/dashboard", "/inbox", "/settings"];

/** True when `pathname` is a protected page or lives beneath one. */
export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
