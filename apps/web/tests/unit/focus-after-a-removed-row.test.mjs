/**
 * Where the reader goes when the row under them leaves the board (#903).
 *
 * Measured on /demo at 1024, before the fix: dismiss a row, wait out the undo
 * window, and focus is on `<body>` from the instant the slot unmounts (t=6.02s)
 * to the end of the trace. The reader was standing on `Undo`, deciding about a
 * destructive action, and the ring, the announcement and the Shift+Tab anchor
 * all go at once.
 *
 * This file pins the CHOICE of successor. That the board acts on it — that
 * focus really lands on that row's `···` trigger and not on `<body>` — is
 * `tests/e2e/row-removal.spec.ts`, which needs a real focus model.
 *
 * The rule is directional, so the assertions are: forward before backward, and
 * the removed row's own stage before any other. A test that only asserted "some
 * surviving row is offered" would pass on a rule that sent the reader to the top
 * of the board, which is the defect wearing different clothes.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { focusCandidatesAfterRemoval } from "../../lib/dashboard/rowFocus.ts";

/** A board in board order: three `applied` rows, then two `interviewing`. */
const BOARD = [
  { id: 1, stage: "applied" },
  { id: 2, stage: "applied" },
  { id: 3, stage: "applied" },
  { id: 4, stage: "interviewing" },
  { id: 5, stage: "interviewing" },
];

const without = (...gone) => new Set(BOARD.map((r) => r.id).filter((id) => !gone.includes(id)));

test("the row that took its place comes first", () => {
  const candidates = focusCandidatesAfterRemoval(BOARD, without(2), 2);
  assert.equal(candidates[0], 3, "focus did not follow the list closing up");
  // Its own column before anything outside it, and never itself.
  assert.deepEqual(candidates, [3, 1, 4, 5]);
});

test("a row that was last in its column hands back to the row above it", () => {
  const candidates = focusCandidatesAfterRemoval(BOARD, without(3), 3);
  assert.equal(candidates[0], 2, "the reader was sent out of the column instead of up it");
  assert.deepEqual(candidates, [2, 1, 4, 5]);
});

test("a removal that empties a column falls out of it rather than nowhere", () => {
  const solo = [
    { id: 1, stage: "applied" },
    { id: 2, stage: "offered" },
    { id: 3, stage: "applied" },
  ];
  // Column `offered` has one row; removing it leaves no heading to hold anyone.
  const candidates = focusCandidatesAfterRemoval(solo, new Set([1, 3]), 2);
  assert.deepEqual(candidates, [3, 1]);
});

test("rows that also went are never offered", () => {
  // A refresh can land several changes at once; a candidate the reader cannot
  // reach is worse than none, because the board would focus nothing and say
  // it had.
  const candidates = focusCandidatesAfterRemoval(BOARD, without(1, 2, 3), 2);
  assert.deepEqual(candidates, [4, 5]);
});

test("an empty answer is possible, and is not an error", () => {
  // The last row on the board. There is genuinely nowhere to go, and inventing
  // a destination — the search box, the page heading — would move the reader
  // somewhere they never were.
  assert.deepEqual(focusCandidatesAfterRemoval([{ id: 7, stage: "applied" }], new Set(), 7), []);
  // A row this board never held answers nothing at all.
  assert.deepEqual(focusCandidatesAfterRemoval(BOARD, without(2), 99), []);
});
