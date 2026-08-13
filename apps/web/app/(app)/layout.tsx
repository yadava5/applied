import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
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
  const user = await getCurrentUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <AppShell userEmail={user.email ?? null} userName={userDisplayName(user)}>
      {children}
    </AppShell>
  );
}
