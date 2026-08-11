/**
 * The deadline derivation every surface shares (`lib/dashboard/deadline.ts`):
 * the card tag, the detail sheet and the pulse cell all read `dueInfo` /
 * `duePhrase` / `deadlinePulse`, so what is asserted here is asserted for all
 * three at once.
 *
 * The properties that matter:
 *  - no `due_at`, no claim: absent/malformed input yields null, never a guess;
 *  - the state boundaries sit exactly on DUE_SOON_DAYS and on "yesterday";
 *  - `dueDayISO` writes the END of the picked day (a deadline is "by then",
 *    not "at midnight before it") and round-trips its calendar prefix;
 *  - the pulse buckets count only rows with usable deadlines and name the
 *    smallest-days-left row as most urgent (overdue outranks everything).
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  DUE_SOON_DAYS,
  deadlinePulse,
  dueDayISO,
  dueInfo,
  duePhrase,
  dueSourceLabel,
} from "../../lib/dashboard/deadline.ts";

const TODAY = "2026-08-11";

test("dueInfo: no date, no claim", () => {
  assert.equal(dueInfo(null, TODAY), null);
  assert.equal(dueInfo(undefined, TODAY), null);
  assert.equal(dueInfo("", TODAY), null);
  assert.equal(dueInfo("not-a-date", TODAY), null);
  assert.equal(dueInfo("2026-13-40T00:00:00Z", TODAY), null);
});

test("dueInfo: the three states and their exact boundaries", () => {
  assert.deepEqual(dueInfo("2026-08-10T23:59:59Z", TODAY), { state: "overdue", daysLeft: -1 });
  assert.deepEqual(dueInfo("2026-08-11T23:59:59Z", TODAY), { state: "soon", daysLeft: 0 });
  // The last "soon" day is exactly DUE_SOON_DAYS out…
  assert.deepEqual(dueInfo("2026-08-13T23:59:59Z", TODAY), {
    state: "soon",
    daysLeft: DUE_SOON_DAYS,
  });
  // …and one more day is "ahead".
  assert.deepEqual(dueInfo("2026-08-14T23:59:59Z", TODAY), { state: "ahead", daysLeft: 3 });
});

test("dueInfo reads the calendar day the string states, time and zone ignored", () => {
  // Same rule as dates.ts: the claim is the stated day, identically on server
  // and client — a time component must not shift the bucket.
  assert.deepEqual(dueInfo("2026-08-13", TODAY), dueInfo("2026-08-13T01:00:00Z", TODAY));
});

test("dueDayISO: end of the picked day, calendar prefix intact", () => {
  assert.equal(dueDayISO("2026-08-15"), "2026-08-15T23:59:59Z");
  assert.equal(dueDayISO(" 2026-08-15 "), "2026-08-15T23:59:59Z");
  assert.equal(dueDayISO(""), null);
  assert.equal(dueDayISO("08/15/2026"), null);
  assert.equal(dueDayISO("2026-99-15"), null);
});

test("duePhrase: arithmetic, not urgency inference", () => {
  assert.equal(duePhrase(-3), "overdue 3d");
  assert.equal(duePhrase(0), "due today");
  assert.equal(duePhrase(1), "due in 1d");
  assert.equal(duePhrase(9), "due in 9d");
});

test("dueSourceLabel: two claims, nothing else dressed up as either", () => {
  assert.equal(dueSourceLabel("user"), "set by you");
  assert.equal(dueSourceLabel("mail"), "from your mail");
  assert.equal(dueSourceLabel(null), null);
  assert.equal(dueSourceLabel("sync"), null);
});

test("deadlinePulse: buckets tracked rows only, most urgent named by smallest days-left", () => {
  const rows = [
    { company: "No Deadline Co" },
    { company: "Broken Co", due_at: "soon-ish" },
    { company: "Later Co", due_at: "2026-08-20T23:59:59Z" },
    { company: "Soon Co", due_at: "2026-08-13T23:59:59Z" },
    { company: "Overdue Co", due_at: "2026-08-09T23:59:59Z" },
    { company: "More Overdue Co", due_at: "2026-08-05T23:59:59Z" },
  ];
  const pulse = deadlinePulse(rows, TODAY);
  assert.deepEqual(pulse, {
    overdue: 2,
    soon: 1,
    later: 1,
    total: 4,
    urgent: { company: "More Overdue Co", daysLeft: -6 },
  });
});

test("deadlinePulse: an empty board is honestly empty", () => {
  assert.deepEqual(deadlinePulse([], TODAY), {
    overdue: 0,
    soon: 0,
    later: 0,
    total: 0,
    urgent: null,
  });
});
