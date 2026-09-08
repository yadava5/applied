/**
 * Unit tests for the half of "Removed rows" (#921) that a browser cannot
 * reach.
 *
 * WHY THIS FILE EXISTS ALONGSIDE `tests/e2e/removed-rows.spec.ts`. The e2e runs
 * on /demo, because that is the only board CI can drive without a Supabase
 * session, and /demo answers `transport.removed` from an in-memory store. So
 * the browser test proves the SURFACE — a row leaves the board, the window
 * closes, the panel finds it, the restore puts it back — and cannot observe the
 * request the live board makes. The one flag in that request is the difference
 * between a recovery surface and the board rendered back at the reader, and
 * flipping it breaks nothing else: `dismissed: false` returns live rows, in the
 * same shape, with the same status code, and the panel renders them perfectly
 * with a "Put it back" button beside rows that never left. Nothing downstream
 * can tell. So it is asserted here, directly, where it is a value.
 *
 * The control, stated so it can be run: change `dismissed: true` to `false` in
 * `lib/applications/removed.ts` and the first test reds. Delete the
 * `REMOVED_PAGE_SIZE` multiplication from `removedRange` and the range test
 * reds. Collapse `removalActor`'s two known reasons onto one string and the
 * actor test reds. None of those three mutations reds anything else in this
 * repository, which is the reason each is here.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  REMOVED_DESCRIPTION,
  REMOVED_EMPTY,
  REMOVED_PAGE_SIZE,
  REMOVED_TITLE,
  RESTORE_FAILED,
  clampPage,
  pageCount,
  removalActor,
  removedPagePath,
  removedPageQuery,
  removedRange,
} from "../../lib/applications/removed.ts";
import {
  REMOVE_HINT,
  REMOVE_STICKY_HINT,
  REMOVED_TAIL,
  restoreToBoardRequest,
} from "../../lib/dashboard/rowActions.ts";

test("the list request asks for the REMOVED set, never the board", () => {
  // THE ASSERTION THE BROWSER TEST CANNOT MAKE. `dismissed` is the only thing
  // separating "what is off the board" from "what is on it", the backend
  // filters `dismissed_at` exclusively on it, and a `false` here would render
  // a plausible, populated, entirely wrong panel.
  assert.equal(removedPageQuery(1).dismissed, true);
  assert.equal(removedPageQuery(7).dismissed, true);
  // It is the same request for every page — a flag that survived page 1 and
  // was dropped on page 2 would show live rows to anyone who paged.
  assert.equal(removedPageQuery(2).page, 2);
  assert.equal(removedPageQuery(2).page_size, REMOVED_PAGE_SIZE);
});

test("a page number the backend would reject never reaches it", () => {
  // `page` is `ge=1` on the endpoint, and a 422 rendered inside a recovery
  // surface reads as "your removed rows are gone". Every one of these is a
  // value some real path can produce: a stale bit of state, a hand-typed URL,
  // a missing query param (`null`).
  for (const bad of [0, -3, null, undefined, "", "abc", NaN, Infinity]) {
    assert.equal(clampPage(bad), 1, `clampPage(${String(bad)})`);
  }
  assert.equal(clampPage(4), 4);
  assert.equal(clampPage("4"), 4);
  assert.equal(clampPage(2.7), 2, "a fractional page is floored, never sent as-is");
  assert.equal(removedPageQuery(0).page, 1);
  assert.equal(removedPagePath(0), "/api/applications/removed?page=1");
});

test("the pager states the page it is on, not the page size", () => {
  // The last page is SHORT, and claiming ten rows over four drawn is exactly
  // the class of number this repo keeps finding wrong. `count` is what the
  // page returned; `total` is what the account holds.
  assert.equal(removedRange(1, REMOVED_PAGE_SIZE, 47), `1–${REMOVED_PAGE_SIZE} of 47`);
  assert.equal(removedRange(2, REMOVED_PAGE_SIZE, 47), `11–20 of 47`);
  assert.equal(removedRange(5, 7, 47), "41–47 of 47");
  // Nothing to page through says nothing at all rather than "1–0 of 0".
  assert.equal(removedRange(1, 0, 0), "");
  assert.equal(pageCount(0), 1, "an empty set is still one (empty) page");
  assert.equal(pageCount(REMOVED_PAGE_SIZE), 1);
  assert.equal(pageCount(REMOVED_PAGE_SIZE + 1), 2);
});

test("the panel names WHO removed a row, and the two authors read differently", () => {
  // `dismissed=true` returns the user's own removals AND everything a rebuild
  // purged — the backend's parameter says so outright. A panel that said "you
  // removed this" over a resync row would be telling the reader they did
  // something they did not do, which on a surface whose whole job is to
  // explain a missing row is the worst available failure.
  const user = removalActor("user");
  const resync = removalActor("resync");
  assert.notEqual(user, resync);
  assert.match(user, /you/i);
  assert.doesNotMatch(resync, /\byou\b/i);
  // An unknown reason claims no actor rather than guessing one. Both shapes
  // are reachable: `dismissed_reason` is nullable on the wire.
  for (const unknown of [null, undefined, "", "something-new"]) {
    assert.doesNotMatch(removalActor(unknown), /\byou\b/i, `actor for ${String(unknown)}`);
  }
});

test("the removal hint says what happens after the window, and names where", () => {
  // #921's second half. The hint used to end at the countdown, which left the
  // reader with the one fact they need unstated — and before the panel existed
  // the honest completion of that sentence was "and then it is gone".
  //
  // This fails on the copy that shipped: "takes it off the board · 10 s to
  // undo" contains neither the title nor anything after the seconds.
  for (const hint of [REMOVE_HINT, REMOVE_STICKY_HINT]) {
    assert.ok(
      hint.includes(REMOVED_TITLE),
      `the hint must name the recovery surface by its own title: "${hint}"`,
    );
    assert.ok(
      hint.indexOf(REMOVED_TITLE) > hint.indexOf("to undo"),
      "the place comes AFTER the window — it is what happens next, not an alternative to it",
    );
  }
  // One name in every mouth: the hint, the panel title and the board menu's
  // item are the same string, so a reader who reads one is looking for
  // something that exists.
  assert.equal(REMOVED_TITLE, "Removed rows");
});

test("the sticky hint separates the machine from the person", () => {
  // The old tail read "a later sync won't bring it back", which beside "it
  // waits in Removed rows" asks the reader which of the two is true. Both are;
  // the distinction is who is acting. So the Gmail variant must still make a
  // sync-specific claim, and must not deny the recovery the plain hint just
  // promised.
  assert.notEqual(REMOVE_STICKY_HINT, REMOVE_HINT);
  assert.ok(REMOVE_STICKY_HINT.startsWith(REMOVE_HINT));
  assert.match(REMOVE_STICKY_HINT, /sync/i);
  assert.doesNotMatch(
    REMOVE_STICKY_HINT,
    /won'?t bring it back|can'?t be recovered|gone for good/i,
    "the sticky claim is about the SYNC, and may not read as 'this is unrecoverable'",
  );
});

test("the committed tombstone and the panel do not contradict each other", () => {
  // The tombstone says "not deleted" and the panel is what makes that
  // actionable. Neither may claim the other's job: the tail states the outcome
  // (this was not a delete), the panel's own copy states the recovery.
  assert.match(REMOVED_TAIL, /not deleted/i);
  assert.match(REMOVED_DESCRIPTION, /not deleted/i);
  assert.doesNotMatch(REMOVED_EMPTY, /error|sorry|oops/i);
  // The failure sentence is the one the scan receipt already uses for the same
  // act — two wordings for one outcome is how a product stops sounding like
  // itself. `SyncBar.tsx` renders this literal beside its per-row restore.
  assert.equal(RESTORE_FAILED, "couldn't restore — still removed");
});

test("restore is still the endpoint that puts a row back", () => {
  // The panel calls `transport.restore`, which is built from this descriptor.
  // Pinned here so the recovery surface cannot quietly start pointing at
  // `dismiss` (a no-op wearing a success) or, worse, at DELETE.
  const restore = restoreToBoardRequest(66);
  assert.equal(restore.path, "/api/applications/66/restore");
  assert.equal(restore.method, "POST");
});
