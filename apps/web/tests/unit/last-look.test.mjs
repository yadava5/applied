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
