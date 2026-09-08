/**
 * Undo puts the row back WHERE IT WAS (#904).
 *
 * The demo board's `restore` appended: `apps: [...s.apps, row]`. The board
 * renders in array order and sorts nothing — `PipelineBoard` groups with
 * `filtered.filter(...)`, deliberately, because the signed-in board's order is
 * the server's and a second ordering rule in the client is how two renderers of
 * one number drift apart. So an appended row is a MOVED row. Measured on /demo
 * at 1024: `Harbor Analytics` (filed Aug 27) sat third in `applied`, and after
 * dismiss-then-Undo it sat last, below a row filed Sep 7. Only a reload put it
 * right — which is the tell, because a reload rebuilds the store from the same
 * fixtures this reinsert reads.
 *
 * WHAT WOULD PASS ON THE BROKEN BUILD, and is therefore not what is asserted
 * here: "the row is back". It was always back. The property is the ORDER of the
 * whole column, and it is only visible when the restored row is not the last
 * one — hence the control at the bottom, which restores a row that genuinely
 * was last and must pass either way.
 *
 * The wiring — that the board's Undo reaches this function at all — is
 * `tests/e2e/row-removal.spec.ts`, on the real /demo.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { reinsertByReference } from "../../lib/demo/restoreOrder.ts";

/** The mount's pristine fixtures, in the order the board first drew them. */
const FIXTURES = [
  { id: 1, company: "Cedar Labs" },
  { id: 2, company: "Harbor Analytics" },
  { id: 3, company: "Quarry Data" },
  { id: 4, company: "Waypoint Robotics" },
];

const ids = (rows) => rows.map((row) => row.id);

test("a row restored from the middle lands back in the middle", () => {
  const removed = FIXTURES[1];
  const board = FIXTURES.filter((row) => row.id !== removed.id);
  assert.deepEqual(
    ids(reinsertByReference(board, removed, FIXTURES)),
    [1, 2, 3, 4],
    "the restored row did not come back to the place the fixtures put it",
  );
});

test("the column's whole order survives, not just the row", () => {
  // Two rows away and back, in the order a reader would do it. The assertion
  // is on every position, because a restore that lands one row wrong is a
  // board that disagrees with itself in exactly the place the reader is
  // looking.
  let board = FIXTURES.filter((row) => row.id !== 2 && row.id !== 3);
  board = reinsertByReference(board, FIXTURES[2], FIXTURES);
  board = reinsertByReference(board, FIXTURES[1], FIXTURES);
  assert.deepEqual(ids(board), [1, 2, 3, 4]);
});

test("a row added this session is not moved, and does not move the restored row", () => {
  // The visitor's own row has no home in the fixtures. It must not be treated
  // as the place a restored row belongs before, and it must not be reordered.
  const session = { id: 99, company: "Typed By Hand" };
  const board = [FIXTURES[0], FIXTURES[2], session];
  assert.deepEqual(
    ids(reinsertByReference(board, FIXTURES[1], FIXTURES)),
    [1, 2, 3, 99],
    "a session row decided where a fixture row belongs",
  );
  // And a row restored from BEYOND every fixture the board still holds goes to
  // the end, after that session row — it has no fixture successor to sit above.
  assert.deepEqual(ids(reinsertByReference(board, FIXTURES[3], FIXTURES)), [1, 3, 99, 4]);
});

test("THE CONTROL: a row that really was last comes back last, as it always did", () => {
  // This one passes on the appending version too, and that is the point: it
  // proves the assertion above is about POSITION and not about the function
  // simply being called. A fix that put every row somewhere new would fail
  // here even while the middle case passed.
  const removed = FIXTURES[3];
  const board = FIXTURES.filter((row) => row.id !== removed.id);
  assert.deepEqual(ids(reinsertByReference(board, removed, FIXTURES)), [1, 2, 3, 4]);
  assert.deepEqual(ids([...board, removed]), [1, 2, 3, 4], "the control is not a control");
});

test("a row the fixtures never held is appended rather than dropped", () => {
  const stranger = { id: 404, company: "Not In This Mount" };
  assert.deepEqual(ids(reinsertByReference(FIXTURES, stranger, FIXTURES)), [1, 2, 3, 4, 404]);
});
