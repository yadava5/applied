/**
 * Unit tests for the dashboard's age/momentum math (`lib/dashboard/age.ts`).
 *
 * What these pin down:
 *
 *  1. Day counts are a pure function of the two calendar strings — the same
 *     no-`Date`-construction rule as `dates.ts`, so a card's "quiet 34d" tag
 *     can never disagree between the UTC server and a local-zone browser.
 *  2. The day buckets and the week-over-week delta derive from ONE pass over
 *     the same dates, oldest day first, with out-of-window and unparsable
 *     dates dropped rather than guessed.
 *  3. The quiet threshold is one shared constant, so the card tag, the pulse
 *     strip's "N quiet" count and the age histogram's overflow bin use the
 *     same boundary.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  MOMENTUM_DAYS,
  QUIET_AFTER_DAYS,
  ageHistogram,
  bestDay,
  bucketAges,
  currentStreak,
  dailyCounts,
  daysBetween,
  isoDaysAgo,
  todayISO,
  weekOverWeek,
  weekdayOf,
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

test("dailyCounts buckets oldest-first with today last", () => {
  const today = "2026-08-11";
  const counts = dailyCounts(
    [
      "2026-08-11", // 0d  → today (last bucket)
      "2026-08-11", // 0d  → today again — bursts stack
      "2026-08-05", // 6d
      "2026-07-13", // 29d → oldest in-window bucket
      "2026-07-12", // 30d → outside the 30-day window, dropped
      "not a date", // dropped
      null, // dropped
    ],
    today,
  );
  assert.equal(counts.length, MOMENTUM_DAYS);
  assert.equal(counts[0], 1); // 29d ago
  assert.equal(counts[MOMENTUM_DAYS - 7], 1); // 6d ago
  assert.equal(counts[MOMENTUM_DAYS - 1], 2); // today
  assert.equal(
    counts.reduce((a, b) => a + b, 0),
    4,
  );
});

test("weekOverWeek splits the same buckets the bars draw, at the CALENDAR week", () => {
  // THE SEMANTICS MOVED (#519). This used to assert "the last 7 buckets vs the
  // 7 before them" — a trailing window that never started over, which is what
  // the owner reported as wrong. The split is now Monday-to-today, so the
  // function needs `today` to know which bucket the week begins at.
  //
  // 2026-08-26 is a WEDNESDAY: this week is Mon 24th, Tue 25th, Wed 26th.
  const today = "2026-08-26";
  const counts = new Array(MOMENTUM_DAYS).fill(0);
  counts[MOMENTUM_DAYS - 1] = 2; // Wed 26th — today
  counts[MOMENTUM_DAYS - 3] = 1; // Mon 24th — this week's first day
  counts[MOMENTUM_DAYS - 4] = 5; // Sun 23rd — LAST week's last day
  counts[MOMENTUM_DAYS - 10] = 4; // Mon 17th — last week's first day
  counts[MOMENTUM_DAYS - 11] = 7; // Sun 16th — the week before that, neither
  counts[0] = 9; // 29d ago — neither

  assert.deepEqual(weekOverWeek(counts, today), {
    thisWeek: 3, // 2 + 1
    lastWeek: 9, // 5 + 4, the whole of Mon 17th–Sun 23rd
    lastWeekToDate: 4, // Mon 17th–Wed 19th, the same three days a week earlier
    daysElapsed: 3,
  });

  // The trailing window would have said 8 — it reaches back to Thu 20th and so
  // swallows Sunday the 23rd, the day the calendar week is supposed to end at.
  assert.notEqual(weekOverWeek(counts, today).thisWeek, 8);
});

test("bestDay takes the heaviest day, ties to the most recent, null when empty", () => {
  assert.deepEqual(bestDay([0, 4, 0, 4, 1]), { daysAgo: 1, count: 4 });
  assert.equal(bestDay([0, 0, 0]), null);
});

test("currentStreak counts back from today, forgiving a still-empty today", () => {
  assert.equal(currentStreak([0, 1, 1, 1]), 3);
  assert.equal(currentStreak([0, 1, 1, 0]), 2); // today empty → count from yesterday
  assert.equal(currentStreak([1, 0, 0, 0]), 0);
});

test("isoDaysAgo inverts daysBetween across a month boundary", () => {
  assert.equal(isoDaysAgo("2026-08-11", 0), "2026-08-11");
  assert.equal(isoDaysAgo("2026-08-11", 29), "2026-07-13");
  assert.equal(isoDaysAgo("not a date", 3), null);
});

test("weekdayOf is Monday-zero (2026-08-11 was a Tuesday)", () => {
  assert.equal(weekdayOf("2026-08-11"), 1);
  assert.equal(weekdayOf("2026-08-10"), 0);
  assert.equal(weekdayOf("2026-08-16"), 6);
  assert.equal(weekdayOf("nope"), null);
});

test("ageHistogram bins per day with one overflow bin at the quiet boundary", () => {
  const bins = ageHistogram([0, 0, 6, QUIET_AFTER_DAYS - 1, QUIET_AFTER_DAYS, 60, -2, null]);
  assert.equal(bins.length, QUIET_AFTER_DAYS + 1);
  assert.equal(bins[0], 2);
  assert.equal(bins[6], 1);
  assert.equal(bins[QUIET_AFTER_DAYS - 1], 1);
  assert.equal(bins[QUIET_AFTER_DAYS], 2); // 14d and 60d share the overflow bin
});

/**
 * `todayISO` is still UTC, and must stay UTC — it is the SSR/hydration-stable
 * read, the one value the server and the browser's first pass can both produce.
 * It is NOT what the deadline surfaces bucket against any more: claiming how
 * much time a reader has left needs the reader's own day, which is
 * `localTodayISO` (and `useLocalToday` for the mount gate). See
 * `local-today.test.mjs` for the clock-read behaviour under a real `TZ`.
 */
test("todayISO is the UTC calendar day — the hydration-stable server read", () => {
  assert.equal(todayISO(Date.UTC(2026, 7, 11, 23, 59, 59)), "2026-08-11");
  assert.equal(todayISO(Date.UTC(2026, 7, 12, 0, 0, 1)), "2026-08-12");
});
