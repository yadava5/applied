import { cookies } from "next/headers";
import type { Metadata } from "next";

import { type DemoReviewSlot } from "@/components/demo/DemoDashboard";
import { DemoShell } from "@/components/demo/DemoShell";
import { DEMO_AMBIENT_COOKIE, parseDemoAmbientPref } from "@/lib/demo/ambientPref";
import { DEMO_NOTIFICATIONS_COOKIE, parseDemoNotificationPrefs } from "@/lib/demo/notificationPrefs";

export const metadata: Metadata = {
  title: "Live demo — the app shell",
  description:
    "The signed-in Applied shell — sidebar rail, viewport lock, worklist — on fixture data. No inbox is read.",
  // A harness first, a showcase second: /demo is the front door — and since
  // the consolidation it renders this same tree (`DemoShell`), knobs aside.
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
 * LOCKED variant, over the same in-memory fixture store as /demo. Since the
 * consolidation the mount itself lives in `DemoShell`, which /demo renders
 * too: one tree for the front door and this harness, so what the specs below
 * measure here cannot drift from what a visitor is actually shown there.
 * This route keeps the KNOBS — reviewable states nothing links to — and the
 * `robots: noindex` that goes with being an instrument.
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
 *   - `?session=1` mounts the SIGNED-IN session edge on the board's header
 *     row in place of that identity block's pill — `signedIn` on and
 *     `trailing` unset, the exact pair `app/(app)/(protected)/dashboard/page.tsx` passes
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
  // Exact-match both values, like every knob here, and fall through to
  // UNDEFINED rather than to "after": absent, the slot comes from the
  // preference the Settings twin wrote (#216), whose own default is "after" —
  // the live account's placement (the alerts pref is off unless turned on)
  // and the one the escaped-`sr-only` defect needed. A knob that silently
  // shadowed the preference would make the pref→slot e2e untestable here.
  const reviewSlot: DemoReviewSlot | undefined =
    queue === "before" ? "before" : queue === "after" ? "after" : undefined;
  const jar = await cookies();
  const notifications = parseDemoNotificationPrefs(jar.get(DEMO_NOTIFICATIONS_COOKIE)?.value);
  // The rail's ambient-mail pref, from the cookie the demo Settings toggle
  // writes — read server-side exactly as the (app) layout reads the real
  // metadata, so the twin's rail is the signed-in rail's honest stand-in.
  const ambient = parseDemoAmbientPref(jar.get(DEMO_AMBIENT_COOKIE)?.value);
  // Literal "1" only, the same shape as the knobs above: anything else leaves
  // the twin in its honest default, so a stray `?session=` in a shared link
  // cannot quietly put a sign-out in front of an anonymous visitor.
  const sessionEdge = session === "1";

  // The rail fixture and the "Sam Fixture" identity live in `DemoShell` now,
  // beside the one mount both routes share.
  return (
    <DemoShell
      pipeline={pipeline === "early" ? "early" : "seed"}
      needsReview={needsReview}
      notifications={notifications}
      reviewSlot={reviewSlot}
      sessionEdge={sessionEdge}
      ambient={ambient}
    />
  );
}
