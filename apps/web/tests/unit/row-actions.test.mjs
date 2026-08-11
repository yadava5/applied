/**
 * Unit tests for a pipeline row's actions: which endpoint each one hits, what a
 * failure says, and the row menu's keyboard + one-at-a-time model.
 *
 * The incident these guard: `DELETE /api/applications/66` answered 200 in
 * 906 ms from a single click on a menu item, with no dialog at any point (the
 * DOM was sampled every 200 ms for `[role="dialog"]`/`[role="alertdialog"]`:
 * zero), no undo and no toast. One of the owner's real applications was lost
 * that way. The backend has a recoverable removal — `dismissed_at`,
 * `POST /applications/{id}/restore`, `GET /applications?dismissed=true` — and
 * the hard delete threw it away.
 *
 * So: the one-click action must be the RECOVERABLE endpoint, and the hard
 * delete must be the one that asks. `ApplicationCard.tsx` builds every request
 * from the descriptors asserted here and constructs no URLs of its own.
 *
 * The menu half of the incident — nothing dismissed the menu (outside click,
 * bare `mousedown`, a full pointer sequence and `Escape` on four different
 * targets all left it open, `defaultPrevented: false` every time) and two menus
 * could be open at once — is only partly reachable at this level: the key→intent
 * mapping, the item an intent lands on, and the one-menu-at-a-time registry are
 * asserted here; the DOM listeners that deliver those keys, the focus moves and
 * the undo TIMER are not (no DOM, no component-test framework in this repo).
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  REMOVE_HINT,
  REMOVE_TRAINS_HINT,
  UNDO_WINDOW_SECONDS,
  createMenuRegistry,
  deletedMessage,
  menuKeyIntent,
  permanentDeleteRequest,
  removalPendingMessage,
  removeFromBoardRequest,
  removedMessage,
  rovingIndex,
  statusChangeFailure,
  statusChangeRequest,
  triggerKeyIntent,
} from "../../lib/dashboard/rowActions.ts";

/** The id of the row that was actually lost. */
const ID = 66;

test("the one-click removal hits the RECOVERABLE endpoint, never DELETE", () => {
  const remove = removeFromBoardRequest(ID);
  assert.deepEqual(remove, { path: "/api/applications/66/dismiss", method: "POST" });
  assert.notEqual(remove.method, "DELETE");
});

test("the hard delete is a separate request, and it is the one that erases", () => {
  assert.deepEqual(permanentDeleteRequest(ID), { path: "/api/applications/66", method: "DELETE" });
  // Different endpoint AND different verb from the recoverable one, so a
  // mis-wired menu item cannot silently become the destructive path.
  assert.notEqual(permanentDeleteRequest(ID).path, removeFromBoardRequest(ID).path);
});

test("a stage change PATCHes the chosen status and nothing else", () => {
  assert.deepEqual(statusChangeRequest(ID, "interviewing"), {
    path: "/api/applications/66",
    method: "PATCH",
    body: { status: "interviewing" },
  });
});

test("the undo window is long enough to notice and short enough to be honest", () => {
  assert.ok(Number.isInteger(UNDO_WINDOW_SECONDS), "the countdown is rendered per second");
  assert.ok(UNDO_WINDOW_SECONDS >= 5 && UNDO_WINDOW_SECONDS <= 10, `got ${UNDO_WINDOW_SECONDS}`);
});

test("the menu hints state the undo window in seconds, never 'undoable'", () => {
  // "undoable" reads equally as "can be undone" and "cannot be done" — on a
  // removal action that is exactly the wrong word. The hint derives from the
  // constant so the copy can never drift from the timer.
  for (const hint of [REMOVE_HINT, REMOVE_TRAINS_HINT]) {
    assert.doesNotMatch(hint, /undoable/i);
    assert.match(hint, new RegExp(`${UNDO_WINDOW_SECONDS} s to undo`));
  }
  assert.match(REMOVE_TRAINS_HINT, /trains the model/);
});

test("the pending-removal message names the row, the undo and the time left", () => {
  const message = removalPendingMessage("Beacon Health", 6);
  assert.match(message, /Beacon Health/);
  assert.match(message, /undo/i);
  assert.match(message, /6s/);
  // A tick past zero must not render "-1s" while the request is in flight.
  assert.match(removalPendingMessage("Beacon Health", -1), /0s/);
  assert.match(removalPendingMessage("   ", 3), /^This row/);
});

