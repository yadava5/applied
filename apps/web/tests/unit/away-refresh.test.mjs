/**
 * Unit tests for the return-refresh rule (`lib/shell/awayRefresh`).
 *
 * The rule exists because `experimental.staleTimes.dynamic` went from 30 s to
 * 300 s: a working session now stays on the fast path (measured on production
 * before the change — /inbox first visit 1124 ms and one `_rsc` request, the
 * same navigation inside the window 33 ms and zero), and the price is that a
 * change written server-side by the 15-minute scheduled sync (#284) can sit
 * unseen for the length of the window. Coming back to the tab after being
 * away is what heals it.
 *
 * BOTH HALVES ARE THE TEST. A refresh that always fires is a polling loop
 * with extra steps; a refresh that never fires is the stale-data bug the
 * longer window would otherwise ship. So the assertions below pin the fire
 * case, the don't-fire case, the exact boundary between them, and the tab
 * that never left.
 *
 * `now` is injected, as in `detail-cache.test.mjs`: a threshold asserted with
 * wall-clock sleeps measures the machine, not the rule.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { AWAY_REFRESH_THRESHOLD_MS, shouldRefreshOnReturn } from "../../lib/shell/awayRefresh.ts";

test("the threshold sits below the router's stale window, or the rule is inert", () => {
  // `staleTimes.dynamic` is 300 s. The rule only does work in the band
  // between the threshold and the window; equal values close the band.
  assert.ok(AWAY_REFRESH_THRESHOLD_MS < 300_000);
  assert.equal(AWAY_REFRESH_THRESHOLD_MS, 60_000);
});

test("away longer than the threshold refreshes", () => {
  const hiddenAt = 1_000_000;
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + AWAY_REFRESH_THRESHOLD_MS + 1), true);
  // Ten minutes away — squarely past a scheduled sync.
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + 600_000), true);
});

test("a glance away and back costs nothing — the rule can decline", () => {
  const hiddenAt = 1_000_000;
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + 1), false);
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + 30_000), false);
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + AWAY_REFRESH_THRESHOLD_MS - 1), false);
});

test("the boundary is inclusive, and it is one millisecond wide", () => {
  const hiddenAt = 42;
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + AWAY_REFRESH_THRESHOLD_MS - 1), false);
  assert.equal(shouldRefreshOnReturn(hiddenAt, hiddenAt + AWAY_REFRESH_THRESHOLD_MS), true);
});

test("a tab that never left never refreshes", () => {
  // `null` is the never-hidden state the listener starts in and returns to
  // after every arrival. No elapsed time can make it fire.
  assert.equal(shouldRefreshOnReturn(null, 0), false);
  assert.equal(shouldRefreshOnReturn(null, Number.MAX_SAFE_INTEGER), false);
});

test("a clock that moved backwards declines rather than refreshing", () => {
  assert.equal(shouldRefreshOnReturn(1_000_000, 900_000), false);
  assert.equal(shouldRefreshOnReturn(Number.NaN, 1_000), false);
});

test("the threshold is injectable, so the rule is testable at any size", () => {
  assert.equal(shouldRefreshOnReturn(0, 5_000, 10_000), false);
  assert.equal(shouldRefreshOnReturn(0, 10_000, 10_000), true);
});
