/**
 * The chart-tip builders (`lib/dashboard/pulseTip.ts`) — the structured
 * replacement for the native `title` tooltips (#195). The properties that
 * matter:
 *
 *  - the figure is carried as a NUMBER, apart from its words, so the renderer
 *    can weight it first — the one-line-one-weight string is the defect;
 *  - the when/qualifier is a separate label line, present exactly where the
 *    words do not already say when (day bars yes, runway columns no);
 *  - the quiet and soon boundaries sit on QUIET_AFTER_DAYS / the runway's own
 *    bin kinds, matching the derivations the cells draw from.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { QUIET_AFTER_DAYS } from "../../lib/dashboard/age.ts";
import { ageTip, dayName, momentumTip, runwayTip } from "../../lib/dashboard/pulseTip.ts";

test("dayName puts the weekday before the calendar day", () => {
  // 2026-08-11 was a Tuesday.
  assert.equal(dayName("2026-08-11"), "Tue Aug 11");
  assert.equal(dayName("2026-08-10"), "Mon Aug 10");
});

test("dayName degrades to the date formatter's own fallback on garbage", () => {
  assert.equal(dayName("not-a-date"), "—");
});

test("momentumTip binds the figure to 'filed' and labels it with the day", () => {
  assert.deepEqual(momentumTip("2026-08-11", 17), {
    count: 17,
    words: "filed",
    label: "Tue Aug 11",
  });
});

test("momentumTip with no resolvable day carries no label rather than a guess", () => {
  assert.deepEqual(momentumTip(null, 3), { count: 3, words: "filed" });
});

test("ageTip labels a day bin by when its rows were filed", () => {
  assert.deepEqual(ageTip(0, 4), { count: 4, words: "open", label: "filed today" });
  assert.deepEqual(ageTip(3, 2), { count: 2, words: "open", label: "filed 3 d ago" });
});

test("ageTip's quiet boundary sits exactly on QUIET_AFTER_DAYS", () => {
  assert.equal(ageTip(QUIET_AFTER_DAYS - 1, 1).label, `filed ${QUIET_AFTER_DAYS - 1} d ago`);
  assert.equal(ageTip(QUIET_AFTER_DAYS, 1).label, "filed 2 wk or more ago");
});

test("runwayTip speaks each bin kind in the deadline vocabulary, with no label line", () => {
  assert.deepEqual(runwayTip({ kind: "overdue", count: 2 }), { count: 2, words: "overdue" });
  assert.deepEqual(runwayTip({ kind: "day", days: 0, count: 1 }), { count: 1, words: "due today" });
  assert.deepEqual(runwayTip({ kind: "day", days: 2, count: 3 }), { count: 3, words: "due in 2d" });
  assert.deepEqual(runwayTip({ kind: "later", count: 5 }), { count: 5, words: "due after 2 days" });
});
