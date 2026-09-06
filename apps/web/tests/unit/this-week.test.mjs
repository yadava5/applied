/**
 * Unit tests for the "this week" count (`lib/dashboard/summary.ts`).
 *
 * THE DEFECT (#509). `summarize` counted a row into "this week" from
 * `created_at` — when the SYNC INSERTED IT — rather than `applied_date`, when
 * the user actually applied. On the owner's production board that made the
 * dashboard header read "+47 this wk" for applications submitted across a
 * fortnight, because one sync had just ingested them. The true answer was 7.
 * All 47 dated rows had an `applied_date` in a different calendar week from
 * their `created_at`, so not one of them was counted correctly.
 *
 * EVERY ROW BELOW SETS THE TWO DATES IN DIFFERENT WEEKS ON PURPOSE. That is
 * the whole design of this file: a fixture where `applied_date` and
 * `created_at` agree passes against the bug and proves nothing, which is
 * exactly why the derivation shipped ungated for as long as it did.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { todayISO } from "../../lib/dashboard/age.ts";
import { summarize } from "../../lib/dashboard/summary.ts";

/** Fixed clock: 2026-08-26T12:00:00Z. The window reaches back to 2026-08-19. */
const NOW = Date.parse("2026-08-26T12:00:00Z");

/** The DAY `summarize` buckets against — it takes a day, not an instant (#584).
 *  Derived from `NOW` rather than retyped, so the comment above stays true. */
const TODAY = todayISO(NOW);

/** A row applied on `appliedDate` but ingested on `createdAt`. */
const row = (appliedDate, createdAt, status = "applied") => ({
  id: `${appliedDate}-${createdAt}`,
  company: "Acme",
  status,
  source: "gmail",
  due_at: null,
  applied_date: appliedDate,
  created_at: `${createdAt}T09:00:00Z`,
});

test("counts the week the user applied, not the week we ingested the row", () => {
  const apps = [
    // Applied five weeks ago; ingested today. The reported bug, exactly.
    row("2026-07-20", "2026-08-26"),
    row("2026-07-21", "2026-08-26"),
    // Applied inside the window; ingested today.
    row("2026-08-24", "2026-08-26"),
  ];
  assert.equal(
    summarize(apps, TODAY).thisWeek,
    1,
    "rows ingested today but applied for weeks ago are being counted as this week",
  );
});

test("a row applied this week still counts when it was ingested long ago", () => {
  // The inverse error: the confirmation arrived in an earlier sync, so
  // `created_at` is old, but the application itself is from this week.
  const apps = [row("2026-08-25", "2026-07-01")];
  assert.equal(summarize(apps, TODAY).thisWeek, 1);
});

test("the window is THIS CALENDAR WEEK — Monday to today, matching the momentum bars", () => {
  // NOW is Wednesday 2026-08-26, so the week is Monday the 24th through today.
  //
  // THE EDGE HAS MOVED TWICE, and both moves are recorded because the second
  // one inverts an assertion the first one wrote. It first spanned EIGHT dates
  // (`now - 7 days` with `>=` on both ends), then seven; both were TRAILING
  // windows, and the owner reported that as wrong: "the week counter should be
  // actual real life week data, but real calendar". A rolling window never
  // starts over — on a Monday it still carries the previous Thursday.
  //
  // So the near edge is no longer "six days back". It is this week's Monday,
  // and Sunday the 23rd — one day earlier, and well inside any seven-day
  // window — is now OUT. That last assertion is the one that fails if anyone
  // reinstates the rolling window.
  assert.equal(summarize([row("2026-08-26", "2026-08-26")], TODAY).thisWeek, 1, "today");
  assert.equal(summarize([row("2026-08-24", "2026-08-24")], TODAY).thisWeek, 1, "this week's Monday");
  assert.equal(
    summarize([row("2026-08-23", "2026-08-23")], TODAY).thisWeek,
    0,
    "Sunday belongs to LAST week, however few days ago it was",
  );
  assert.equal(
    summarize([row("2026-08-20", "2026-08-20")], TODAY).thisWeek,
    0,
    "the old trailing window's near edge, which is last Thursday",
  );
});

test("a future applied date is not this week", () => {
  assert.equal(summarize([row("2026-09-02", "2026-08-26")], TODAY).thisWeek, 0);
});

