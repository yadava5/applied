/**
 * WHERE THE LEDGER'S PLATE SITS ON THE BAR — the arithmetic, on its own.
 *
 * `SinceLastLook` centres its chip on the notification overlay and then yields
 * exactly as far as a same-line neighbour forces; that component's `placePlate`
 * header tells the whole placement story, including why the totals win when
 * both neighbours bind at once (#196). What lives here is the last two lines of
 * it: given the plate's box and whichever of the totals and the sync cluster
 * share its line, how far does the plate slide.
 *
 * IT IS A FILE OF ITS OWN BECAUSE #610 WAS A TIMING DEFECT AND THE BUDGET WAS
 * ALREADY RIGHT. The clearance below is the guard that holds the plate off the
 * subtitle's right edge, and it was correct — it was just computed once, before
 * the reader's-week correction (#518) made a ~70px segment APPEAR in that
 * subtitle. Measured at 1024 on the board the owner reads: 69.4px of segment
 * against 16px of clearance, so the totals ran ~53px under the changes pill
 * with a sound budget in hand. `SinceLastLook.tsx` is a client component
 * `node --test` cannot import, so the one number that mattered was the one
 * number nothing could execute. Here it is four lines over plain edges, and
 * `tests/unit/plate-placement.test.mjs` drives it with that issue's own
 * measurements.
 *
 * No imports at all, which is the discipline `lib/dashboard/summary.ts`
 * documents for this directory: `node --test` strips types but cannot resolve
 * the `@/` alias, and one value import through it would make this untestable
 * again.
 */

/** The horizontal edges of a box on the plate's line. `DOMRect` satisfies it
 *  structurally, so the component hands its measurements straight through. */
export interface Edges {
  readonly left: number;
  readonly right: number;
}

/** What the plate keeps from a same-line neighbour. Under the gate's 24px floor
 *  for the arrangement that fits — the neighbours there never bind: ~72px clear
 *  on the quiet chip at 1024 (`next start`, 2026-08-14) and 65.0px on the wider
 *  loud one (2026-09-07). The crowded fixture twin is gated at 12 instead, and
 *  its cluster binds at exactly this number. */
export const PLATE_CLEAR = 16;

/**
 * How far the plate slides off its centred position: negative towards the
 * totals' side, positive away from them, 0 where the centre already clears
 * both. The caller applies it as a transform, so the centre stays the
 * stylesheet's business and this stays a measurement.
 *
 * A neighbour that is not on the plate's line — the row has wrapped, or the box
 * is empty — is `null` and constrains nothing, which is how the stacked header
 * below `lg` costs a no-op instead of a nudge.
 *
 * THE TOTALS WIN when both bind, and the order below is that rule: the cluster
 * pulls the plate left, the totals then push it right past whatever the cluster
 * asked for. #196 is the defect with a number on it — a plate that yielded to
 * the controls first read as a caption hung off the totals it was overlapping.
 */
export function plateSlide({
  plate,
  totals,
  cluster,
  clear = PLATE_CLEAR,
}: {
  plate: Edges;
  totals: Edges | null;
  cluster: Edges | null;
  clear?: number;
}): number {
  let dx = 0;
  if (cluster) dx = Math.min(dx, cluster.left - clear - plate.right);
  if (totals) dx = Math.max(dx, totals.right + clear - plate.left);
  return dx;
}
