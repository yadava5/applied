/**
 * Unit tests for the Gmail sync-state reading: staleness, the "last synced"
 * labels, and what a sync actually did.
 *
 * Three bugs are guarded here, all of them user-visible:
 *
 *  1. The dashboard auto-synced only when the board was EMPTY (`total === 0`),
 *     so an account with rows never picked up new mail by itself and the owner
 *     re-synced by hand on every visit. The replacement is `isStale`, and its
 *     edge cases (never synced, unreadable, clock skew) decide whether the
 *     product hammers Gmail or goes silent — so they are asserted, not assumed.
 *
 *  2. Relative time rendered during SSR is how this app produced React #418 in
 *     production. The property that makes it impossible here is that the label
 *     the SERVER renders is a pure function of the input string's characters:
 *     `process.env.TZ` must not change a single expectation. As in
 *     `dates.test.mjs` these are ABSOLUTE expected strings — two timezones can
 *     agree on the wrong one — plus a positive control that actually mutates
 *     `process.env.TZ` between calls and asserts the output does not move.
 *
 *  3. `POST /gmail/sync` returns counts nobody rendered, so filing 100 mined
 *     messages reported nothing at all. `filedSummary` is the one reading of
 *     those counts, shared by the inbox's file action, the rail's re-sync and
 *     the dashboard's auto-sync.
 *
 * Run:  npm run test:unit
 *       TZ=UTC npm run test:unit
 *       TZ=America/New_York npm run test:unit
 *
 * Requires Node >= 22.6 (built-in TypeScript type stripping loads the `.ts`
 * module under test). `frontend-ci.yml` still pins Node 20, so — like
 * `dates.test.mjs` — this is deliberately NOT wired into CI yet.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  NOT_SYNCED_YET,
  STALE_AFTER_MS,
  absoluteInstant,
  absoluteSyncLabel,
  filedSummary,
  isStale,
  parseInstant,
  relativeSince,
  relativeSyncLabel,
} from "../../lib/gmail/sync-state.ts";

const TZ = process.env.TZ ?? "(system default)";

/** The exact shape the backend emits — `_iso_utc`, explicit offset, never naive. */
const SYNCED_AT = "2026-08-10T19:26:13+00:00";
const SYNCED_MS = Date.UTC(2026, 7, 10, 19, 26, 13);

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// --- parsing ---------------------------------------------------------------

test(`an explicit-offset instant parses to the same epoch in any zone [TZ=${TZ}]`, () => {
  assert.equal(parseInstant(SYNCED_AT), SYNCED_MS);
  assert.equal(parseInstant("2026-08-10T19:26:13Z"), SYNCED_MS);
  // Same instant, expressed in US Eastern — must land on the identical epoch.
  assert.equal(parseInstant("2026-08-10T15:26:13-04:00"), SYNCED_MS);
});

test(`a zone-less timestamp is read as UTC, never as local time [TZ=${TZ}]`, () => {
  // If the backend ever regressed to a naive `datetime.utcnow()` string, a
  // browser in US Eastern reading it as local would report a just-finished sync
  // as "in 4 hours". The parse defends against that directionally.
  assert.equal(parseInstant("2026-08-10T19:26:13"), SYNCED_MS);
});

test(`absent, malformed, and calendar-date input parse to null [TZ=${TZ}]`, () => {
  for (const bad of [
    null,
    undefined,
    "",
    "   ",
    "never",
    "10/08/2026",
    "2026-08-10", // a calendar date is a `dates.ts` value, not an instant
    "2026-08-10T", // truncated
    "2026-13-40T99:99:99Z", // shaped right, not a real time
  ]) {
    assert.equal(parseInstant(bad), null, `parseInstant(${JSON.stringify(bad)})`);
  }
});

// --- staleness -------------------------------------------------------------

