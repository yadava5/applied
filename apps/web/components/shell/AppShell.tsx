import type { ReactNode } from "react";

import { loadRailData } from "@/lib/shell/rail";
import { AppShellFrame } from "./AppShellFrame";

type AppShellProps = {
  children: ReactNode;
  userEmail: string | null;
};

/**
 * Protected shell used under `app/(app)/` (and by the signed-in branch of
 * `/import`): live data around the shared frame. The geometry itself —
 * viewport lock, the one scroll pane, the flow/locked page contract — lives
 * in `AppShellFrame`, which `/demo/shell` also mounts over fixtures so the
 * lock stays testable without a session.
 *
 * This is an async Server Component: it assembles the rail's data (the Gmail
 * connection state the footer shows) via `loadRailData()` — a never-throwing
 * backend read that degrades to an honest fallback — and hands the result to
 * the client `Sidebar` as serializable props. The auth/session reads
 * underneath are request-memoized, so the shell shares them with the page it
 * wraps. `TopBar` is a Client Component because sign-out calls into
 * supabase-js in the browser.
 */
export async function AppShell({ children, userEmail }: AppShellProps) {
  const rail = await loadRailData();

  return (
    <AppShellFrame rail={rail} userEmail={userEmail}>
      {children}
    </AppShellFrame>
  );
}
