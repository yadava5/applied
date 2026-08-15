/**
 * What the two notification preferences decide ON THE BOARD.
 *
 * `weekly` folds the this-week count into the header line; `reviewAlerts`
 * decides which of `PipelineBoard`'s two slots the needs-review queue lands
 * in. Both branches are real and visibly differ — and both had zero
 * executable coverage until #216, where
 * `grep "readNotificationPrefs\|reviewAlerts\|buildSubtitle" tests/` returned
 * nothing at all: `readNotificationPrefs` could have returned constants and
 * every suite would have stayed green.
 *
 * They live here, out of `app/(app)/(protected)/dashboard/page.tsx`, for exactly one
 * reason — a Server Component page cannot be imported by `node --test`, and
 * these two derivations are pure. The public twin
 * (`components/demo/DemoDashboard.tsx`) calls the SAME two functions, which
 * is what makes the twin's e2e a real gate on the signed-in page's wiring
 * rather than a test of a parallel implementation.
 *
 * Both imports below are type-only and therefore erased before Node ever
 * resolves them — the discipline `lib/dashboard/summary.ts` documents about
 * its own `@/` alias, and what keeps this module dependency-free.
 */
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";
import type { PipelineSummary } from "@/lib/dashboard/summary";

/** Which of `PipelineBoard`'s two slots the needs-review queue lands in. */
export type ReviewSlot = "before" | "after";

/**
 * "Needs-review alerts" ON means held mail INTERRUPTS the worklist (it renders
 * above the stage groups); OFF means it waits under them — the quiet-board
 * promise the Settings toggle's own copy makes.
 *
 * One function rather than a ternary at each call site, so the mapping is
 * asserted once and cannot drift between the signed-in board and the twin:
 * inverting it now fails `tests/e2e/settings.spec.ts` AND changes the real
 * page, which is the only way a demo-driven test can gate a session-gated
 * surface.
 */
export function reviewSlotFor(prefs: NotificationPrefs): ReviewSlot {
  return prefs.reviewAlerts ? "before" : "after";
}

/** The dashboard's one prose data line — its only rendering of the totals. The
 *  needs-review count is NOT here: the pulse's classifier signal owns it
 *  (with the deep link), so the number renders once. `weekly` folds the
 *  this-week count in — the pref's digest used to be its own banner line
 *  restating everything else this line already says.
 *
 *  A zero this-week count folds in NOTHING even with the pref on: "+0 this wk"
 *  is not news. That is why the two branches read identically on a quiet
 *  board, and it is a data condition rather than a defect (#216) — the tests
 *  drive a non-zero count on purpose, or they would pass for the wrong
 *  reason. */
export function buildSubtitle(summary: PipelineSummary, weekly: boolean): string {
  const thisWeek = weekly && summary.thisWeek > 0 ? ` · +${summary.thisWeek} this wk` : "";
  // "open", not "in motion": the pulse already calls these same rows open,
  // and an applied-and-waiting row is precisely the one NOT moving.
  return `${summary.total} filed${thisWeek} · ${summary.inMotion} open · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;
}
