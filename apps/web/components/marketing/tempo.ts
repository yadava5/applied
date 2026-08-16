/**
 * The window act's beat-1 tempo — one module, because three components keep
 * time against each other and a drifted copy of any number here breaks the
 * causal chain the scene exists to show: mail arrives → verdict → THIS row
 * moves → it lands somewhere new.
 *
 * Plain data, no directive, and deliberately not exported from
 * `MarketingBoard`: `WindowAct` needs the receipt delay, and a static import
 * from `MarketingBoard` would pull the whole dashboard graph into the act's
 * chunk — the exact cost `LandingBoard`'s dynamic mount exists to avoid.
 */

/** The pause between the camera settling at the board's foot and the row
 *  travelling. One event, read in sequence: the pan is 700ms, so the breath
 *  outlasts it and the move never starts on a moving frame. */
export const VERDICT_BREATH_MS = 750;

/**
 * The narrated glide for the verdict row — the tempo `MarketingBoard` hands
 * the board for the ONE commit the page performs, against the product's own
 * 220ms (`PipelineBoard`'s default, which answers a hand that already knows
 * what it did). 1.4s with a sustained middle rather than the product's hard
 * ease-out: the row enters the frame from above, and the watchable part of
 * the transit is its arrival — an ease-out at this duration would spend the
 * visible portion nearly stopped.
 */
export const VERDICT_TRAVEL = {
  duration: 1.4,
  ease: [0.35, 0, 0.15, 1],
} as const;

/** Margin after the glide before the tempo is handed back — covers the layout
 *  animation's own tail so a visitor's drag a beat later answers at product
 *  speed without ever truncating the narrated one. */
export const VERDICT_TRAVEL_HOLD_MS = 300;

/** When the receipt card (`ChangedRow`) floats in: after the row has LANDED,
 *  plus a beat to let the landing register. The receipt is the explanation,
 *  and an explanation that arrives before the event narrates nothing. */
export const RECEIPT_DELAY_MS =
  VERDICT_BREATH_MS + VERDICT_TRAVEL.duration * 1000 + 400;
