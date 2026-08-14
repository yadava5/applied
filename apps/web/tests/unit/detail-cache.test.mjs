/**
 * Unit tests for the detail pane's in-tab cache (`lib/dashboard/detailCache`).
 *
 * The cache exists because #203 measured `GET /api/applications/{id}` at
 * 850 ms for 568 bytes and a REOPEN of the same row at 820 ms — the whole
 * cost re-paid for a payload the tab held four seconds earlier. What must
 * hold, and is held here:
 *
 *   - a write is readable back inside the 30 s window, and NOT after it
 *     (the TTL is the correctness bound for changes made outside this tab's
 *     transports — expiry is what heals them, so it must actually expire);
 *   - a row-scoped invalidation drops that row and only that row (the
 *     transports call it after every successful mutation);
 *   - the whole-cache clear drops everything (the sync path — a rebuild can
 *     touch any trail).
 *
 * `now` is injected everywhere: a TTL asserted with wall-clock sleeps is a
 * flaky test measuring the machine, not the cache.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  DETAIL_CACHE_TTL_MS,
  cacheDetail,
  clearDetailCache,
  invalidateDetail,
  readCachedDetail,
} from "../../lib/dashboard/detailCache.ts";

test("a cached payload is served inside the TTL window", () => {
  clearDetailCache();
  const body = { application: { id: 7 }, messages: [] };
  cacheDetail(7, body, 1_000);
  assert.equal(readCachedDetail(7, 1_000 + DETAIL_CACHE_TTL_MS), body);
});

test("the same entry is GONE one millisecond past the window — the TTL can fail", () => {
  clearDetailCache();
  cacheDetail(7, { id: 7 }, 1_000);
  assert.equal(readCachedDetail(7, 1_000 + DETAIL_CACHE_TTL_MS + 1), null);
  // Expiry evicts rather than shadows: a fresh write at the same id works.
  cacheDetail(7, { id: 7, v: 2 }, 60_000);
  assert.deepEqual(readCachedDetail(7, 60_000), { id: 7, v: 2 });
});

test("an unknown id is a miss, not an error", () => {
  clearDetailCache();
  assert.equal(readCachedDetail(999, 0), null);
});

test("invalidateDetail drops that row and only that row", () => {
  clearDetailCache();
  cacheDetail(1, "one", 0);
  cacheDetail(2, "two", 0);
  invalidateDetail(1);
  assert.equal(readCachedDetail(1, 1), null);
  assert.equal(readCachedDetail(2, 1), "two");
});

test("clearDetailCache drops everything", () => {
  cacheDetail(1, "one", 0);
  cacheDetail(2, "two", 0);
  clearDetailCache();
  assert.equal(readCachedDetail(1, 1), null);
  assert.equal(readCachedDetail(2, 1), null);
});

test("the TTL matches the router cache's dynamic window — one trade, one number", () => {
  // `next.config.ts` sets `staleTimes.dynamic: 30`. If either number moves,
  // the other must be re-argued, not silently left behind.
  assert.equal(DETAIL_CACHE_TTL_MS, 30_000);
});
