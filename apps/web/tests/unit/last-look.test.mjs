/**
 * The "since you last looked" derivation (`lib/dashboard/lastLook.ts`) — the
 * pure half of the dashboard's change ledger.
 *
 * The properties that matter, and that the surface's honesty rests on:
 *
 *  - a claim needs evidence: a row is "filed" because it was not on the board
 *    you acknowledged, "moved" because its BOARD COLUMN WORD changed, and
 *    carries a deadline only when the classifier read one out of mail;
 *  - a sync touch is not a change: a status that lands in the same column
 *    produces nothing, which is what keeps `updated_at`-shaped noise out;
 *  - a deadline the user typed is never news (`due_source: "user"`);
 *  - a board that was RE-DATED is not a board of new deadlines: a deadline is
 *    measured against its own row's filed day, so a pass that moves both by the
 *    same number of days has moved nothing (/demo re-dates its offset fixtures
 *    onto the reader's local day, `lib/demo/redate.ts`);
 *  - under a partial board, a row that scrolled INTO the loaded window is not
 *    a row that arrived — `floor` suppresses it rather than guessing;
 *  - one entry per row, so the ledger's own counts cannot double-count;
 *  - a record from another user, another version, or a corrupt one reads as no
 *    record at all, which is the first-visit path.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  LAST_LOOK_VERSION,
  changesSince,
  floorOf,
  groupChanges,
  momentLabel,
  momentShortLabel,
  parseLastLook,
  snapshotOf,
} from "../../lib/dashboard/lastLook.ts";

const SCOPE = "user-1";

/** A board row as the caller projects it (`toChangeRow`). */
function row(id, stage, filed, extra = {}) {
  return {
    id,
    company: `Company ${id}`,
    position: `Engineer ${id}`,
    stage,
    filed,
    ...extra,
  };
}

const BOARD = [
  row(1, "applied", "2026-08-10"),
  row(2, "interviewing", "2026-08-04"),
  row(3, "closed", "2026-07-02"),
];

/** The same board with one mail-read deadline on it — the only rows the
 *  deadline claim can be about. */
const DATED = [
  BOARD[0],
  row(2, "interviewing", "2026-08-04", {
    dueAt: "2026-08-13T23:59:59Z",
    dueSource: "mail",
  }),
  BOARD[2],
];

/** The calendar day of `value`, moved `days` on; everything after the day is
 *  left exactly as it was. */
function shiftDay(value, days) {
  const moved = new Date(Date.parse(`${value.slice(0, 10)}T00:00:00Z`) + days * 86_400_000);
  return `${moved.toISOString().slice(0, 10)}${value.slice(10)}`;
}

/** Every row's filed day AND its deadline moved by the same `days` — what
 *  /demo's re-dating pass does to a store built for a different day. */
function reDated(rows, days) {
  return rows.map((current) => ({
    ...current,
    filed: shiftDay(current.filed, days),
    ...(typeof current.dueAt === "string" ? { dueAt: shiftDay(current.dueAt, days) } : {}),
  }));
}

test("snapshotOf: ids and stage words only — no company, role or note", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  assert.equal(snap.v, LAST_LOOK_VERSION);
  assert.equal(snap.scope, SCOPE);
  assert.equal(snap.at, 1_000);
  assert.deepEqual(snap.rows, {
    1: { s: "applied" },
    2: { s: "interviewing" },
    3: { s: "closed" },
  });
  assert.equal(JSON.stringify(snap).includes("Company"), false);
});

test("floorOf: only a partial board carries a floor, and it is the oldest day", () => {
  assert.equal(floorOf(BOARD, false), null);
  assert.equal(floorOf(BOARD, true), "2026-07-02");
  // An unparsable filed date cannot lower the floor, and an empty board has none.
  assert.equal(floorOf([row(9, "applied", "not-a-date")], true), null);
  assert.equal(floorOf([], true), null);
});

test("nothing changed → no entries at all", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  assert.deepEqual(changesSince(BOARD, snap), []);
});

test("a row that was not there is filed, and carries a mail deadline with it", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const arrived = row(4, "interviewing", "2026-08-11", {
    dueAt: "2026-08-13T23:59:59Z",
    dueSource: "mail",
  });
  const entries = changesSince([arrived, ...BOARD], snap);
  assert.equal(entries.length, 1);
  assert.deepEqual(entries[0], {
    id: 4,
    company: "Company 4",
    position: "Engineer 4",
    kind: "filed",
    to: "interviewing",
    dueAt: "2026-08-13T23:59:59Z",
  });
});

test("a stage change is a move, named from and to", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const moved = changesSince(
    [row(1, "interviewing", "2026-08-10"), BOARD[1], BOARD[2]],
    snap,
  );
  assert.equal(moved.length, 1);
  assert.equal(moved[0].kind, "moved");
  assert.equal(moved[0].from, "applied");
  assert.equal(moved[0].to, "interviewing");
});

