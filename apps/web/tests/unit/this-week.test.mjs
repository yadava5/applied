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

import { localTodayISO, todayISO } from "../../lib/dashboard/age.ts";
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
 *
 * WHAT THIS DOES NOT GRADE, said here because the first version of this
 * comment implied it did. The first two assertions pass on the OLD signature
 * too: `new Date("2026-09-06")` parses as UTC midnight, so `todayISO(day)`
 * returns that same day and the old body computed the identical week. `node
 * --test` strips types rather than checking them, so the string sails through.
 * What they DO grade is a regression where `summarize` ignores its argument
 * and reads a clock — both days would then collapse to the real week and the
 * `notEqual` fires.
 *
 * The third assertion is the one that separates the two signatures, and it is
 * why it is here rather than in a type test.
 *
 * NOTHING IN THIS FILE GRADES THE `DemoDashboard` WIRING, which is where the
 * defect actually lived. Revert that one line and the only red anywhere is the
 * time-windowed comparison in `tests/e2e/demo.spec.ts`. That is a real limit
 * and it is written down rather than papered over.
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

  // THE ASSERTION THAT SEPARATES THE TWO SIGNATURES. The old parameter was an
  // INSTANT and `summarize(apps, NOW)` counted the week around it; the new one
  // is a DAY, and a number is not one — `utcDay` cannot parse it, so nothing
  // is bucketed. Ugly on purpose: it is the only single-process way to state
  // "this argument is a calendar day, not a clock reading", and reverting the
  // signature is exactly the edit that would put an instant back here.
  assert.equal(
    summarize(apps, Date.parse("2026-09-06T12:00:00Z")).thisWeek,
    0,
    "an instant is no longer a day: the parameter must not accept one",
  );
});

/**
 * The default is the UTC day, and it has to stay that way: server renders and
 * the hydrating client pass both call this with no day, and they must produce
 * byte-identical HTML (`age.ts` header, React #418).
 *
 * THE FIRST VERSION OF THIS TEST COULD NOT FAIL. It compared `summarize(apps)`
 * against `summarize(apps, todayISO())` over a row dated a fixed day — two
 * expressions that are equal by construction whatever the default is, and
 * whose count decays to `0 === 0` as that fixed day recedes.
 *
 * This one uses the day AFTER the UTC day, which is the future for a UTC
 * reader and TODAY for a reader east of UTC inside the divergence window. So
 * the assertion is a real gate in `TZ=Asia/Tokyo` and `TZ=Pacific/Auckland`
 * (which `frontend-ci.yml` runs, alongside `America/New_York` and `UTC`), for
 * the part of the day those zones have already turned over — and an honest
 * control everywhere else. Which arm you are in is asserted, not assumed.
 */
test("with no day given it counts from the UTC day, not the reader's", () => {
  const utcToday = todayISO();
  const tomorrowUTC = new Date(Date.parse(`${utcToday}T00:00:00Z`) + 86400000)
    .toISOString()
    .slice(0, 10);
  const apps = [row(tomorrowUTC, tomorrowUTC)];

  assert.equal(
    summarize(apps).thisWeek,
    0,
    "a row dated tomorrow (UTC) was counted: the default is reading a clock that is not UTC",
  );

  // East of UTC and already turned over: the same row IS today for that
  // reader, so a default that read their day would have counted it. Where the
  // two days agree there is nothing to discriminate and this arm is a control.
  if (localTodayISO() > utcToday) {
    assert.equal(
      summarize(apps, localTodayISO()).thisWeek,
      1,
      "the fixture is not east-discriminating: this arm proves nothing",
    );
  }
});
