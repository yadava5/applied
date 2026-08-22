/**
 * Unit tests for the detail pane's neighbour prefetch bound
 * (`lib/dashboard/neighbourWarm`).
 *
 * WHY. The pane opens with no network — the wait a reader feels on a card is
 * `GET /api/applications/{id}` for the mail trail, measured on production
 * 2026-08-22 at a 371 ms median with connection reuse already on. That request
 * is not getting much faster, so it is taken EARLIER instead: one row either
 * side of the open card, into the cache the pane already reads.
 *
 * What must hold, and is held here — all of it about the BOUND, because the
 * failure mode of a prefetch is not "too slow", it is "too much":
 *
 *   - a closed pane (`index === -1`) warms NOTHING. This is the one that keeps
 *     a board nobody has clicked from speculatively reading anything at all;
 *   - both ends CLAMP, so the first and last rows warm one neighbour, not one
 *     neighbour and an `undefined`;
 *   - the open row is never in the set — the pane is already fetching it;
 *   - the bound stays at one row either side. A future edit widening it to two
 *     is a fan-out change against a small pool and should have to change a
 *     test that says so.
 *
 * The delay is asserted as an ORDERING fact rather than a magic number: it has
 * to sit above the median it was chosen to clear, or a speculative fetch
 * starts competing with the request the reader is actually waiting on.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  NEIGHBOUR_WARM_DELAY_MS,
  neighbourIdsToWarm,
} from "../../lib/dashboard/neighbourWarm.ts";

/** A board's visible order; only `id` is read. */
const rows = [{ id: 10 }, { id: 11 }, { id: 12 }, { id: 13 }];

test("a card in the middle warms exactly the row above and the row below", () => {
  assert.deepEqual(neighbourIdsToWarm(rows, 2), [11, 13]);
});

test("the open row is never warmed — the pane is already fetching it", () => {
  for (let i = 0; i < rows.length; i += 1) {
    assert.ok(
      !neighbourIdsToWarm(rows, i).includes(rows[i].id),
      `index ${i} warmed its own row`,
    );
  }
});

test("both ends clamp instead of warming an undefined row", () => {
  assert.deepEqual(neighbourIdsToWarm(rows, 0), [11]);
  assert.deepEqual(neighbourIdsToWarm(rows, rows.length - 1), [12]);
});

test("a CLOSED pane warms nothing — the board does not speculate unprompted", () => {
  // -1 is what PipelineBoard computes when `detailApp === null`.
  assert.deepEqual(neighbourIdsToWarm(rows, -1), []);
  // An index past the end is the same refusal, not a crash: the open row can
  // leave the visible set (a filter, a stage change) between renders.
  assert.deepEqual(neighbourIdsToWarm(rows, 99), []);
  assert.deepEqual(neighbourIdsToWarm([], 0), []);
});

test("a one-row board warms nothing, and a two-row board warms exactly one", () => {
  assert.deepEqual(neighbourIdsToWarm([{ id: 5 }], 0), []);
  assert.deepEqual(neighbourIdsToWarm([{ id: 5 }, { id: 6 }], 0), [6]);
  assert.deepEqual(neighbourIdsToWarm([{ id: 5 }, { id: 6 }], 1), [5]);
});

test("the bound is ONE row either side — never more than two reads per open", () => {
  const wide = Array.from({ length: 43 }, (_, i) => ({ id: i + 1 }));
  for (let i = 0; i < wide.length; i += 1) {
    assert.ok(
      neighbourIdsToWarm(wide, i).length <= 2,
      `index ${i} would fan out ${neighbourIdsToWarm(wide, i).length} reads`,
    );
  }
  // The whole board is 43 rows; an unbounded version would warm all of them.
  assert.equal(neighbourIdsToWarm(wide, 20).length, 2);
});

test("the warm waits longer than the open card's own read, so it cannot queue ahead of it", () => {
  /** The production median this delay was chosen against (ms). */
  const MEASURED_OPEN_MEDIAN_MS = 371;
  assert.ok(
    NEIGHBOUR_WARM_DELAY_MS > MEASURED_OPEN_MEDIAN_MS,
    `delay ${NEIGHBOUR_WARM_DELAY_MS}ms does not clear the ${MEASURED_OPEN_MEDIAN_MS}ms median`,
  );
  // And short enough to land before a deliberate ↑/↓ step (~1 s apart),
  // or the traversal it exists for arrives first and it warms nothing useful.
  assert.ok(NEIGHBOUR_WARM_DELAY_MS < 1_000, "delay is too long to beat a traversal step");
});
