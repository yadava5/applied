/**
 * The CLOCK READ behind every deadline claim — the one thing the rest of the
 * deadline tests deliberately do not exercise.
 *
 * `deadline.test.mjs` and `age.test.mjs` feed a literal `TODAY` string, so they
 * pass in every timezone by construction: they pin the arithmetic, never the
 * question "which day is it for the person reading this card?". That question
 * is what shipped wrong. A New York user at 21:00 on Aug 11 was bucketed
 * against the UTC day (Aug 12) and told an assessment due at the end of Aug 11
 * was `overdue 1d` — while they still had three hours. Positive-offset zones
 * failed the other way: a deadline whose local day had already passed still
 * read `due today`.
 *
 * So these tests read the clock, under a fixed instant and whatever `TZ` the
 * process was given, and check the day against an ORACLE computed independently
 * of the code under test. The file itself is timezone-agnostic — the same
 * assertions must hold in every zone — which is what makes running it under
 * four of them meaningful rather than decorative.
 *
 * Run (all four must be green; UTC is the positive control):
 *
 *   TZ=America/New_York node --test tests/unit/local-today.test.mjs
 *   TZ=Asia/Tokyo       node --test tests/unit/local-today.test.mjs
 *   TZ=Pacific/Auckland node --test tests/unit/local-today.test.mjs
 *   TZ=UTC              node --test tests/unit/local-today.test.mjs
 */
import assert from "node:assert/strict";
import test from "node:test";

import { localTodayISO } from "../../lib/dashboard/age.ts";
import { dueDayISO, dueInfo, duePhrase } from "../../lib/dashboard/deadline.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * The oracle: what the READER's own calendar says the day is, derived without
 * touching the code under test. `en-CA` formats as `YYYY-MM-DD`, and omitting
 * `timeZone` means the runtime's zone — which is precisely the day a browser's
 * `<input type="date">` offers as "today", i.e. the day a user picks.
 */
const LOCAL_DAY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const localDayOf = (ms) => LOCAL_DAY.format(new Date(ms));

/** The calendar day before `day` — string arithmetic, no zone involved. */
const dayBefore = (day) =>
  new Date(Date.parse(`${day}T00:00:00Z`) - DAY_MS).toISOString().slice(0, 10);

/**
 * Two instants, one per sign of UTC offset. One alone cannot fail everywhere,
 * and a test that can only fail in one of the four zones makes the other three
 * runs theatre:
 *
 *  - WEST — `2026-08-12T01:00:00Z` is 2026-08-11 21:00 in New York: the
 *    reader's day is still Aug 11 while the UTC day is already Aug 12.
 *  - EAST — `2026-08-11T23:00:00Z` is 2026-08-12 08:00 in Tokyo (11:00 in
 *    Auckland): the reader's day is Aug 12 while the UTC day is still Aug 11.
 *
 * Under `TZ=UTC` both instants agree with the UTC day, which is why UTC is the
 * positive control — it passed before this fix and must pass after it.
 */
const WEST = Date.UTC(2026, 7, 12, 1, 0, 0);
const EAST = Date.UTC(2026, 7, 11, 23, 0, 0);
const INSTANTS = [
  ["west of UTC (2026-08-12T01:00:00Z)", WEST],
  ["east of UTC (2026-08-11T23:00:00Z)", EAST],
];

test("the day deadlines bucket against is the reader's own calendar day", () => {
  for (const [label, instant] of INSTANTS) {
    assert.equal(localTodayISO(instant), localDayOf(instant), label);
  }
});

test("a deadline the user picks as TODAY never renders overdue", () => {
  for (const [label, instant] of INSTANTS) {
    // Exactly what the sheet does: the date input hands back the reader's local
    // day, `dueDayISO` turns it into the end of that day, and the card buckets
    // the result against the clock.
    const picked = localDayOf(instant);
    const stored = dueDayISO(picked);
    const state = dueInfo(stored, localTodayISO(instant));
    assert.notEqual(state, null, label);
    assert.equal(duePhrase(state.daysLeft), "due today", label);
    assert.equal(state.state, "soon", label);
  }
});

test("a deadline whose day has passed for the reader is overdue by exactly one", () => {
  for (const [label, instant] of INSTANTS) {
    const stored = dueDayISO(dayBefore(localDayOf(instant)));
    const state = dueInfo(stored, localTodayISO(instant));
    assert.notEqual(state, null, label);
    assert.equal(duePhrase(state.daysLeft), "overdue 1d", label);
    assert.equal(state.state, "overdue", label);
  }
});
