/**
 * The notification preferences, end to end through the pure half of their
 * wiring: how a stored blob is read (`readNotificationPrefs`), and what the
 * two flags then decide on the board (`buildSubtitle`, `reviewSlotFor`).
 *
 * WHY THIS FILE EXISTS. Before #216,
 * `grep "readNotificationPrefs\|reviewAlerts\|buildSubtitle" tests/` matched
 * NOTHING. Both toggles drive real, visibly different behaviour, and not one
 * line of it was executable: `readNotificationPrefs` could have returned
 * constants, or `buildSubtitle` ignored its `weekly` argument, and every suite
 * in this repo would have stayed green. `tests/e2e/shell.spec.ts` drives both
 * queue placements, but from a URL parameter — it proves the SLOTS work, never
 * that a preference reaches them.
 *
 * The cases below are chosen to be NON-DEGENERATE on purpose. A quiet board —
 * `thisWeek: 0`, `needsReview: 0` — renders both branches of both prefs
 * identically, which is a data condition rather than a defect (#216) and the
 * reason these controls look inert on a real account. A test written on those
 * values would pass against the wiring being deleted.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { buildSubtitle, reviewSlotFor } from "../../lib/dashboard/boardPrefs.ts";
import { parseDemoNotificationPrefs } from "../../lib/demo/notificationPrefs.ts";
import { readNotificationPrefs } from "../../lib/settings/notifications.ts";

/** A board with three filings this week — the value that makes the two
 *  `weekly` branches differ. */
const busy = { total: 17, thisWeek: 3, inMotion: 14, offers: 0, closed: 3 };
/** The same board on a quiet week: `thisWeek` 0, where they cannot differ. */
const quiet = { ...busy, thisWeek: 0 };

test("readNotificationPrefs defaults a never-set preference to off", () => {
  assert.deepEqual(readNotificationPrefs({}), { weekly: false, reviewAlerts: false });
});

test("readNotificationPrefs is defensive about a malformed blob", () => {
  // `null` metadata, a null blob, and a truthy-but-not-`true` value all mean
  // "not switched on". The strict `=== true` is what makes the last one safe:
  // a string "yes" out of a hand-edited user record must not read as on.
  assert.deepEqual(readNotificationPrefs({ notifications: null }), {
    weekly: false,
    reviewAlerts: false,
  });
  assert.deepEqual(readNotificationPrefs({ notifications: { weekly: "yes" } }), {
    weekly: false,
    reviewAlerts: false,
  });
  assert.deepEqual(readNotificationPrefs({ notifications: { weekly: 1, reviewAlerts: "true" } }), {
    weekly: false,
    reviewAlerts: false,
  });
});

test("readNotificationPrefs carries both flags through when they are really set", () => {
  assert.deepEqual(readNotificationPrefs({ notifications: { weekly: true, reviewAlerts: true } }), {
    weekly: true,
    reviewAlerts: true,
  });
  assert.deepEqual(readNotificationPrefs({ notifications: { weekly: true } }), {
    weekly: true,
    reviewAlerts: false,
  });
});

test("weekly ON folds the this-week count into the subtitle", () => {
  assert.equal(buildSubtitle(busy, true), "17 filed · +3 this wk · 14 open · 0 offers");
});

test("weekly OFF leaves the same board's subtitle without it", () => {
  const off = buildSubtitle(busy, false);
  assert.equal(off, "17 filed · 14 open · 0 offers");
  // The whole point of the pref: the two branches must not agree here.
  assert.notEqual(off, buildSubtitle(busy, true));
});

test("a zero this-week count folds in nothing even with weekly ON", () => {
  // The documented degenerate case: "+0 this wk" is not news, so both
  // branches render the same line. Asserted so the behaviour is deliberate
  // rather than something a future edit can quietly change.
  assert.equal(buildSubtitle(quiet, true), buildSubtitle(quiet, false));
  assert.equal(buildSubtitle(quiet, true), "17 filed · 14 open · 0 offers");
});

test("the subtitle pluralises offers, with and without the weekly fold", () => {
  assert.equal(buildSubtitle({ ...busy, offers: 1 }, false), "17 filed · 14 open · 1 offer");
  assert.equal(
    buildSubtitle({ ...busy, offers: 2 }, true),
    "17 filed · +3 this wk · 14 open · 2 offers",
  );
});

test("reviewAlerts decides which slot the needs-review queue lands in", () => {
  // ON interrupts the board (above the stage groups); OFF waits below them.
  assert.equal(reviewSlotFor({ weekly: false, reviewAlerts: true }), "before");
  assert.equal(reviewSlotFor({ weekly: false, reviewAlerts: false }), "after");
  // …and `weekly` has no say in it.
  assert.equal(reviewSlotFor({ weekly: true, reviewAlerts: true }), "before");
  assert.equal(reviewSlotFor({ weekly: true, reviewAlerts: false }), "after");
});

test("the demo twin's cookie parses through the product's own reader", () => {
  const on = JSON.stringify({ weekly: true, reviewAlerts: true });
  assert.deepEqual(parseDemoNotificationPrefs(on), { weekly: true, reviewAlerts: true });
  // The value is written URL-encoded; both forms must read the same, because
  // whether the framework hands back a decoded value is not this module's to
  // assume.
  assert.deepEqual(parseDemoNotificationPrefs(encodeURIComponent(on)), {
    weekly: true,
    reviewAlerts: true,
  });
});

test("an absent or unreadable demo cookie means both flags off, never a crash", () => {
  const off = { weekly: false, reviewAlerts: false };
  assert.deepEqual(parseDemoNotificationPrefs(undefined), off);
  assert.deepEqual(parseDemoNotificationPrefs(""), off);
  assert.deepEqual(parseDemoNotificationPrefs("not json"), off);
  assert.deepEqual(parseDemoNotificationPrefs("%E0%A4%A"), off); // malformed escape
  assert.deepEqual(parseDemoNotificationPrefs('{"weekly":"yes"}'), off);
});