test("the two committed outcomes do not read alike", () => {
  const removed = removedMessage("Beacon Health");
  const deleted = deletedMessage("Beacon Health");
  assert.notEqual(removed, deleted);
  assert.match(removed, /not deleted/i, "the recoverable one must say it is not a delete");
  assert.match(deleted, /permanently/i);
  assert.equal(/permanently/i.test(removed), false);
  assert.match(removedMessage(""), /^This row/);
});

test("a failed stage change says what it tried, what the row still is, and why", () => {
  // The 10px footnote it replaces read, in full: "Couldn't update the status."
  const plain = statusChangeFailure("assessment", "applied");
  assert.match(plain, /assessment/);
  assert.match(plain, /applied/);

  const withDetail = statusChangeFailure(
    "assessment",
    "applied",
    "Input should be 'applied', 'interviewing', 'offered', 'rejected', 'accepted', 'withdrawn' or 'ghosted'",
  );
  assert.ok(withDetail.startsWith(plain), "the backend's reason is appended, not substituted");
  assert.match(withDetail, /'ghosted'/);
  assert.equal(statusChangeFailure("offered", "applied", "   "), statusChangeFailure("offered", "applied"));
});

test("Escape and Tab close the menu; the arrows move within it", () => {
  assert.equal(menuKeyIntent("Escape"), "close");
  assert.equal(menuKeyIntent("Tab"), "close");
  assert.equal(menuKeyIntent("ArrowDown"), "next");
  assert.equal(menuKeyIntent("ArrowUp"), "previous");
  assert.equal(menuKeyIntent("Home"), "first");
  assert.equal(menuKeyIntent("End"), "last");
  for (const key of ["a", "Enter", " ", "ArrowLeft", "Shift", "escape"]) {
    assert.equal(menuKeyIntent(key), null, `menuKeyIntent(${JSON.stringify(key)})`);
  }
});

test("ArrowDown on the closed trigger opens it (it was unhandled)", () => {
  assert.equal(triggerKeyIntent("ArrowDown"), "first");
  assert.equal(triggerKeyIntent("ArrowUp"), "last");
  for (const key of ["Escape", "Tab", "a", "ArrowRight"]) {
    assert.equal(triggerKeyIntent(key), null, `triggerKeyIntent(${JSON.stringify(key)})`);
  }
});

test("focus wraps at both ends of the menu and survives a bad index", () => {
  assert.equal(rovingIndex(0, 2, "next"), 1);
  assert.equal(rovingIndex(1, 2, "next"), 0); // wraps forward
  assert.equal(rovingIndex(0, 2, "previous"), 1); // wraps backward
  assert.equal(rovingIndex(1, 2, "previous"), 0);
  assert.equal(rovingIndex(1, 2, "first"), 0);
  assert.equal(rovingIndex(0, 2, "last"), 1);
  assert.equal(rovingIndex(1, 2, "close"), 1);
  assert.equal(rovingIndex(1, 2, null), 1);
  // Out-of-range / empty must not produce an index nothing can be focused at.
  assert.equal(rovingIndex(9, 2, "next"), 0);
  assert.equal(rovingIndex(-4, 2, "previous"), 1);
  assert.equal(rovingIndex(Number.NaN, 2, "next"), 1);
  assert.equal(rovingIndex(0, 0, "next"), 0);
});

test("opening one menu closes the other — two were open at once before", () => {
  const registry = createMenuRegistry();
  const closed = [];

  registry.open("row-a", () => closed.push("row-a"));
  assert.equal(registry.openId(), "row-a");
  assert.deepEqual(closed, []);

  registry.open("row-b", () => closed.push("row-b"));
  assert.deepEqual(closed, ["row-a"], "the first menu should have been told to close");
  assert.equal(registry.openId(), "row-b");
});

test("re-opening the same menu does not close it — that would fight the toggle", () => {
  const registry = createMenuRegistry();
  const closed = [];
  registry.open("row-a", () => closed.push("row-a"));
  registry.open("row-a", () => closed.push("row-a"));
  assert.deepEqual(closed, []);
  assert.equal(registry.openId(), "row-a");
});

test("a stale close is a no-op, so an unmounting row cannot close the live menu", () => {
  const registry = createMenuRegistry();
  registry.open("row-a", () => {});
  registry.open("row-b", () => {});
  registry.close("row-a"); // row-a's cleanup, arriving after row-b opened
  assert.equal(registry.openId(), "row-b");
  registry.close("row-b");
  assert.equal(registry.openId(), null);
});
