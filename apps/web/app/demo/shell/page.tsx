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
 *   - `?session=1` mounts the SIGNED-IN session edge on the board's header
 *     row in place of that identity block's pill — `signedIn` on and
 *     `trailing` unset, the exact pair `app/(app)/dashboard/page.tsx` passes
 *     to `SyncBar`. Third harness knob, same reasoning as `?review=N`, and
 *     the case it was written for is that sentence word for word: sign-out on
 *     the board route is a user-facing control that renders on no other
 *     testable surface, because this twin deliberately renders
 *     `DemoFixturePill` exactly where the real page renders its session edge.
 *     So when #172 folded that control out of the row and into the row's `⋯`
 *     menu — to stop a ~97px button wrapping the row to two lines at 1024 and
 *     taking the height out of the worklist — the change landed on a shape no
 *     gate in this repo could see. `tests/e2e/session-edge.spec.ts` drives
 *     this param; nothing links to it.
 *
 *     It swaps ONE other thing, and has to: the row's recency slot, which on
 *     the simulated transport carries the frame "simulated account · nothing
 *     is read" instead of the live row's `LastSynced`. That frame lays out
 *     69px wider than the phrase it stands in for, and 69px is enough to wrap
 *     this row at 1024 with the session edge in either arrangement — so a
 *     twin that kept it reported a wrap the signed-in row does not have and
 *     could not measure the one thing the knob exists for. Under `?session=1`
 *     the slot renders the real `LastSynced` over the fixture Gmail state,
 *     which has never synced, so it reads "not synced yet" — true of a
 *     simulated account, and a state the signed-in page renders too. Nothing
 *     else about the twin changes, and neither /demo nor this route's own
 *     default is touched.
 *
 *     It does NOT hand an anonymous visitor a working sign-out: there is no
 *     session here, and a control whose only outcome is a bounce to /login is
 *     what the pill exists to prevent. The menu item renders with the real
 *     label, the real width and the real menu chrome — that geometry is the
 *     entire point — and leaves for /demo when picked, the pill's own
 *     destination. See the item in `SyncBar`; the guard is the simulated
 *     transport, which is already how this route keeps the auto-sync off.
 *     The rail and TopBar stay in demo dress, which costs the measurement
 *     nothing: on the board route at `lg`+ TopBar yields to this row
 *     entirely, so the row IS the session edge at both widths under test.
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
  searchParams: Promise<{
    pipeline?: string;
    review?: string;
    queue?: string;
    session?: string;
  }>;
}) {
  const { pipeline, review, queue, session } = await searchParams;
  const needsReview = Math.min(99, Math.max(0, Number.parseInt(review ?? "", 10) || 0));
  // `after` for anything that is not literally "before": the default matches
  // the live account (the alerts pref is off unless the user turns it on) and
  // is the placement the escaped-`sr-only` defect needed.
  const reviewSlot: DemoReviewSlot = queue === "before" ? "before" : "after";
  // Literal "1" only, the same shape as the knobs above: anything else leaves
  // the twin in its honest default, so a stray `?session=` in a shared link
  // cannot quietly put a sign-out in front of an anonymous visitor.
  const sessionEdge = session === "1";
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
        sessionEdge={sessionEdge}
      />

    </AppShellFrame>
  );
}