test(`the staleness threshold is 30 minutes and sits above the tab cooldown [TZ=${TZ}]`, () => {
  assert.equal(STALE_AFTER_MS, 30 * 60 * 1000);
  // `GmailSyncTrigger`'s sessionStorage cooldown is 10 minutes. If the
  // threshold ever dropped below it the cooldown would become the real gate and
  // the stated threshold would be decorative.
  assert.ok(STALE_AFTER_MS >= 10 * 60 * 1000);
});

test(`a board synced inside the window is NOT re-synced [TZ=${TZ}]`, () => {
  assert.equal(isStale(SYNCED_AT, SYNCED_MS), false, "synced this instant");
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + MINUTE), false);
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + 29 * MINUTE), false);
  // This is the case the old `total === 0` rule got wrong: a populated board,
  // synced an hour ago, must sync again.
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + 30 * MINUTE), true, "exactly at the threshold");
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + HOUR), true);
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + 7 * DAY), true);
});

test(`never synced, or unreadable, counts as stale [TZ=${TZ}]`, () => {
  // A fresh connection has no row yet — the connect-time backfill must still run.
  assert.equal(isStale(null, SYNCED_MS), true);
  assert.equal(isStale(undefined, SYNCED_MS), true);
  assert.equal(isStale("", SYNCED_MS), true);
  assert.equal(isStale("not a timestamp", SYNCED_MS), true);
});

test(`a timestamp from the future is clock skew, not staleness [TZ=${TZ}]`, () => {
  // Treating it as stale would fire a sync on every visit for as long as the
  // browser and backend clocks disagree.
  assert.equal(isStale(SYNCED_AT, SYNCED_MS - MINUTE), false);
  assert.equal(isStale(SYNCED_AT, SYNCED_MS - DAY), false);
});

test(`the threshold is a parameter, so callers can be tested at any window [TZ=${TZ}]`, () => {
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + 5 * MINUTE, MINUTE), true);
  assert.equal(isStale(SYNCED_AT, SYNCED_MS + 5 * MINUTE, HOUR), false);
});

// --- the labels ------------------------------------------------------------

test(`the server-rendered label is absolute and UTC [TZ=${TZ}]`, () => {
  assert.equal(absoluteInstant(SYNCED_AT), "2026-08-10 19:26 UTC");
  assert.equal(absoluteSyncLabel(SYNCED_AT), "last synced 2026-08-10 19:26 UTC");
  // Single-digit month/day/hour/minute must be zero-padded, not locale-formatted.
  assert.equal(absoluteInstant("2026-01-02T03:04:05Z"), "2026-01-02 03:04 UTC");
  // The same instant written in another offset renders the same UTC wall time.
  assert.equal(absoluteInstant("2026-08-10T15:26:13-04:00"), "2026-08-10 19:26 UTC");
  assert.equal(absoluteInstant(null), null);
  assert.equal(absoluteSyncLabel(null), NOT_SYNCED_YET);
});

