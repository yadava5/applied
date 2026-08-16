/**
 * The window act's tempo — every duration the choreography owns, in one
 * place, because the beats only read correctly as a SEQUENCE:
 *
 *   camera pans (700ms, LandingBoard's transition) →
 *   receipt strip announces the verdict (the Reveal at the frame's foot) →
 *   the breath: the announcement gets read →
 *   the row travels, at `VERDICT_TRAVEL` →
 *   the row lands →
 *   the pane opens on the mail that explains it (beat 2's seed, which now
 *   waits out the travel — see MarketingBoard).
 *
 * The order is the product's honesty: the verdict registers BEFORE the row
 * moves, and the pane never narrates a row that has not arrived. Measured on
 * the previous cut: seeding on the STATUS value docked the pane ~1.4s before
 * the row it names entered the frame, so the scene's caption was false for
 * the first ~600ms of the scene. Reduced motion collapses every number here
 * to an immediate, composed state.
 */

/**
 * Seconds the moved row glides between stage groups (PipelineBoard's `travel`
 * prop). The board's own 220ms is a tool's tempo — right for a user who just
 * dragged the row, unreadable as a first demonstration: the visitor does not
 * know which row will move, so the move itself has to be slow enough to
 * follow after the strip has said what to watch.
 */
export const VERDICT_TRAVEL = { duration: 1.4 } as const;

/**
 * Milliseconds between the act entering beat 1 and the row being committed:
 * the camera's 700ms pan plus time to read the receipt strip's announcement.
 * The gesture-attribution window (`OPEN_GESTURE_MS`) reasons against this
 * number — it must stay far above 400ms, and it does.
 */
export const VERDICT_BREATH_MS = 1800;

/** Milliseconds of settle after the glide before the pane may dock — the
 *  layout animation's tail, so the pane opens on a row at rest. */
export const VERDICT_SETTLE_MS = 200;
