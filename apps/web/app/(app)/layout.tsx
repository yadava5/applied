import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { readAmbientPref } from "@/lib/settings/ambient";
import { loadRailData } from "@/lib/shell/rail";
import { getCurrentUser, userDisplayName } from "@/lib/supabase/auth";

/**
 * Protected shell for every route under `app/(app)/`.
 *
 * The `proxy.ts` already redirects unauthenticated users away from these
 * paths. We re-check the user here (defence-in-depth) so that even if the
 * proxy matcher is ever misconfigured for a new protected route, rendering
 * will fall back to a redirect instead of leaking shell UI.
 *
 * `getCurrentUser()` is request-memoized (see `lib/supabase/auth`), so this
 * verified read is shared with the page rendered inside the shell rather than
 * costing a second Supabase Auth round-trip.
 */
export default async function ProtectedLayout({
  children,
}: {
  children: ReactNode;
}) {
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
   * failure degrades to `null` and the rail omits the chip), and the redirect
   * below still happens before any of it can reach the screen. A signed-out
   * request now issues one backend call whose answer is discarded — the proxy
   * redirects those before they arrive here, so it should be unreachable, and
   * it costs a user with no session nothing they can see.
   *
   * This does NOT unblock `children`: `AppShell` still awaits the rail before
   * returning the tree the page renders inside, so the page's own data still
   * starts after the rail's answer. Streaming the rail into a Suspense boundary
   * would fix that too, and it is the larger, separately-verified change.
   */
  const rail = loadRailData();
  const user = await getCurrentUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <AppShell
      rail={rail}
      userEmail={user.email ?? null}
      userName={userDisplayName(user)}
      // Rides on the user the layout already verified — no extra read. The
      // Appearance toggle's router.refresh() re-runs this layout, which is
      // how a saved change reaches the rail server-side.
      ambient={readAmbientPref((user.user_metadata ?? {}) as Record<string, unknown>)}
    >
      {children}
    </AppShell>
  );
}