test(`the label the server renders cannot disagree with the browser's first render [TZ=${TZ}]`, () => {
  // The hydration property, as a positive control: mutate the process timezone
  // between calls (Node honours a runtime `process.env.TZ` change) and assert
  // the server-side label does not move. A UTC server and an Eastern browser
  // rendering different text is precisely React #418.
  const original = process.env.TZ;
  try {
    const seen = [];
    for (const tz of ["UTC", "America/New_York", "Asia/Kolkata", "Pacific/Kiritimati"]) {
      process.env.TZ = tz;
      // Prove the mutation actually took effect — otherwise this test asserts
      // nothing at all and would pass against a broken formatter.
      const localHour = new Date(SYNCED_MS).getHours();
      seen.push(localHour);
      assert.equal(
        absoluteSyncLabel(SYNCED_AT),
        "last synced 2026-08-10 19:26 UTC",
        `absoluteSyncLabel under TZ=${tz}`,
      );
      // The relative label is likewise a function of (instant, now) only.
      assert.equal(
        relativeSyncLabel(SYNCED_AT, SYNCED_MS + 3 * MINUTE),
        "last synced 3 minutes ago",
        `relativeSyncLabel under TZ=${tz}`,
      );
    }
    assert.ok(
      new Set(seen).size > 1,
      `process.env.TZ did not take effect — local hours were ${JSON.stringify(seen)}`,
    );
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test(`relative time takes "now" explicitly — it can never read the clock itself [TZ=${TZ}]`, () => {
  // A one-argument call would be the hydration bug: `relativeSince` would have
  // to consult `Date.now()`, which differs between the server render and the
  // browser's hydration by however long the response took.
  assert.equal(relativeSince.length, 2);
  assert.equal(relativeSyncLabel.length, 2);
  assert.equal(absoluteSyncLabel.length, 1);
});

test(`relative buckets read the way a person would say them [TZ=${TZ}]`, () => {
  const at = (offset) => relativeSince(SYNCED_AT, SYNCED_MS + offset);

  assert.equal(at(0), "just now");
  assert.equal(at(59 * 1000), "just now");
  assert.equal(at(MINUTE), "1 minute ago");
  assert.equal(at(3 * MINUTE), "3 minutes ago");
  assert.equal(at(59 * MINUTE), "59 minutes ago");
  assert.equal(at(HOUR), "1 hour ago");
  assert.equal(at(5 * HOUR), "5 hours ago");
  assert.equal(at(DAY), "1 day ago");
  assert.equal(at(6 * DAY), "6 days ago");
  // Past a week the count stops being useful and the date itself takes over.
  assert.equal(at(7 * DAY), "on 2026-08-10 19:26 UTC");
  // Clock skew reads as "just now" rather than a negative or future phrasing.
  assert.equal(at(-5 * MINUTE), "just now");

  assert.equal(relativeSince(null, SYNCED_MS), null);
  assert.equal(relativeSyncLabel(null, SYNCED_MS), NOT_SYNCED_YET);
  assert.equal(relativeSyncLabel("garbage", SYNCED_MS), NOT_SYNCED_YET);
});

// --- what the sync did -----------------------------------------------------

test(`"filed N" is derived from the sync outcome the backend returns [TZ=${TZ}]`, () => {
  // The backend's SyncResponse: created / updated / applications / scanned.
  assert.equal(
    filedSummary({ created: 3, updated: 1, applications: 12, scanned: 200 }),
    "3 filed, 1 already known",
  );
  assert.equal(filedSummary({ created: 3, updated: 0, applications: 3, scanned: 200 }), "3 filed");
  assert.equal(filedSummary({ created: 1, updated: 0, applications: 1, scanned: 12 }), "1 filed");
});

test(`a mine that filed nothing says so honestly, never "up to date" by accident [TZ=${TZ}]`, () => {
  // Everything found was already on the board.
  assert.equal(
    filedSummary({ created: 0, updated: 4, applications: 12, scanned: 200 }),
    "nothing new · 4 already known",
  );
  // Nothing cleared the confidence gates. Naming `scanned` is what stops this
  // reading as a failure — the sync ran, it just had nothing to file.
  assert.equal(
    filedSummary({ created: 0, updated: 0, applications: 12, scanned: 200 }),
    "nothing to file · 200 scanned",
  );
  assert.equal(
    filedSummary({ created: 0, updated: 0, applications: 0, scanned: 0 }),
    "nothing to file",
  );
});

test(`a partial or nonsense body degrades to a sentence, not "undefined filed" [TZ=${TZ}]`, () => {
  for (const body of [null, undefined, {}, { created: null }, { created: "3" }, { created: NaN }]) {
    assert.equal(filedSummary(body), "nothing to file", `filedSummary(${JSON.stringify(body)})`);
  }
  // Negative / fractional counts can only be a backend bug; never render them.
  assert.equal(filedSummary({ created: -2, updated: 0, scanned: 0 }), "nothing to file");
  assert.equal(filedSummary({ created: 2.7, updated: 0, scanned: 0 }), "2 filed");
  // A body that carries only `scanned` still reports the scan.
  assert.equal(filedSummary({ scanned: 40 }), "nothing to file · 40 scanned");
});