test("a status that lands in the SAME column is not a change", () => {
  // The caller passes the word the board renders, so `interview` →
  // `interviewing`, or `rejected` → `withdrawn` (both "closed"), never reach
  // here as a difference. This is what keeps a sync's touch out of the ledger.
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  assert.deepEqual(changesSince([...BOARD], snap), []);
  const restated = [row(3, "closed", "2026-07-02"), BOARD[0], BOARD[1]];
  assert.deepEqual(changesSince(restated, snap), []);
});

test("a deadline counts only when the classifier read it out of mail", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const userSet = [
    row(1, "applied", "2026-08-10", { dueAt: "2026-08-20T23:59:59Z", dueSource: "user" }),
    BOARD[1],
    BOARD[2],
  ];
  assert.deepEqual(changesSince(userSet, snap), []);

  const mailRead = [
    row(1, "applied", "2026-08-10", { dueAt: "2026-08-20T23:59:59Z", dueSource: "mail" }),
    BOARD[1],
    BOARD[2],
  ];
  const entries = changesSince(mailRead, snap);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "deadline");
  assert.equal(entries[0].dueAt, "2026-08-20T23:59:59Z");

  // The same mail-read date, already known, says nothing the second time.
  assert.deepEqual(changesSince(mailRead, snapshotOf(mailRead, SCOPE, 1_000, false)), []);
});

test("snapshotOf: a stored deadline carries the filed day it is measured against", () => {
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  assert.deepEqual(snap.rows, {
    1: { s: "applied" },
    2: { s: "interviewing", d: "2026-08-13T23:59:59Z", f: "2026-08-04" },
    3: { s: "closed" },
  });
  // `f` measures `d` and nothing else, so a row with no deadline stores none.
});

test("a board re-dated onto another day is not a board of new deadlines", () => {
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  // BOTH directions, because both happen: /demo's re-dating moves its fixtures
  // a day EARLIER for a reader west of UTC and a day LATER for one far enough
  // east, and at any instant one of those two is what a reader is getting.
  assert.deepEqual(changesSince(reDated(DATED, -1), snap), []);
  assert.deepEqual(changesSince(reDated(DATED, 1), snap), []);
  // Across a year boundary too, where the day strings look nothing alike.
  const newYear = [
    row(1, "interviewing", "2026-12-28", {
      dueAt: "2026-12-31T23:59:59Z",
      dueSource: "mail",
    }),
  ];
  const turned = snapshotOf(newYear, SCOPE, 1_000, false);
  assert.deepEqual(changesSince(reDated(newYear, 1), turned), []);
  assert.deepEqual(changesSince(reDated(newYear, -1), turned), []);
});

test("a deadline that moves while its row stays put is still news", () => {
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  const moved = [
    BOARD[0],
    row(2, "interviewing", "2026-08-04", {
      dueAt: "2026-08-14T23:59:59Z",
      dueSource: "mail",
    }),
    BOARD[2],
  ];
  const entries = changesSince(moved, snap);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "deadline");
  assert.equal(entries[0].dueAt, "2026-08-14T23:59:59Z");
});

test("a deadline that moves further than its row is news", () => {
  // The row moved one day, its deadline two: the deadline moved relative to the
  // row that carries it, which is the fact the ledger reports.
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  const drifted = [
    row(2, "interviewing", "2026-08-05", {
      dueAt: "2026-08-15T23:59:59Z",
      dueSource: "mail",
    }),
  ];
  const entries = changesSince(drifted, snap);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "deadline");
});

test("a deadline the snapshot never knew is news however the board is dated", () => {
  // The suppression above can only ever silence a date the snapshot HELD. A row
  // that gained its first mail-read deadline says so on any day basis.
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const entries = changesSince(reDated(DATED, -1), snap);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "deadline");
  assert.equal(entries[0].id, 2);
});

test("the granularity is the calendar day, here as everywhere else", () => {
  // `deadline.ts`: every surface renders and buckets the DAY a deadline states.
  // An instant that moves inside one day changes nothing the board can show, so
  // the ledger does not announce it — the same rule that keeps `interview` →
  // `interviewing` out of "moved".
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  const sameDay = [
    BOARD[0],
    row(2, "interviewing", "2026-08-04", {
      dueAt: "2026-08-13T09:00:00Z",
      dueSource: "mail",
    }),
    BOARD[2],
  ];
  assert.deepEqual(changesSince(sameDay, snap), []);
});

