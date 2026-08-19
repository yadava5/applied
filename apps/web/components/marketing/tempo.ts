/**
 * The window act's tempo — and the reason almost nothing here is a duration.
 *
 * The act used to be a fixed ~3s sequence started by an IntersectionObserver
 * sentinel: 700ms pan, an 1800ms breath, a 1400ms travel, a 200ms settle. It
 * then ran INDEPENDENTLY OF THE SCROLL. Measured on the deployed preview
 * (docs/landing-b-motion-diagnosis.md): the caption advanced three seconds
 * after the reader had stopped scrolling, and the pinned runway gave each
 * scene ~574px — 0.3–0.6s of dwell at trackpad speed, against a 3s
 * choreography. Two passes retimed those durations and both made it worse,
 * because a longer timer inside a short runway is strictly further from the
 * reader's hand.
 *
 * So the beats are POSITIONS now, not moments. `WindowAct` reads one
 * `scrollYProgress` across the pinned runway and every mark below is a share
 * of it: the camera's pan and the receipt's rise are interpolated straight
 * off that value, and the two state changes — the row's commit and the
 * pane's dock — are latched at a mark and UNLATCHED on the way back up. The
 * act therefore cannot be outrun, cannot finish while the reader is looking
 * elsewhere, and cannot be left half-played: whatever the reader can see is
 * whatever their scroll position defines.
 *
 * The order the marks encode is the product's honesty, unchanged: the camera
 * reaches the board's foot BEFORE the receipt announces, the receipt
 * announces BEFORE the row moves, and the pane never opens on a row that has
 * not arrived.
 */

/**
 * The act's marks, as shares of the pinned runway (`scrollYProgress` over the
 * act's section, `start start` → `end end`, which is within ~33px of the
 * sticky window's own pin and release at every viewport height).
 *
 * The runway is `lg:h-[400vh]`, so the scrubbed distance is 3× the viewport:
 * 2847px at 949 tall, 2304px at 768. What each mark buys, at those two
 * heights:
 *
 *   0.00–0.20  the board at rest, captioned          569px / 461px
 *   0.20–0.38  the camera pans to the foot, scrubbed  512px / 415px
 *   0.30–0.44  the receipt rises into the frame       399px / 323px
 *   0.44–0.54  announced, and the row has NOT moved   285px / 230px
 *   0.54       the row commits to `offered`
 *   0.54–0.72  it travels and comes to rest           512px / 415px
 *   0.72       the pane docks on it; caption 3        797px / 645px to the end
 *
 * The old arithmetic gave three scenes 574px EACH and spent most of it on
 * nothing at all. These numbers are larger, but the comparison is not like
 * for like: every pixel here produces a visible change, which is the thing
 * the previous runway did not have and the reason it read as dead scroll.
 */
export const ACT_MARKS = {
  /** Caption 2, and the camera leaves the board's head. */
  scene: 0.2,
  /** The camera's pan, scrubbed: head → foot. Finishes well before the row
   *  moves, so the verdict lands in a frame that has already settled. */
  pan: [0.2, 0.38],
  /** The receipt strip's rise into the frame's foot, scrubbed. It overlaps
   *  the pan's tail on purpose — the announcement arrives as the camera
   *  arrives — and clears it by the breath below. */
  receipt: [0.3, 0.44],
  /**
   * The row commits to `offered`. The 0.10 of runway between the receipt
   * landing and this mark is the BREATH — what `VERDICT_BREATH_MS`'s 1800ms
   * used to be, now measured in the reader's own scrolling: 285px at 949
   * tall. A reader crossing it at 400px/s gets 713ms of "announced, not yet
   * moved"; one at 1500px/s gets 190ms and does not want more, because the
   * next thing they will see is the state their position defines.
   */
  verdict: 0.54,
  /** The detail pane docks on the moved row, and the caption becomes "the row
   *  opens on the mail that moved it". The seed still waits out whatever is
   *  left of the travel (`MarketingBoard`'s `landedAtRef`), so a reader who
   *  crosses both marks in one flick never sees the pane open on a row that
   *  is still in the air. */
  docked: 0.72,
} as const;

/**
 * Half-width of the deadband around every latched mark, as a share of the
 * runway — 142px at a 949-tall viewport, 115px at 768.
 *
 * Board state is a function of position, so it has to be a function that does
 * not chatter: scroll anchoring, trackpad momentum settling and a resize all
 * move `scrollYProgress` by a few pixels' worth, and each toggle would
 * re-target a layout animation. Tens of pixels is the jitter this has to
 * clear; 142 clears it with room.
 *
 * It is deliberately NOT wide enough to outlast the travel (1.4s ≈ 560px at a
 * slow 400px/s). A reader who scrolls a screen-tenth back up SHOULD see the
 * row go home — that is the reversibility the act was rebuilt for, and it is
 * how the move gets replayed by anyone who missed it. An interrupted
 * shared-layout glide is not a glitch: `motion` re-targets from the row's
 * current position, so scrubbing across the mark shuttles the row by hand.
 */
export const ACT_DEADBAND = 0.025;

/**
 * Seconds the moved row glides between stage groups (`PipelineBoard`'s
 * `travel` prop). The board's own 220ms is a tool's tempo — right for a user
 * who just dragged the row, unreadable as a first demonstration: the visitor
 * does not know which row will move, so the move itself has to be slow enough
 * to follow after the strip has said what to watch.
 *
 * This is the ONE duration the act still owns, and it is the one thing on the
 * page that genuinely cannot be scrubbed: the travel is the product's own
 * shared-layout animation between two positions the marketing layer never
 * measures. Everything that could be bound to the scroll has been.
 */
export const VERDICT_TRAVEL = { duration: 1.4 } as const;

/** Milliseconds of settle after the glide before the pane may dock — the
 *  layout animation's tail, so the pane opens on a row at rest. */
export const VERDICT_SETTLE_MS = 200;
