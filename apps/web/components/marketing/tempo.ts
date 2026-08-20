/**
 * The board's marketing tempo — what little of it is a duration.
 *
 * This file used to carry the scrubbed window act's marks (`ACT_MARKS`,
 * `ACT_WINDOW`, `ACT_DEADBAND`, `RECEIPT_FADE`): shares of a pinned runway
 * that made every beat of the offer choreography a function of scroll
 * position. That act was replaced by the workday oner (the owner's 01a pick,
 * 2026-08-20 — see `WindowAct`), which plays on the director's own pausable
 * clock, so the marks retired with the choreography they paced. Git history
 * holds the full argument; nothing should re-derive those constants without
 * re-reading it.
 *
 * What remains is read by `MarketingBoard`'s CHOREOGRAPHED path. That path
 * is DORMANT as of the oner: no mount passes `verdict`/`docked` any more
 * (every live mount is a resting board). It is kept, with these constants,
 * because it is the working implementation of the offer beat should the
 * owner recall it — retire the path and this file goes with it. Recalling
 * it is also what re-arms the seeded-open race its CI gate guarded
 * (`.github/workflows/landing-b-race.yml`, retired 2026-08-20, last at
 * 9e1675c): restore that workflow — sensitivity arithmetic and all — in the
 * same change that passes `verdict` to a mount again.
 */

/**
 * Seconds the moved row glides between stage groups (`PipelineBoard`'s
 * `travel` prop). The board's own 220ms is a tool's tempo — right for a user
 * who just dragged the row, unreadable as a first demonstration: the visitor
 * does not know which row will move, so the move itself has to be slow enough
 * to follow after the strip has said what to watch.
 */
export const VERDICT_TRAVEL = { duration: 1.4 } as const;

/** Milliseconds of settle after the glide before the pane may dock — the
 *  layout animation's tail, so the pane opens on a row at rest. */
export const VERDICT_SETTLE_MS = 200;
