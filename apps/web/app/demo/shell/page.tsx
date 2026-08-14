import type { Metadata } from "next";

import { DemoDashboard, type DemoReviewSlot } from "@/components/demo/DemoDashboard";
import { AppShellFrame } from "@/components/shell/AppShellFrame";
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
 * only behind a session guard that no CI environment can satisfy — a check
 * that could not fail. That guard is now `requireSession` in
 * `tests/e2e/session.ts` and it is loud rather than silent (#188), but loud
 * is not the same as running: the 13 tests behind it still do not execute
 * anywhere, which is exactly why the geometry lives on this route instead.
 * The lock lives entirely in components this
 * page mounts verbatim (`AppShellFrame`'s `h-dvh overflow-hidden` frame and
 * <main>, `LOCKED_PAGE_CLASS` on the twin's root, `PipelineBoard
 * variant="locked"`), so the executing assertions in
 * `tests/e2e/shell.spec.ts` measure the same primitives the signed-in
 * dashboard renders, not a copy of their class names.
 *
 * What is fixture here and what is real:
 *   - real: every layout component, the board's full interactivity (drag,
 *     detail sheet, stage filter), the pulse band across the board, the
 *     theme.
 *   - fixture: the rows, the rail's Gmail state, and the identity block.
 *   - the pulse's `needsReview` is 0 by default, same reasoning as /demo: the
 *     classifier signal's non-zero branch deep-links to an auth-gated route
 *     that would dead-end an anonymous visitor (`DemoDashboard` passes it).
 *     `?review=N` (clamped 0–99) overrides it — a harness knob, declared as
 *     such, because that branch is a user-facing control that renders on no
 *     other testable surface, which is exactly how a clipped link could ship
 *     with every gate green. Tests drive the param; nothing links to it.
 *   - `?review=N` also mounts N held verdicts as a REAL `ReviewQueue` in the
 *     board's slot, and `?queue=before|after` (default `after`) says which of
 *     `PipelineBoard`'s two slots it lands in. Both knobs, same reasoning, and
 *     this pair is why they were added: the twin used to render a strict
 *     SUBSET of the signed-in page — no queue at all — so the document-lock
 *     assertions in `tests/e2e/shell.spec.ts` were correct, executing, and
 *     measuring a tree the defect could not be in. `ReviewQueue` positions
 *     nothing of its own; in the `after` slot, below every row, its `sr-only`
 *     labels resolved against the initial containing block, planted a box at
 *     document scale that no ancestor's `overflow` could clip, and the whole
 *     signed-in dashboard scrolled (#149). The live page picks the slot by a
 *     user preference — "Needs review alerts" on puts the queue above the
 *     rows, off leaves it below — so both are reachable here.
 *
 * `?pipeline=early` renders the same locked twin over the early-search
 * projection, exactly as /demo does — the measured production shape (every
 * row at `applied`, no deadlines, roles missing at the real rate). The
 * geometry claims have to hold when every distribution is a single spike,
 * because that is the real account's normal state, not an edge case.
 */
export default async function DemoShellPage({
  searchParams,
}: {
  searchParams: Promise<{ pipeline?: string; review?: string; queue?: string }>;
}) {
  const { pipeline, review, queue } = await searchParams;
  const needsReview = Math.min(99, Math.max(0, Number.parseInt(review ?? "", 10) || 0));
  // `after` for anything that is not literally "before": the default matches
  // the live account (the alerts pref is off unless the user turns it on) and
  // is the placement the escaped-`sr-only` defect needed.
  const reviewSlot: DemoReviewSlot = queue === "before" ? "before" : "after";
  const rail: RailData = {
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
    // The fixture gets a NAME as well as an email — the real rail shows the
    // display name now, and a twin that still printed the address would drift
    // from the surface it stands in for (the bug class this route exists to
    // prevent). Same persona as /demo/settings' profile: one fixture identity.
    <AppShellFrame rail={rail} userEmail="demo@applied.example" userName="Sam Fixture" demo>
      <DemoDashboard
        variant="locked"
        pipeline={pipeline === "early" ? "early" : "seed"}
        needsReview={needsReview}
        reviewSlot={reviewSlot}
      />

    </AppShellFrame>
  );
}
