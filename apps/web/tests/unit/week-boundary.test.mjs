/**
 * "This week" is a REAL CALENDAR WEEK, and both sides agree which one (#519).
 *
 * THE REPORT: "the week counter should be actual real life week data, but real
 * calendar!" — the header and the momentum caption both counted a TRAILING
 * SEVEN DAYS, which never starts over. On a Monday morning it still carried
 * the previous Thursday's filings.
 *
 * THE OTHER HALF OF THIS FILE IS IN PYTHON.
 * `backend/tests/test_this_week_is_a_calendar_week.py` asserts the SAME rows
 * of `tests/fixtures/week-boundary.json` against the backend's `_week_start`.
 * The boundary is derived twice and cannot share code across the two
 * languages, so the shared table is what makes the two fail together: there is
 * one copy of the answers, and "fix one side, both suites stay green" — the
 * way the demo twin drifted from the board before — is no longer available.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { dailyCounts, daysElapsedThisWeek, weekOverWeek, weekStartOf } from "../../lib/dashboard/age.ts";

const TABLE = JSON.parse(
  readFileSync(fileURLToPath(new URL("../fixtures/week-boundary.json", import.meta.url)), "utf8"),
);

test("the shared table still starts the week on Monday", () => {
  assert.equal(
    TABLE.weekStartsOn,
    "monday",
    "the table changed which day starts the week; both implementations have to move with it",
  );
});

test("weekStartOf returns the Monday the shared table names", () => {
  for (const row of TABLE.days) {
    assert.equal(weekStartOf(row.day), row.weekStart, `${row.day} (${row.weekday})`);
  }
});

test("daysElapsedThisWeek matches the shared table", () => {
  for (const row of TABLE.days) {
    assert.equal(daysElapsedThisWeek(row.day), row.daysElapsed, `${row.day} (${row.weekday})`);
  }
});

test("the table covers every weekday, Monday included", () => {
  // Monday is the whole difficulty: it is the day the calendar week is one day
  // wide and the trailing window was seven. A table that happened to skip it
  // would pass on the bug.
  assert.deepEqual(
    new Set(TABLE.days.map((row) => row.weekday)),
    new Set(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]),
  );
});

/** 30 buckets, one filing on every single day — so any window's count IS its width. */
const everyDay = (today) =>
  dailyCounts(
    Array.from({ length: 30 }, (_, back) => {
      const day = new Date(Date.parse(`${today}T00:00:00Z`) - back * 86400000);
      return day.toISOString().slice(0, 10);
    }),
    today,
  );

test("thisWeek counts Monday-to-today, and resets on a Monday", () => {
  // A board filed on every one of the last 30 days. Under the trailing window
  // this was 7 on every weekday; under a calendar week it is the weekday
  // number, which is the reset the report asked for.
  for (const row of TABLE.days) {
    assert.equal(
      weekOverWeek(everyDay(row.day), row.day).thisWeek,
      row.daysElapsed,
      `${row.day} (${row.weekday}) should count ${row.daysElapsed} day(s) of this week`,
    );
  }
});

test("lastWeek is always a whole week, and lastWeekToDate is the like-for-like span", () => {
  // The distinction the caption depends on. Comparing a Monday's ONE day
  // against last week's SEVEN reports a collapse for a board nobody touched,
  // so the caption reads `lastWeekToDate` and the panel states `lastWeek`.
  for (const row of TABLE.days) {
    const week = weekOverWeek(everyDay(row.day), row.day);
    assert.equal(week.lastWeek, 7, `${row.day}: last week is seven whole days`);
    assert.equal(
      week.lastWeekToDate,
      row.daysElapsed,
      `${row.day}: the baseline spans the same days as this week so far`,
    );
    assert.equal(week.daysElapsed, row.daysElapsed);
  }
});

test("an unparsable day degrades to a whole week rather than to zero", () => {
  // A caption that silently reads 0 is worse than one that reads a full week:
  // zero looks like "you have filed nothing", which is a claim about the user.
  assert.equal(daysElapsedThisWeek("not-a-day"), 7);
  assert.equal(weekStartOf("not-a-day"), null);
});

test("a short bucket array cannot make the window read the wrong days", () => {
  // `slice(-n)` with a negative start counts from the END, so an unclamped
  // implementation given fewer than 14 buckets would sum a window it was never
  // handed. Guarded because `dailyCounts` takes a `days` argument.
  const counts = [1, 1, 1]; // three days, ending on a Sunday
  const week = weekOverWeek(counts, "2026-08-30");
  assert.equal(week.thisWeek, 3, "every bucket it has is inside the week");
  assert.equal(week.lastWeek, 0, "it holds no days of the previous week");
  assert.equal(week.lastWeekToDate, 0);
});
