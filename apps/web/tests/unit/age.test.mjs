/**
 * Unit tests for the dashboard's age/momentum math (`lib/dashboard/age.ts`).
 *
 * What these pin down:
 *
 *  1. Day counts are a pure function of the two calendar strings — the same
 *     no-`Date`-construction rule as `dates.ts`, so a card's "quiet 34d" tag
 *     can never disagree between the UTC server and a local-zone browser.
 *  2. The week buckets and the delta line derive from ONE pass over the same
 *     dates, oldest week first, with out-of-window and unparsable dates
 *     dropped rather than guessed.
 *  3. The quiet threshold is one shared constant, so the card tag and the
 *     pulse strip's "N quiet" count use the same boundary.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  MOMENTUM_WEEKS,
  QUIET_AFTER_DAYS,
  bucketAges,
  daysBetween,
  momentumDelta,
  todayISO,
  weeklyCounts,
} from "../../lib/dashboard/age.ts";

test("daysBetween reads calendar prefixes only — timestamps and date-only agree", () => {
  assert.equal(daysBetween("2026-07-09", "2026-08-11"), 33);
  assert.equal(daysBetween("2026-07-09T23:59:59", "2026-08-11"), 33);
  assert.equal(daysBetween("2026-07-09T00:00:01Z", "2026-08-11"), 33);
});

test("daysBetween is null for absent or malformed input, never a guess", () => {
  assert.equal(daysBetween(null, "2026-08-11"), null);
  assert.equal(daysBetween(undefined, "2026-08-11"), null);
  assert.equal(daysBetween("last Tuesday", "2026-08-11"), null);
  assert.equal(daysBetween("2026-13-01", "2026-08-11"), null);
});

test("a future date is negative, and bucketAges drops it", () => {
  assert.equal(daysBetween("2026-08-20", "2026-08-11"), -9);
  assert.deepEqual(bucketAges([-9]), { fresh: 0, waiting: 0, quiet: 0 });
});

test("the quiet boundary is exactly QUIET_AFTER_DAYS, shared with the card tag", () => {
  const b = bucketAges([0, 6, 7, QUIET_AFTER_DAYS - 1, QUIET_AFTER_DAYS, 60, null]);
  assert.deepEqual(b, { fresh: 2, waiting: 2, quiet: 2 });
});

test("weeklyCounts buckets oldest-first with the current week last", () => {
  const today = "2026-08-11";
  const counts = weeklyCounts(
    [
      "2026-08-11", // 0d  → current week (last bucket)
      "2026-08-05", // 6d  → current week
      "2026-08-04", // 7d  → one week back
      "2026-06-17", // 55d → oldest in-window bucket
      "2026-06-16", // 56d → outside the 8-week window, dropped
      "not a date", // dropped
      null, // dropped
    ],
    today,
  );
  assert.equal(counts.length, MOMENTUM_WEEKS);
  assert.deepEqual(counts, [1, 0, 0, 0, 0, 0, 1, 2]);
});

test("momentumDelta halves the same buckets the bars draw", () => {
  assert.deepEqual(momentumDelta([1, 0, 0, 0, 0, 0, 1, 2]), { recent: 3, prior: 1 });
});

test("todayISO is the UTC calendar day of the instant it is handed", () => {
  assert.equal(todayISO(Date.UTC(2026, 7, 11, 23, 59, 59)), "2026-08-11");
  assert.equal(todayISO(Date.UTC(2026, 7, 12, 0, 0, 1)), "2026-08-12");
});
