/**
 * Unit tests for the shared dashboard date formatter.
 *
 * The bug these guard: `applied_date` is date-only ("2026-08-10" → UTC
 * midnight) while `created_at` is a naive timestamp ("2026-08-10T21:19:13" →
 * local), so a `Date`-based formatter rendered "Aug 9" on a card and
 * "Aug 10, 2026" in the feed for one row, and disagreed between the UTC server
 * and the Eastern browser (React #418 text hydration mismatch).
 *
 * So we assert ABSOLUTE strings, not merely that the two inputs agree — two
 * inputs can agree on the wrong month. CI/dev must run this under at least two
 * timezones; `process.env.TZ` must not change a single expectation.
 *
 * Run:  npm run test:unit
 *       TZ=UTC npm run test:unit
 *       TZ=America/New_York npm run test:unit
 *
 * Requires Node >= 22.6 (built-in TypeScript type stripping loads the `.ts`
 * module under test; the glob in the script needs >= 21). `frontend-ci.yml`
 * still pins Node 20, so this is deliberately NOT wired into CI yet — bumping
 * the CI runtime is a separate call.
 *
 * Written as `.mjs` (not `.ts`) on purpose: tsconfig's `include` list has no
 * `.mjs` glob, so `tsc --noEmit` stays clean without adding
 * `allowImportingTsExtensions` to the shared project config, while Node's
 * built-in type stripping still loads the real `.ts` module under test.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { NO_DATE, filedAt, longDate, shortDate } from "../../lib/dashboard/dates.ts";

const TZ = process.env.TZ ?? "(system default)";

test(`date-only and naive-timestamp agree on the same calendar day [TZ=${TZ}]`, () => {
  // The exact pair from production: one row's applied_date and created_at.
  assert.equal(shortDate("2026-08-10"), "Aug 10");
  assert.equal(shortDate("2026-08-10T21:19:13"), "Aug 10");
  assert.equal(shortDate("2026-08-10"), shortDate("2026-08-10T21:19:13"));

  assert.equal(longDate("2026-08-10"), "Aug 10, 2026");
  assert.equal(longDate("2026-08-10T21:19:13"), "Aug 10, 2026");
  assert.equal(longDate("2026-08-10"), longDate("2026-08-10T21:19:13"));
});

test(`output never depends on the process timezone [TZ=${TZ}]`, () => {
  // A UTC-midnight instant is the case that flipped to the previous day in
  // US/Eastern, and a late-evening local time is the case that flipped forward
  // in UTC. Both must read as the day their own characters state.
  assert.equal(shortDate("2026-08-10T00:00:00Z"), "Aug 10");
  assert.equal(shortDate("2026-01-01T00:00:00Z"), "Jan 1");
  assert.equal(longDate("2026-12-31T23:59:59"), "Dec 31, 2026");
  assert.equal(longDate("2026-01-01"), "Jan 1, 2026");
});

test(`month names map from the 1-based month, not an off-by-one index [TZ=${TZ}]`, () => {
  const expected = [
    "Jan 1",
    "Feb 1",
    "Mar 1",
    "Apr 1",
    "May 1",
    "Jun 1",
    "Jul 1",
    "Aug 1",
    "Sep 1",
    "Oct 1",
    "Nov 1",
    "Dec 1",
  ];
  for (let month = 1; month <= 12; month += 1) {
    const iso = `2026-${String(month).padStart(2, "0")}-01`;
    assert.equal(shortDate(iso), expected[month - 1]);
  }
});

test(`days render without a leading zero [TZ=${TZ}]`, () => {
  assert.equal(shortDate("2026-08-09"), "Aug 9");
  assert.equal(shortDate("2026-08-31"), "Aug 31");
});

test(`absent or malformed input renders the em-dash placeholder [TZ=${TZ}]`, () => {
  for (const bad of [
    undefined,
    null,
    "",
    "not a date",
    "10/08/2026",
    "2026-13-01", // month out of range
    "2026-00-10", // month out of range
    "2026-08-00", // day out of range
    "2026-08-45", // day out of range
    "2026-8-1", // unpadded — not the shape the API emits
  ]) {
    assert.equal(shortDate(bad), NO_DATE, `shortDate(${JSON.stringify(bad)})`);
    assert.equal(longDate(bad), NO_DATE, `longDate(${JSON.stringify(bad)})`);
  }
});

test(`filedAt prefers the mail's received date over the row's creation time [TZ=${TZ}]`, () => {
  assert.equal(
    filedAt({ applied_date: "2026-08-10", created_at: "2026-08-11T04:00:00" }),
    "2026-08-10",
  );
  assert.equal(filedAt({ applied_date: null, created_at: "2026-08-11T04:00:00" }), "2026-08-11T04:00:00");
  assert.equal(filedAt({ created_at: "2026-08-11T04:00:00" }), "2026-08-11T04:00:00");
});
