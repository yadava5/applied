import type { Metadata } from "next";

import { DemoDashboard } from "@/components/demo/DemoDashboard";
import { AppShellFrame } from "@/components/shell/AppShellFrame";
import { todayISO } from "@/lib/dashboard/age";
import { summarize, toPulseRow } from "@/lib/dashboard/summary";
import { demoApplicationsAsApi } from "@/lib/demo/asApplications";
import type { RailData } from "@/lib/shell/rail";

export const metadata: Metadata = {
  title: "Live demo — the app shell",
  description:
    "The signed-in Applied shell — sidebar rail, viewport lock, worklist — on fixture data. No inbox is read.",
  // A harness first, a showcase second: /demo is the front door.
  robots: { index: false },
};

/**
 * Rendered per request, for the same reason as /demo: the fixtures are dated
 * RELATIVE to today, and a statically prerendered page would bake the build
 * day's dates into HTML that hydrates against the viewer's day (React #418).
 */
export const dynamic = "force-dynamic";

/**
 * The signed-in shell, auth-free: the REAL `AppShellFrame` — the same
 * component the protected layout renders — around the demo dashboard in its
 * LOCKED variant, over the same in-memory fixture store as /demo.
 *
 * This route exists because the shell's headline geometry claim ("the
 * document never scrolls; the worklist is the one scroll pane") was asserted
 * only behind `reachDashboardOrSkip`, which no CI environment can satisfy —
 * a check that could not fail. The lock lives entirely in components this
 * page mounts verbatim (`AppShellFrame`'s `h-dvh overflow-hidden` frame and
 * <main>, `LOCKED_PAGE_CLASS` on the twin's root, `PipelineBoard
 * variant="locked"`), so the executing assertions in
 * `tests/e2e/shell.spec.ts` measure the same primitives the signed-in
 * dashboard renders, not a copy of their class names.
 *
 * What is fixture here and what is real:
 *   - real: every layout component, the board's full interactivity (drag,
 *     detail sheet, stage filter), the pulse in the rail, the theme.
 *   - fixture: the rows, the rail snapshot below, and the identity block.
 *     The rail snapshot is computed once per request from the pristine
 *     fixtures; unlike the live shell it does not re-derive after board
 *     mutations, because the transports here commit to component state
 *     rather than to a backend a `router.refresh()` could re-read.
 *   - `needsReview: 0`, same reasoning as /demo: the classifier signal's
 *     non-zero branch deep-links to an auth-gated route that would dead-end
 *     an anonymous visitor.
 */
export default function DemoShellPage() {
  const apps = demoApplicationsAsApi(todayISO());
  const rail: RailData = {
    pipeline: {
      summary: summarize(apps),
      needsReview: 0,
      pulseRows: apps.map(toPulseRow),
    },
    gmail: {
      connected: true,
      email: null,
      lastSyncAt: null,
      hasCursor: true,
      syncStatus: null,
      syncError: null,
    },
  };

  return (
    <AppShellFrame rail={rail} userEmail="demo@applied.example" demo>
      <DemoDashboard variant="locked" />
    </AppShellFrame>
  );
}
