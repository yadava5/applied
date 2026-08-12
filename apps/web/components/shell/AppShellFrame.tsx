import type { ReactNode } from "react";

import type { RailData } from "@/lib/shell/rail";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

type AppShellFrameProps = {
  children: ReactNode;
  rail: RailData;
  userEmail: string | null;
  /** Fixture mode (/demo/shell): the top bar trades sign-out for a demo pill. */
  demo?: boolean;
};

/**
 * The shell's GEOMETRY, separated from its data so it can be mounted over
 * fixtures. `AppShell` (the signed-in wrapper) resolves live rail data and
 * renders this; `/demo/shell` renders the same frame over the demo fixtures,
 * which is what makes the viewport-lock assertions below executable without a
 * Supabase session (`tests/e2e/shell.spec.ts`). One frame, so the fixture can
 * never drift from the thing it stands in for.
 *
 * The frame is viewport-locked: exactly one screen tall (`h-dvh`), chrome
 * (rail + top bar) that never moves, and <main> as the one scroll pane. The
 * document itself never scrolls — the app reads as an instrument, not a page.
 * Two geometries live inside that pane:
 *
 *   - a FLOW page (settings, inbox, import) renders normal top-to-bottom
 *     content; the wrapper grows with it and the pane scrolls.
 *   - a LOCKED page (the dashboard) declares `LOCKED_PAGE_CLASS`
 *     (`./geometry`) on its root and scrolls a region of its own, so the page
 *     always fits the screen and only the worklist moves.
 *
 * The wrapper cannot serve both with one static minimum — MEASURED, not
 * assumed: with `min-height: auto` its content-based minimum swallows the
 * locked page's whole worklist (993px in a 744px pane; the child section's
 * own `min-h-0` does not reduce a parent's content-derived minimum), so the
 * pane scrolled the dashboard as one block; with an unconditional `min-h-0`
 * a flow page's content would overflow a pane-height wrapper instead of
 * growing it. So the minimum is conditional on what the page declared:
 * `lg:has-[.page-locked]:min-h-0` collapses it exactly when a locked page is
 * inside. The executing geometry specs (shell.spec.ts, via /demo/shell) hold
 * this: document locked, <main> still, worklist overflowing.
 */
export function AppShellFrame({ children, rail, userEmail, demo = false }: AppShellFrameProps) {
  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <Sidebar rail={rail} userEmail={userEmail} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar userEmail={userEmail} demo={demo} />
        {/* ONE page geometry for every authed surface: a shared centred column
            with a common left edge. The dashboard fills it; narrower pages
            (settings, inbox) cap their own measure inside it but start at the
            same x. `overflow-y-auto` here is NOT inert: the shell is h-dvh,
            so this pane is the scroll context the whole app shares. */}
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-5">
          <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col lg:has-[.page-locked]:min-h-0">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
