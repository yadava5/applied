/**
 * Where a restored row goes back on the demo board (#904).
 *
 * The board draws its rows in the order the array holds them — `PipelineBoard`
 * groups with `filtered.filter(...)` and sorts nothing, deliberately, because
 * the signed-in board's order is the server's and a second ordering rule in the
 * client is how two renderers of one number drift apart. So on /demo the array
 * IS the order, and `restore` appending to it moved the row: a row filed Aug 27
 * came back below one filed Sep 7, and only a reload put it right, because a
 * reload rebuilds the store from the fixtures.
 *
 * The fix is a POSITION, not a predicate. Re-sorting here would invent that
 * second rule — this module instead puts the row back where the mount's own
 * pristine fixtures say it sat, which is exactly the order a reload produces.
 * That is why `reference` is the pristine list and not the live one.
 *
 * A row the reference has never heard of — one a visitor added through the form
 * this session — has no home in that order, so it never decides where a
 * restored row lands, and a restored row never jumps ahead of it. It is
 * appended if it is the one being restored, which is where it already was.
 */

/** Anything the board holds by id. */
interface Identified {
  id: number;
}

export function reinsertByReference<T extends Identified>(
  rows: readonly T[],
  row: T,
  reference: readonly Identified[],
): T[] {
  const home = reference.findIndex((known) => known.id === row.id);
  if (home === -1) return [...rows, row];
  const rank = new Map(reference.map((known, index) => [known.id, index]));
  const at = rows.findIndex((candidate) => {
    const place = rank.get(candidate.id);
    return place !== undefined && place > home;
  });
  return at === -1 ? [...rows, row] : [...rows.slice(0, at), row, ...rows.slice(at)];
}
