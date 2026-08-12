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
 * The frame is viewport-locked: exactly one screen tall (`h-dvh`), chrome
 * (rail + top bar) that never moves, and <main> as the one scroll pane. The
 * document itself never scrolls — the app reads as an instrument, not a page.
 * Two geometries live inside that pane:
 *
 *   - a FLOW page (settings, inbox, import) renders normal top-to-bottom
 *     content; the wrapper grows with it and the pane scrolls.
 *   - a LOCKED page (the dashboard) declares `lg:min-h-0 lg:flex-1` on its
 *     root and scrolls a region of its own, so the page always fits the
 *     screen and only the worklist moves. The wrapper is a flex column with
 *     `flex-1` (no `min-h-0`), which is what makes both work: it fills the
 *     pane for the locked page and still grows for the flow pages.
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
    <div className="flex h-dvh w-full overflow-hidden">
      <Sidebar rail={rail} userEmail={userEmail} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar userEmail={userEmail} />
        {/* ONE page geometry for every authed surface: a shared centred column
            with a common left edge. The dashboard fills it; narrower pages
            (settings, inbox) cap their own measure inside it but start at the
            same x. `overflow-y-auto` here is NOT inert anymore: the shell is
            h-dvh, so this pane is the scroll context the whole app shares. */}
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-5">
          <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col">{children}</div>
        </main>
      </div>
    </div>
  );
}
