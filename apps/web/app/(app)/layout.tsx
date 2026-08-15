import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { readAmbientPref } from "@/lib/settings/ambient";
import { loadRailData } from "@/lib/shell/rail";
import { getCurrentUser, userDisplayName } from "@/lib/supabase/auth";

/**
 * THE app shell, mounted exactly once for every route that can wear it.
 *
 * WHY THIS LAYOUT OWNS THE SHELL, AND NOTHING ELSE MAY.
 *
 * React preserves a component instance across a client navigation only when it
 * stays at the same position in the same tree. A layout is that guarantee; a
 * shell rendered INSIDE a page is not. `/import` and `/privacy` used to live
 * outside this group and each mounted its own `<AppShell>` from within its
 * page, so navigating /settings → /import tore the whole shell down and built a
 * new one: the rail, the logo, the footer and the ambient canvas all repainted
 * from nothing, mid-session, on a soft navigation.
 *
 * Measured on production before the fix (signed in, clicking rail links, one
 * document — `window.__probe` survived every hop, so none of this was a page
 * load):
 *
 *     /dashboard → /inbox → /settings   `aside canvas` data-probe SURVIVED
 *     /dashboard → /import              `aside canvas` data-probe GONE
 *
 * So the two public-but-shell-wearing routes moved in here, and the shell moved
 * out of their pages. Route groups contribute no URL segment, so `/import` is
 * still `/import` and `/privacy` is still `/privacy`.
 *
 * WHY THE SHELL IS CONDITIONAL. Both of those routes must stay reachable
 * SIGNED OUT at the same URL — `/import` is the public "no upload, no sign-in"
 * surface (the one `demoNavHrefs` entry that maps to itself, and the landing's
 * CTA), `/privacy` is the document Google's OAuth reviewer fetches anonymously.
 * With no user there is no shell to render, so `children` pass through bare and
 * each page renders its own standalone public form, exactly as before.
 *
 * WHY THE REDIRECT LEFT. It moved DOWN, to `(protected)/layout.tsx`, because a
 * layout cannot see the pathname and this one now covers public routes too.
 * The defence-in-depth property gets stronger rather than weaker: if the proxy
 * matcher were ever misconfigured for a protected route, this layout sees no
 * user, renders nothing of the shell at all, and the protected layout below
 * bounces — so no chrome can leak ahead of the redirect. `tests/unit/
 * protected-routes.test.mjs` holds both halves of the arrangement: every
 * directory under `(protected)/` is in `PROTECTED_PREFIXES`, and every other
 * directory under `(app)/` is on an explicit public allowlist.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  /**
   * Started here, awaited inside `AppShell` — the same shape the dashboard uses
   * for its review queue, and for the same reason. These are TWO INDEPENDENT
   * NETWORK ROUND-TRIPS that were running strictly in series: this layout
   * awaited `getCurrentUser()` (which `@supabase/ssr` verifies against the
   * Supabase Auth server — a real request, not a cookie decode), and only then
   * did `AppShell` await `loadRailData()` (an HTTP call to the FastAPI backend
   * for the Gmail connection state). Nothing forced that order. The rail's
   * probe reaches the backend with the access token from
   * `getAccessToken()` → `getCurrentSession()`, which decodes the cookie and
   * makes no network call at all, so it never needed the verified user.
   *
   * Overlapping them is safe on the auth side as well as the timing side: the
   * probe is scoped by the caller's own JWT, `loadRailData` never throws (every
   * failure degrades to `null` and the rail omits the chip), and on the
   * signed-out branch below the promise is simply never awaited. That branch is
   * now genuinely reachable (it is how public `/import` renders), and it costs
   * nothing: with no session the probe resolves `unauthenticated` from the
   * cookie jar without touching the network, and because it cannot reject it
   * can never become an unhandled rejection — the same contract `/import`'s own
   * floated `getGmailStatus()` already relied on.
   *
   * This does NOT unblock `children`: `AppShell` still awaits the rail before
   * returning the tree the page renders inside, so the page's own data still
   * starts after the rail's answer. Streaming the rail into a Suspense boundary
   * would fix that too, and it is the larger, separately-verified change.
   */
  const rail = loadRailData();
  const user = await getCurrentUser();

  // Signed out: the public routes in this group render their own standalone
  // page, and a protected one is bounced by the layout below before anything
  // of theirs renders. Either way there is no chrome to wrap them in.
  if (!user) return <>{children}</>;

  return (
    <AppShell
      rail={rail}
      userEmail={user.email ?? null}
      userName={userDisplayName(user)}
      // Rides on the user the layout already verified — no extra read. The
      // Appearance toggle's router.refresh() re-runs this layout, which is
      // how a saved change reaches the rail server-side.
      //
      // `/import` used to miss this entirely: its in-page `<AppShell>` passed
      // no `ambient`, so the prop defaulted to `true` and an account that had
      // switched the ambient field OFF still got the canvas on that one route.
      // One shell, one source for the preference, so that cannot recur.
      ambient={readAmbientPref((user.user_metadata ?? {}) as Record<string, unknown>)}
    >
      {children}
    </AppShell>
  );
}
