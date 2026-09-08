/**
 * Where the reader goes when the row they were standing IN leaves the board
 * (#903, and #425's family — "where does focus go when the thing under it
 * disappears").
 *
 * The removal path is the case the board had no answer for. A dismissal keeps
 * the row on screen for `UNDO_WINDOW_SECONDS` with focus on its Undo, and then
 * the whole cell unmounts: measured on /demo at 1024, focus was on `<body>`
 * from the instant the slot went (t=6.02s) to the end of the trace. A reader
 * who was mid-decision about a destructive action loses the ring, the
 * announcement and their Shift+Tab anchor at exactly that moment.
 *
 * This module owns only the CHOICE of successor, in preference order, so the
 * rule can be asserted without a DOM. The board walks the list and focuses the
 * first candidate that is actually rendered — a row inside a collapsed employer
 * set is a real id with no control on screen, and skipping it here would need
 * this module to know about set state, which is the board's business.
 *
 * The order is "the row that took its place, then the one it sat under":
 *
 *  1. rows AFTER the removed one in its own stage — the list closes up, so the
 *     first survivor below is the row now occupying that place;
 *  2. rows BEFORE it in its own stage, nearest first, for a row that was last;
 *  3. the same two walks with the stage constraint dropped, for a removal that
 *     emptied the column — an empty stage renders no heading at all, so there
 *     is nothing left there to hold anyone.
 *
 * An empty result is honest and the board does nothing with it: on a board
 * whose last row just left there is no row to go to, and inventing one (the
 * search box, the page heading) would move the reader somewhere they were not.
 */

/** A row as the board ordered it, reduced to what this decision needs. */
export interface OrderedRow {
  id: number;
  /** The stage KEY the row was grouped under, i.e. its column. */
  stage: string;
}

export function focusCandidatesAfterRemoval(
  previous: readonly OrderedRow[],
  surviving: ReadonlySet<number>,
  removedId: number,
): number[] {
  const at = previous.findIndex((row) => row.id === removedId);
  if (at === -1) return [];
  const stage = previous[at].stage;
  const after = previous.slice(at + 1).filter((row) => surviving.has(row.id));
  const before = previous
    .slice(0, at)
    .filter((row) => surviving.has(row.id))
    .reverse();

  const ordered = [
    ...after.filter((row) => row.stage === stage),
    ...before.filter((row) => row.stage === stage),
    ...after.filter((row) => row.stage !== stage),
    ...before.filter((row) => row.stage !== stage),
  ];
  return ordered.map((row) => row.id);
}
