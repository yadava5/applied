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
export function buildSubtitle(
  summary: PipelineSummary,
  weekly: boolean,
): string {
  const thisWeek =
    weekly && summary.thisWeek > 0 ? ` · +${summary.thisWeek} this wk` : "";
  // "open", not "in motion": the pulse already calls these same rows open,
  // and an applied-and-waiting row is precisely the one NOT moving.
  return `${summary.total} filed${thisWeek} · ${summary.inMotion} open · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;
}

/**
 * The sync row's subtitle for an EMPTY board.
 *
 * A separate builder from `buildSubtitle`, because an empty board's line
 * answers a different question. `buildSubtitle` reports totals; here the totals
 * are all zero and the useful thing to say is WHY — is mail connected, has a
 * scan run, and is anything waiting in the review queue.
 *
 * IT LIVES HERE FOR THE REASON THE FILE HEADER GIVES. It was built inline in
 * `app/(app)/(protected)/dashboard/page.tsx`, which a Server Component test
 * cannot import, so nothing gated it — and the demo twin, which cannot see it
 * either, fell back to calling `buildSubtitle` with the FULL fixture summary.
 * The result was `/demo/shell?empty=1` rendering
 *
 *     17 filed · 14 open · 0 offers
 *
 * directly above "nothing filed yet", in the one harness state that exists to
 * model an empty board. That knob is also what the viewport-lock specs measure,
 * so the twin was contradicting itself on the surface it was meant to stand in
 * for — the exact drift this module was created to prevent, in a corner it had
 * not reached yet.
 *
 * `needsReview` is folded in rather than left to the pulse, and that is not a
 * duplicate of the rule `buildSubtitle` follows: on an empty board there is no
 * board for the pulse to sit on, so this line is the only place the held count
 * can be said at all. Zero folds in nothing — "· 0 need review" is not news.
 */
export function emptySubtitle(input: {
  /** What we know about the mailbox. `unknown` is a failed probe, not "no". */
  gmailState: "connected" | "disconnected" | "unknown";
  /** A sync has completed successfully at least once. */
  scanCompleted: boolean;
  /** How many messages are held for classification. */
  needsReview: number;
}): string {
  const { gmailState, scanCompleted, needsReview } = input;
  const reviewNote =
    needsReview > 0
      ? ` · ${needsReview} ${needsReview === 1 ? "needs" : "need"} review`
      : "";

  if (gmailState === "connected") {
    const detail = scanCompleted
      ? "no applications detected yet"
      : "no applications filed yet";
    return `connected · ${detail}${reviewNote}`;
  }
  // A failed probe is NOT evidence that nothing is connected, and saying
  // "nothing tracked yet" about it would state a verdict we do not have.
  if (gmailState === "unknown")
    return `0 filed · mail connection unknown${reviewNote}`;
  return `0 filed · nothing tracked yet${reviewNote}`;
}
