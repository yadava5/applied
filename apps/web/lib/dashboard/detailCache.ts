/**
 * A tiny in-tab cache for `GET /api/applications/{id}` payloads — the detail
 * pane's read.
 *
 * WHY. #203 measured the pane's open at 850 ms for 568 bytes, and REOPENING
 * the same row at 820 ms: the whole cost is the origin round-trip (proxy
 * route → FastAPI → Supabase), re-paid every time the pane mounts, including
 * for a row the user looked at four seconds ago. Traversing the board with
 * ↑/↓ pays it per step, in both directions.
 *
 * THE TRADE, stated. Within the window, a reopen can show a trail that is up
 * to 30 s old. That is the same trade — the same number, on purpose — the
 * router cache makes for whole routes (`experimental.staleTimes.dynamic`,
 * #211), and it is bounded the same way: nothing on this board changes
 * server-side except through THIS tab's own actions, and every one of those
 * actions invalidates here (see `lib/dashboard/transport.ts` — row mutations
 * drop the row's entry; a sync/rebuild, which can add messages to any
 * application's trail, clears the cache whole). What remains is the pure
 * TTL: a review-queue classify or a filed-mail correction elsewhere in the
 * tab can add to a trail and is healed by expiry within 30 s.
 *
 * Module-scope state is per browser tab, exactly like the router cache it
 * mirrors; the server never imports this. `now` is injectable so the TTL is
 * testable without wall-clock sleeps (`tests/unit/detail-cache.test.mjs`).
 */

/** Same window as `staleTimes.dynamic` — one trade, one number. */
export const DETAIL_CACHE_TTL_MS = 30_000;

type Entry = { body: unknown; at: number };

const entries = new Map<number, Entry>();

/** The cached payload for a row, or `null` when absent or expired. */
export function readCachedDetail(id: number, now: number = Date.now()): unknown | null {
  const entry = entries.get(id);
  if (!entry) return null;
  if (now - entry.at > DETAIL_CACHE_TTL_MS) {
    entries.delete(id);
    return null;
  }
  return entry.body;
}

export function cacheDetail(id: number, body: unknown, now: number = Date.now()): void {
  entries.set(id, { body, at: now });
}

/** Drop one row's entry — every row-scoped mutation calls this on success. */
export function invalidateDetail(id: number): void {
  entries.delete(id);
}

/** Drop everything — for writes that can touch any row (sync/rebuild). */
export function clearDetailCache(): void {
  entries.clear();
}