/**
 * An undated row falls back to `created_at`, VIA `filedAt` — the same accessor
 * the momentum bars on the same screen have always used.
 *
 * This test asserted the opposite until the twin proved it wrong. Excluding
 * undated rows reads as the stricter, safer choice, and on the signed-in board
 * it changes nothing either way: the API serves no row without an
 * `applied_date` (50 of 57 on the live board, the other 7 withheld). But the
 * DEMO twin's fixtures had no `applied_date` at all, so a rule that excluded
 * them sent the twin's week to zero and took a passing e2e down with it.
 *
 * The lesson is the one this file is about. Two derivations of one number
 * drift; the fix is to share the accessor, not to write a second rule that
 * looks stricter. `filedAt` is that accessor, and the fixtures now carry a real
 * `applied_date` besides, so the fallback is a floor rather than the path.
 */
test("an undated row falls back to its insert time, as the momentum bars do", () => {
  const undated = { ...row("2026-08-24", "2026-08-26"), applied_date: null };
  const summary = summarize([undated], TODAY);
  assert.equal(summary.thisWeek, 1, "an undated row was dropped, not folded back");
  assert.equal(summary.total, 1);
});

test("the fallback is a floor: a real applied_date always outranks created_at", () => {
  // The CONTROL for the line above — without it, "falls back" could be
  // satisfied by ignoring `applied_date` entirely, which is the original bug.
  assert.equal(summarize([row("2026-07-20", "2026-08-26")], TODAY).thisWeek, 0);
});

test("a malformed applied date is not counted and does not throw", () => {
  for (const bad of ["", "not-a-date", "2026-08", 20260824]) {
    const app = { ...row("2026-08-24", "2026-08-26"), applied_date: bad };
    assert.equal(summarize([app], TODAY).thisWeek, 0, `${JSON.stringify(bad)} was counted`);
  }
});

/**
 * #584. `summarize` took `now: number` and derived the UTC day itself, so a
 * caller that KNEW the reader's day had no way to say so — and /demo's header
 * was exactly that caller, sitting beside a momentum caption that already
 * counted from `useLocalToday()`.
 *
 * The two days below are the real pair, not an invented one: a reader at
 * UTC-10 at 04:00 UTC on Monday 2026-09-07 is living in Sunday 2026-09-06.
 * They fall in DIFFERENT calendar weeks, which is the whole reason the split
 * was worth a number rather than a shrug.
 */
test("the week is counted from the day it is GIVEN, not from a clock it reads", () => {
  // The demo's own near seeds: filed 0, 1, 3 and 5 days before the reader's
  // Sunday, so every one of them is inside that reader's Monday-to-Sunday week.
  const readerSunday = "2026-09-06";
  const utcMonday = "2026-09-07";
  const apps = [
    row("2026-09-06", "2026-09-06"),
    row("2026-09-05", "2026-09-05"),
    row("2026-09-03", "2026-09-03"),
    row("2026-09-01", "2026-09-01"),
  ];

  assert.equal(summarize(apps, readerSunday).thisWeek, 4, "the reader's own week");
  // The UTC day has already rolled into the NEXT week, which contains none of
  // them — and `buildSubtitle` omits the whole segment at zero, so the header
  // did not read a wrong number, it silently stopped saying anything.
  assert.equal(summarize(apps, utcMonday).thisWeek, 0, "the UTC week");

  // Stated as its own assertion so the pair cannot quietly become one case:
  // if a future edit made both days answer the same, the two lines above could
  // still be made to pass by changing one number, and this one could not.
  assert.notEqual(
    summarize(apps, readerSunday).thisWeek,
    summarize(apps, utcMonday).thisWeek,
    "the two days must be able to disagree, or this file grades nothing",
  );
});

/**
 * The default is the UTC day, and it has to stay that way: server renders and
 * the hydrating client pass both call this with no day, and they must produce
 * byte-identical HTML (`age.ts` header, React #418).
 */
test("with no day given it counts from the UTC day", () => {
  const apps = [row("2026-09-06", "2026-09-06")];
  assert.equal(
    summarize(apps).thisWeek,
    summarize(apps, todayISO()).thisWeek,
    "the default must be the UTC day, or SSR and hydration disagree",
  );
});
