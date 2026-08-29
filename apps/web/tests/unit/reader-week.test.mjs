/**
 * The header and the momentum caption count ONE week — the reader's (#518).
 *
 * THE DEFECT, as arithmetic. `50 filed · +N this wk` came from
 * `GET /applications/summary`, counted server-side from a UTC Monday.
 * `N this wk · up from M by now`, a few hundred pixels below it, is computed
 * in the browser from `useLocalToday()` — the reader's Monday — because the
 * bars beside that caption bucket on the reader's day. West of UTC that leaves
 * a window each week the size of the offset, and inside it the two surfaces
 * describe different weeks.
 *
 * NO CLOCK IS READ IN THIS FILE, and no timezone is assumed. The two day
 * strings below are what a New York reader's browser and the server actually
 * hold at one instant — `2026-08-31T00:30:00Z`, which is Sunday the 30th at
 * 20:30 in Eastern. Feeding them as literals is what makes these assertions
 * identical in every zone the suite might run in; that `localTodayISO` really
 * returns the reader's day is `local-today.test.mjs`'s job, under four zones,
 * and is not re-asserted here.
 *
 * WHAT IS HERE AND WHAT IS NEXT DOOR. This file covers the DECISION —
 * `summaryWeekCorrection`, a pure function — plus the control that proves the
 * window it decides about is real. The DELIVERY (which day the decision is fed,
 * whether the request is issued, whether its answer reaches the rendered line,
 * whether the parameter survives the proxy) lives in
 * `reader-week-delivery.test.mjs`, which EXECUTES the component and the route
 * handler.
 *
 * IT USED TO LIVE HERE, AS A SOURCE SCAN, AND THAT WAS NOT COVERAGE. A pure
 * function cannot see which day its caller handed it, so the call site was
 * asserted with `source.includes("useLocalToday()")`. The mutation that proof
 * was written against deletes that token — but the mutation that actually
 * matters swaps the ARGUMENT,
 * `summaryWeekCorrection(readerToday, servedWeekStart)` ->
 * `(servedWeekStart, servedWeekStart)`, which restores #518 in full, leaves
 * every scanned substring in place, and was green across all 625 tests. A grep
 * standing in for behaviour is not coverage; the scan is gone and the
 * behaviour is asserted by running it.
 *
 * The one source check that remains is over `dashboard/page.tsx`, an async
 * Server Component that reads cookies and cannot be imported here at all.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  dailyCounts,
  daysElapsedThisWeek,
  isoDaysAgo,
  weekOverWeek,
  weekStartOf,
} from "../../lib/dashboard/age.ts";
import { summaryUrlFor, summaryWeekCorrection } from "../../lib/dashboard/readerWeek.ts";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");

/** 2026-08-31T00:30:00Z in New York: the reader is still in Sunday the 30th… */
const READER_TODAY = "2026-08-30";
/** …while the server has been in Monday the 31st for half an hour. */
const UTC_TODAY = "2026-08-31";

/** Three applications, filed across the reader's current week. */
const FILED = ["2026-08-25", "2026-08-27", "2026-08-30"];

// ---------------------------------------------------------------------------
// The disagreement is real — the control, without which everything below is
// a test of a window that never opens.
// ---------------------------------------------------------------------------

test("at this instant the two clocks name DIFFERENT weeks", () => {
  assert.notEqual(
    weekStartOf(READER_TODAY),
    weekStartOf(UTC_TODAY),
    "the fixture instant is no longer inside the offset window, so nothing below discriminates",
  );
  assert.equal(weekStartOf(READER_TODAY), "2026-08-24");
  assert.equal(weekStartOf(UTC_TODAY), "2026-08-31");
});

test("and the two weeks give the same board different answers", () => {
  // The caption's own derivation, on the reader's day: a full week of filings.
  const caption = weekOverWeek(dailyCounts(FILED, READER_TODAY), READER_TODAY);
  // The same derivation on the UTC day — which is what the header was counting.
  const header = weekOverWeek(dailyCounts(FILED, UTC_TODAY), UTC_TODAY);

  assert.equal(caption.thisWeek, 3, "the reader's week holds all three");
  assert.equal(header.thisWeek, 0, "the UTC week has only just begun and holds none");
  assert.notEqual(caption.thisWeek, header.thisWeek);
});

// ---------------------------------------------------------------------------
// What the client asks for
// ---------------------------------------------------------------------------

test("the Monday requested is the Monday the caption counts from", () => {
  const requested = summaryWeekCorrection(READER_TODAY, weekStartOf(UTC_TODAY));

  // Derived from `weekOverWeek`'s OWN arithmetic rather than from `weekStartOf`
  // a second time: the caption sums the last `daysElapsed` buckets of a window
  // whose final bucket is today, so its first counted day is
  // `today - (daysElapsed - 1)`. That is the day the header must be asking
  // about, and reading it out this way means the two cannot agree merely
  // because one function was called twice.
  const captionWindowStart = isoDaysAgo(READER_TODAY, daysElapsedThisWeek(READER_TODAY) - 1);

  assert.equal(requested, captionWindowStart);
  assert.equal(requested, "2026-08-24");
});

test("no request at all when the server already counted the reader's week", () => {
  // Every hour of the week outside the offset window, and every hour for a
  // reader in UTC. Nothing is fetched and nothing on screen moves.
  assert.equal(summaryWeekCorrection("2026-08-26", "2026-08-24"), null);
  assert.equal(summaryWeekCorrection(UTC_TODAY, weekStartOf(UTC_TODAY)), null);
  assert.equal(summaryWeekCorrection(READER_TODAY, weekStartOf(READER_TODAY)), null);
});

test("a reader AHEAD of the server asks for the week that has already begun", () => {
  // Tokyo's Monday 08:30 is the server's Sunday 23:30 — the mirror case, and
  // the one that moves the requested Monday forwards rather than back.
  assert.equal(summaryWeekCorrection("2026-08-31", "2026-08-24"), "2026-08-31");
});

test("an unreadable day corrects nothing rather than guessing a week", () => {
  for (const bad of ["", "today", "2026-13-01", "31/08/2026"]) {
    assert.equal(summaryWeekCorrection(bad, "2026-08-24"), null, bad);
  }
});

test("the requested Monday reaches the endpoint as week_start", () => {
  assert.equal(summaryUrlFor("2026-08-24"), "/api/applications/summary?week_start=2026-08-24");
});

// ---------------------------------------------------------------------------
// The one call site left here — the Server Component that cannot be executed
// ---------------------------------------------------------------------------

test("the page hands the header the Monday the endpoint actually counted", () => {
  const source = readFileSync(
    join(WEB_ROOT, "app/(app)/(protected)/dashboard/page.tsx"),
    "utf8",
  );

  assert.ok(
    source.includes("<BoardSubtitle"),
    "the dashboard's subtitle is not BoardSubtitle any more, so the correction never mounts",
  );
  assert.ok(
    source.includes("summaryRes.data.week_start"),
    "the served week_start is no longer read off the summary response — without it the " +
      "client cannot tell a corrected answer from an uncorrected one and would re-ask always",
  );
  assert.ok(
    source.includes("servedWeekStart={state.weekStart}"),
    "the served Monday is not reaching BoardSubtitle",
  );
});
