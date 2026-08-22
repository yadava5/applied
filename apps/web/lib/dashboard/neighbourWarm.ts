/**
 * Which rows to warm around the open detail card, and how long to wait first.
 *
 * WHY THIS EXISTS. The detail pane already answers a click with no network:
 * company, role, stage, filed date and deadline all come off the row the board
 * is already holding. The one thing that waits is "the mail behind this card"
 * — `GET /api/applications/{id}` — measured on production 2026-08-22, signed
 * in, at a **371 ms median** (n=6, `Server-Timing` read off the browser's own
 * Resource Timing). That request is not going to get much faster: 81 ms of it
 * is browser↔edge↔the Next app with the handler doing nothing, up to ~47 ms
 * more is the signed-in path through `proxy.ts` (dominated by its
 * `supabase.auth.getUser()` round trip, though that figure is an upper bound —
 * the control also drops the whole cookie jar), and the rest is a
 * cross-function hop to the FastAPI project plus four serial statements
 * against the pooler. Connection reuse is already on — `db_connect;desc="n=0"`
 * on every WARM sample — so the old ~216 ms NullPool tax is not in this number
 * and must not be re-litigated. (A fresh backend instance does still pay one
 * connect, measured once at `n=1`, 105 ms; see the linked issue.)
 *
 * So the win is not a faster request — it is the same request, taken earlier.
 * The next card a reader opens is nearly always a neighbour: ↑/↓ traverse
 * exactly the board's visible order, and a mouse walks it in the same order.
 * Warming one row either side turns the next step into a cache hit, using the
 * cache (`lib/dashboard/detailCache`) and the transport that already existed.
 *
 * BOUNDED BY THE CACHE'S OWN TTL, which is 30 s. A reader who studies one card
 * for longer than that and only then arrows on finds the warmed neighbour
 * already expired and pays the full read again. That is not a bug to fix here:
 * the TTL is the correctness bound on mail filed server-side by the 15-minute
 * cron, argued out in `detailCache.ts`, and it is not worth widening for a
 * prefetch. It does mean the honest claim is "the next step is free for a
 * reader who is moving", not "every step after the first is free".
 *
 * The walk stays one step ahead without compounding: opening A warms A±1;
 * arrowing to A+1 is a cache hit and re-arms for A and A+2, of which A is
 * itself a hit — one speculative read per step, not two.
 *
 * Kept as a pure function, out of the component, so the bound is testable
 * without rendering a board: the clamping at both ends and the refusal to warm
 * anything with the pane closed are the parts that can regress silently.
 */

/**
 * How long an open card must stay open before its neighbours are warmed.
 *
 * Longer than the 371 ms median the open card's OWN read takes, so a
 * speculative fetch never competes with the request the reader is actually
 * waiting on — the backend pool is deliberately small and the reader's row
 * must never queue behind a guess. Short enough that a deliberate ↑/↓ step
 * (about a second apart) always lands on a warm row. Holding ↓ re-arms the
 * timer per step and the caller's cleanup cancels it, so a fast traversal
 * fetches nothing at all.
 */
export const NEIGHBOUR_WARM_DELAY_MS = 400;

/**
 * The ids to warm for the card at `index` of `ordered` — the row above and the
 * row below, clamped at both ends.
 *
 * Returns empty when no card is open (`index === -1`), which is what stops a
 * board with a closed pane from speculatively reading anything at all. Never
 * includes the open row: that one is already being fetched by the pane.
 */
export function neighbourIdsToWarm(ordered: readonly { id: number }[], index: number): number[] {
  if (index < 0 || index >= ordered.length) return [];
  const ids: number[] = [];
  const before = ordered[index - 1];
  const after = ordered[index + 1];
  if (before) ids.push(before.id);
  if (after) ids.push(after.id);
  return ids;
}
