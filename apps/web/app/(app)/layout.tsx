import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { createClient } from "@/lib/supabase/server";

/**
 * Protected shell for every route under `app/(app)/`.
 *
 * The `proxy.ts` already redirects unauthenticated users away from these
 * paths. We re-check the user here (defence-in-depth) so that even if the
 * proxy matcher is ever misconfigured for a new protected route, rendering
 * will fall back to a redirect instead of leaking shell UI.
 */
export default async function ProtectedLayout({
  children,
}: {
  children: ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  return <AppShell userEmail={user.email ?? null}>{children}</AppShell>;
}
