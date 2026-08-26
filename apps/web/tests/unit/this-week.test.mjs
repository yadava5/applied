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

import { summarize } from "../../lib/dashboard/summary.ts";

/** Fixed clock: 2026-08-26T12:00:00Z. The window reaches back to 2026-08-19. */
const NOW = Date.parse("2026-08-26T12:00:00Z");

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
    summarize(apps, NOW).thisWeek,
    1,
    "rows ingested today but applied for weeks ago are being counted as this week",
  );
});

test("a row applied this week still counts when it was ingested long ago", () => {
  // The inverse error: the confirmation arrived in an earlier sync, so
  // `created_at` is old, but the application itself is from this week.
  const apps = [row("2026-08-25", "2026-07-01")];
  assert.equal(summarize(apps, NOW).thisWeek, 1);
});

test("the window edges are days, and inclusive at the near edge", () => {
  assert.equal(summarize([row("2026-08-19", "2026-08-19")], NOW).thisWeek, 1);
  assert.equal(summarize([row("2026-08-18", "2026-08-18")], NOW).thisWeek, 0);
});

test("a future applied date is not this week", () => {
  assert.equal(summarize([row("2026-09-02", "2026-08-26")], NOW).thisWeek, 0);
});

/**
 * Undated rows count toward nothing. Falling back to `created_at` would
 * reintroduce the whole bug for precisely the rows whose date is unknown — and
 * would do it invisibly, since those are the rows nobody can check by eye.
 */
test("a row with no applied date is not counted, and does not fall back", () => {
  const undated = { ...row("2026-08-24", "2026-08-26"), applied_date: null };
  const summary = summarize([undated], NOW);
  assert.equal(summary.thisWeek, 0, "an undated row fell back to its insert time");
  // ...but it is still a real application and must not vanish from the totals.
  assert.equal(summary.total, 1);
});

test("a malformed applied date is not counted and does not throw", () => {
  for (const bad of ["", "not-a-date", "2026-08", 20260824]) {
    const app = { ...row("2026-08-24", "2026-08-26"), applied_date: bad };
    assert.equal(summarize([app], NOW).thisWeek, 0, `${JSON.stringify(bad)} was counted`);
  }
});
