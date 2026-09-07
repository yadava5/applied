/**
 * WHERE THE LEDGER'S PLATE LANDS — `lib/dashboard/platePlacement.ts`, driven
 * with the measurements #610 was reported from.
 *
 * THE DEFECT THIS FILE IS PART OF CLOSING, and it is worth being precise about
 * which part. #610 asked for "a width budget at 1024". The budget existed and
 * was right; it was computed ONCE, at mount, and the width it budgets against
 * arrives later — `BoardSubtitle` corrects `+N this wk` to the reader's own
 * week (#518), `buildSubtitle` omits that segment entirely at zero, so the
 * correction makes ~70px of subtitle APPEAR in a sibling subtree. That half is
 * a wiring defect and is gated next door, in
 * `tests/unit/plate-replaces-on-neighbour-growth.test.mjs`, which mounts the
 * component and grades whether the placement re-runs at all.
 *
 * What THIS file grades is the arithmetic that wiring re-runs: given the
 * plate's box and its two neighbours', how far does it move. It could not be
 * executed before, because it lived inside a `"use client"` component
 * `node --test` cannot import — the reason the one number the issue is about
 * had no test, while the ledger's copy, grouping and labels all had several.
 *
 * EVERY NUMBER BELOW IS A READING, not a plausible value. They were taken off
 * the shipped page at 1024×768 on `/demo/shell?session=1` — the arrangement
 * `tests/e2e/shell.spec.ts` measures because it stands in for the signed-in
 * row — in headless Chrome against `next dev`, 2026-09-07, and they agree with
 * the issue's own production reading to within a rounding step (it measured
 * the `"+N this wk · "` segment at 69.4px; the same segment lays out at
 * 69.71px here, and the corrected subtitle's right edge at 580.8 in both).
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { PLATE_CLEAR, plateSlide } from "../../lib/dashboard/platePlacement.ts";

/** Sub-pixel edges are floats, so every comparison here is on a rounded
 *  value — 0.01px, two orders finer than anything the guard is about. */
const px = (n) => Math.round(n * 100) / 100;

/**
 * The signed-in twin's header row at 1024×768, rounded to 0.1px as read.
 *
 * `totals.right` is the only value that moves between the two states this
 * issue is about: 511.1 as the server renders the line, 580.8 once the
 * reader's-week segment appears in it. The plate is 111.9px wide and centred
 * on the bar at 576 (main's centre is 632), and the sync cluster starts at
 * 755.5.
 */
const PLATE = { left: 576, right: 688 };
const CLUSTER = { left: 755.5, right: 1000 };
const SERVED = { left: 352, right: 511.1 };
const CORRECTED = { left: 352, right: 580.8 };
/** One more character in the segment (`+7` → `+17`), laid out at the
 *  subtitle's shipped face — 13px atkinson, tabular figures: 237.06px against
 *  228.84px for the same line one digit shorter. */
const ONE_CHARACTER = 8.22;

test("centred and clear of both neighbours: the plate does not move at all", () => {
  assert.equal(
    plateSlide({ plate: PLATE, totals: SERVED, cluster: CLUSTER }),
    0,
    "the centre is the invariant — a plate that drifts with nothing forcing it is #212 reopening",
  );
});

test("#610: the reader's-week segment appears and the plate yields exactly the budget", () => {
  const dx = plateSlide({ plate: PLATE, totals: CORRECTED, cluster: CLUSTER });
  assert.equal(px(dx), 20.8, "the slide the corrected subtitle forces at 1024");
  assert.equal(
    px(PLATE.left + dx - CORRECTED.right),
    PLATE_CLEAR,
    "it yields what the neighbour forces and not a pixel more — the centre is what is being spent",
  );
  // The state the issue reported: the same plate, not re-placed. Held here as
  // the size of what is at stake rather than as a second way of saying the
  // line above — 4.7px of the subtitle under the chip on this twin, ~53px on
  // the owner's board, where the totals already bind at the budget.
  assert.ok(
    PLATE.left - CORRECTED.right < 0,
    "the un-slid plate overlaps the corrected subtitle, which is why this number matters",
  );
});

test("directional control: one more character in the segment moves the plate by exactly that character", () => {
  const before = plateSlide({ plate: PLATE, totals: CORRECTED, cluster: CLUSTER });
  const after = plateSlide({
    plate: PLATE,
    totals: { ...CORRECTED, right: CORRECTED.right + ONE_CHARACTER },
    cluster: CLUSTER,
  });
  assert.equal(
    px(after - before),
    ONE_CHARACTER,
    "widening the subtitle by one character must move the plate by one character, or this guard is reporting a constant",
  );
});

test("a neighbour that is not on the plate's line constrains nothing", () => {
  // Below `lg` the chip is an in-flow line of its own and `sameLine` hands both
  // neighbours through as null. The answer has to be zero: a nudge there would
  // shift a centred line inside a phone's column for no reason.
  assert.equal(plateSlide({ plate: PLATE, totals: null, cluster: null }), 0);
  assert.equal(
    plateSlide({ plate: PLATE, totals: null, cluster: CLUSTER }),
    0,
    "a cluster 67px clear of the plate asks for nothing",
  );
});

test("the cluster binds: the plate slides LEFT, and only as far as asked", () => {
  // The FURNISHED twin at 1024 — /demo/shell with its fixture pill, 167px of
  // right flank the live board does not have. Measured there in this same
  // state: a 161.1px window between the neighbours, the plate 31.8px off the
  // bar's centre and 16.0px off the cluster. `left` is that reading put back
  // together (511.1 + 161.1), and the answer has to be the 31.8 it was seen
  // to yield.
  const furnished = { left: 672.2, right: 1000 };
  const dx = plateSlide({ plate: PLATE, totals: SERVED, cluster: furnished });
  assert.equal(px(dx), -31.8, "left is negative — a sign error reads as the plate fleeing the row");
  assert.equal(px(furnished.left - (PLATE.right + dx)), PLATE_CLEAR);
});

test("#196: when both neighbours bind at once, the TOTALS win", () => {
  // The rule with a defect number on it: a plate that yielded to the controls
  // first sat on the totals it was overlapping and read as a caption hung off
  // them. This case is also the one that catches a swapped min/max — the
  // corrected-subtitle case above answers 20.8 either way round.
  const tight = { left: 700, right: 900 };
  const dx = plateSlide({ plate: PLATE, totals: CORRECTED, cluster: tight });
  assert.equal(px(dx), 20.8, "the totals' requirement, not the cluster's");
  assert.ok(
    PLATE.right + dx > tight.left - PLATE_CLEAR,
    "the cluster is the neighbour that gets overlapped, which is the rule stated out loud",
  );
});

test("the budget is 16px", () => {
  // A literal on purpose: this is the number the two e2e floors are written
  // under (24px where nothing binds, 12px on the crowded twin), so a silent
  // change to it should red here and be argued for in a diff.
  assert.equal(PLATE_CLEAR, 16);
});