test("a stored deadline with no filed day compares the dates outright", () => {
  // A record can only reach this shape if the row's filed date was unusable
  // when the snapshot was taken. There is then nothing to measure the deadline
  // against, so the ledger reports the difference rather than guessing silence.
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  const unanchored = {
    ...snap,
    rows: { ...snap.rows, 2: { s: "interviewing", d: "2026-08-13T23:59:59Z" } },
  };
  const entries = changesSince(reDated(DATED, -1), unanchored);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "deadline");
});

test("one entry per row: a row that moved AND gained a deadline is one move", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const both = [
    row(1, "interviewing", "2026-08-10", { dueAt: "2026-08-13T23:59:59Z", dueSource: "mail" }),
    BOARD[1],
    BOARD[2],
  ];
  const entries = changesSince(both, snap);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "moved");
  assert.equal(entries[0].dueAt, "2026-08-13T23:59:59Z");
});

test("a row that scrolled into a PARTIAL board is not a row that arrived", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, true);
  assert.equal(snap.floor, "2026-07-02");

  // Older than everything the snapshot could see → it entered the window.
  const older = row(7, "applied", "2026-06-01");
  assert.deepEqual(changesSince([older, ...BOARD], snap), []);
  // Exactly at the floor is still not evidence.
  assert.deepEqual(changesSince([row(8, "applied", "2026-07-02"), ...BOARD], snap), []);
  // Newer than the floor is a real arrival.
  const arrived = changesSince([row(9, "applied", "2026-07-03"), ...BOARD], snap);
  assert.equal(arrived.length, 1);
  assert.equal(arrived[0].kind, "filed");
  // An unusable filed date claims nothing rather than guessing.
  assert.deepEqual(changesSince([row(10, "applied", "nope"), ...BOARD], snap), []);
});

test("a row that DISAPPEARED produces nothing — absence is not evidence", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  assert.deepEqual(changesSince([BOARD[0], BOARD[1]], snap), []);
});

test("groupChanges: the count is the heading, and empty groups never render", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const next = [
    row(4, "applied", "2026-08-11"),
    row(5, "applied", "2026-08-11"),
    row(1, "interviewing", "2026-08-10"),
    row(2, "interviewing", "2026-08-04", {
      dueAt: "2026-08-12T23:59:59Z",
      dueSource: "mail",
    }),
    BOARD[2],
  ];
  const groups = groupChanges(changesSince(next, snap));
  assert.deepEqual(
    groups.map((group) => [group.count, group.label]),
    [
      [2, "filed"],
      [1, "moved"],
      [1, "new deadline"],
    ],
  );
  // Read order is arrival, movement, then dates.
  assert.deepEqual(
    groups.map((group) => group.kind),
    ["filed", "moved", "deadline"],
  );
  assert.equal(groups[0].entries.length, 2);
  assert.equal(groupChanges([]).length, 0);
  // Plural only when there is more than one.
  const two = groupChanges([
    { id: 1, company: "A", position: "x", kind: "deadline", to: "applied" },
    { id: 2, company: "B", position: "y", kind: "deadline", to: "applied" },
  ]);
  assert.equal(two[0].label, "new deadlines");
});

test("parseLastLook: anything not this user's current record reads as absent", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const raw = JSON.stringify(snap);
  assert.deepEqual(parseLastLook(raw, SCOPE), snap);

  assert.equal(parseLastLook(null, SCOPE), null);
  assert.equal(parseLastLook("", SCOPE), null);
  assert.equal(parseLastLook("{not json", SCOPE), null);
  // Another user's board is not yours.
  assert.equal(parseLastLook(raw, "user-2"), null);
  // An older shape fails loudly rather than half-parsing.
  assert.equal(parseLastLook(JSON.stringify({ ...snap, v: 0 }), SCOPE), null);
  assert.equal(parseLastLook(JSON.stringify({ ...snap, at: "soon" }), SCOPE), null);
  assert.equal(parseLastLook(JSON.stringify({ ...snap, rows: null }), SCOPE), null);
  // Junk rows are dropped, the record survives.
  const messy = parseLastLook(
    JSON.stringify({ ...snap, rows: { 1: { s: "applied" }, 2: null, 3: { s: 7 } } }),
    SCOPE,
  );
  assert.deepEqual(messy.rows, { 1: { s: "applied" } });
});

test("rows the reader changed themselves report nothing, in either direction", () => {
  // The stored snapshot is patched the instant a stage write succeeds, while
  // the board only catches up on the next fetch. Between the two, a plain
  // comparison reads as a move BACKWARDS — so those ids are silent for the
  // session. See `ownChanges` in lib/dashboard/lastLookStore.ts.
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  const patched = { ...snap, rows: { ...snap.rows, 1: { s: "interviewing" } } };
  // Board still says "applied": without the guard this is a reversed claim.
  assert.equal(changesSince(BOARD, patched).length, 1);
  assert.equal(changesSince(BOARD, patched, new Set([1])).length, 0);
  // And once the board catches up, still nothing.
  const caughtUp = [row(1, "interviewing", "2026-08-10"), BOARD[1], BOARD[2]];
  assert.deepEqual(changesSince(caughtUp, patched, new Set([1])), []);
});

