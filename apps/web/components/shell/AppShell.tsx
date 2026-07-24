import type { ReactNode } from "react";

import { loadRailData } from "@/lib/shell/rail";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

type AppShellProps = {
  children: ReactNode;
  userEmail: string | null;
};

/**
 * Protected shell layout used under `app/(app)/` (and by the signed-in branch
 * of `/import`). Renders the persistent sidebar rail and a top bar (mobile
 * nav + sign-out) around the page content.
 *
 * This is an async Server Component: it assembles the rail's snapshot data
 * (pipeline summary + Gmail connection) via `loadRailData()` — two parallel,
 * never-throwing backend reads that degrade to honest fallbacks — and hands
 * the result to the client `Sidebar` as serializable props. The auth/session
 * reads underneath are request-memoized, so the shell shares them with the
 * page it wraps. `TopBar` is a Client Component because sign-out calls into
 * supabase-js in the browser.
 */
export async function AppShell({ children, userEmail }: AppShellProps) {
  const rail = await loadRailData();

  return (
    <div className="flex min-h-screen w-full">
      <Sidebar rail={rail} userEmail={userEmail} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar userEmail={userEmail} />
        <main className="flex-1 overflow-y-auto px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