test("the seed flag survives a round-trip and is never invented", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, false);
  assert.equal(snap.seed, undefined);
  assert.equal(parseLastLook(JSON.stringify(snap), SCOPE).seed, undefined);
  const seeded = { ...snap, seed: true };
  assert.equal(parseLastLook(JSON.stringify(seeded), SCOPE).seed, true);
  assert.equal(parseLastLook(JSON.stringify({ ...snap, seed: "yes" }), SCOPE).seed, undefined);
});

test("parseLastLook: the filed day round-trips, and never travels without a date", () => {
  const snap = snapshotOf(DATED, SCOPE, 1_000, false);
  assert.deepEqual(parseLastLook(JSON.stringify(snap), SCOPE).rows["2"], {
    s: "interviewing",
    d: "2026-08-13T23:59:59Z",
    f: "2026-08-04",
  });
  const messy = parseLastLook(
    JSON.stringify({
      ...snap,
      rows: {
        // A filed day with no deadline measures nothing, and a non-string one
        // is not a day: both are dropped, and the row survives without them.
        1: { s: "applied", f: "2026-08-10" },
        2: { s: "interviewing", d: "2026-08-13T23:59:59Z", f: 7 },
      },
    }),
    SCOPE,
  );
  assert.deepEqual(messy.rows, {
    1: { s: "applied" },
    2: { s: "interviewing", d: "2026-08-13T23:59:59Z" },
  });
});

test("the version bump: a record written before deadlines carried a filed day is absent", () => {
  assert.equal(LAST_LOOK_VERSION, 2);
  const v1 = { v: 1, scope: SCOPE, at: 1_000, floor: null, rows: { 1: { s: "applied" } } };
  assert.equal(parseLastLook(JSON.stringify(v1), SCOPE), null);
});

test("parseLastLook round-trips a partial board's floor", () => {
  const snap = snapshotOf(BOARD, SCOPE, 1_000, true);
  assert.equal(parseLastLook(JSON.stringify(snap), SCOPE).floor, "2026-07-02");
});

test("momentLabel: today, yesterday, then the calendar day — in local time", () => {
  // Built from LOCAL parts on purpose: the marker is an instant this browser
  // wrote, so the label is the reader's own clock and the assertion must not
  // depend on the machine's zone.
  const now = new Date(2026, 7, 11, 9, 30).getTime();
  assert.equal(momentLabel(new Date(2026, 7, 11, 9, 14).getTime(), now), "today 9:14 am");
  assert.equal(momentLabel(new Date(2026, 7, 10, 18, 41).getTime(), now), "yesterday 6:41 pm");
  assert.equal(momentLabel(new Date(2026, 7, 8, 18, 41).getTime(), now), "Aug 8, 6:41 pm");
  assert.equal(momentLabel(new Date(2026, 7, 11, 0, 5).getTime(), now), "today 12:05 am");
  assert.equal(momentLabel(new Date(2026, 7, 11, 12, 0).getTime(), now), "today 12:00 pm");
  // A clock corrected backwards leaves a marker in the future; it reads as
  // today rather than as a date nobody has lived through.
  assert.equal(momentLabel(new Date(2026, 7, 12, 8, 0).getTime(), now), "today 8:00 am");
  assert.equal(momentLabel(Number.NaN, now), "your last visit");
});

test("momentShortLabel: the same buckets, each keeping the part that names its day", () => {
  // The `lg`+ overlay chip's form (#212): a bare clock is today's,
  // "yesterday" and a bare date carry their day without the clock. Bucketed
  // identically to momentLabel — a pair that disagreed about which day they
  // mean would be two claims about one marker.
  const now = new Date(2026, 7, 11, 9, 30).getTime();
  assert.equal(momentShortLabel(new Date(2026, 7, 11, 9, 14).getTime(), now), "9:14 am");
  assert.equal(momentShortLabel(new Date(2026, 7, 10, 18, 41).getTime(), now), "yesterday");
  assert.equal(momentShortLabel(new Date(2026, 7, 8, 18, 41).getTime(), now), "Aug 8");
  // The future-marker rule is shared: a corrected-backwards clock reads as
  // today's clock time, never as a day nobody has lived through.
  assert.equal(momentShortLabel(new Date(2026, 7, 12, 8, 0).getTime(), now), "8:00 am");
  assert.equal(momentShortLabel(Number.NaN, now), "your last visit");
});
