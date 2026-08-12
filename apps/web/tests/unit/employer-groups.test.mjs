/**
 * Unit tests for the employer DISPLAY grouping (`lib/dashboard/employerGroups.ts`).
 *
 * What these pin down:
 *
 *  1. Grouping is a fold over the same rows the flat list would render — no
 *     row is dropped, invented or reordered. This is the boundary that keeps
 *     it a view and never a merge (the merge was a real correctness bug:
 *     furthest-stage-wins plus a terminal override made one rejection swallow
 *     an employer's other live applications).
 *  2. The singleton — most rows — passes through untouched, so the common
 *     case cannot be made worse by the grouped one.
 *  3. A set anchors at its first member's position and keeps member order.
 *  4. The cross-stage chip text names ONE other stage when there is one, and
 *     says "other stages" when there are several — and renders nothing for a
 *     count of zero, because "+0 elsewhere" is noise.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { elsewhereLabel, groupByEmployer } from "../../lib/dashboard/employerGroups.ts";

const row = (id, company) => ({ id, company });

test("singletons pass through as singles, in order", () => {
  const rows = [row(1, "Harbor"), row(2, "Quarry"), row(3, "Beacon")];
  assert.deepEqual(groupByEmployer(rows), [
    { kind: "single", app: rows[0] },
    { kind: "single", app: rows[1] },
    { kind: "single", app: rows[2] },
  ]);
});

test("two or more rows at one employer fold into one set holding every row", () => {
  const rows = [row(1, "Northstar"), row(2, "Northstar"), row(3, "Northstar"), row(4, "Northstar")];
  const entries = groupByEmployer(rows);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].kind, "set");
  assert.equal(entries[0].company, "Northstar");
  // Every application is present — a set is a view, never a merge.
  assert.deepEqual(
    entries[0].items.map((r) => r.id),
    [1, 2, 3, 4],
  );
});

test("a set anchors at its first member's position; interleaved rows keep their own", () => {
  const rows = [row(1, "Northstar"), row(2, "Cedar"), row(3, "Northstar"), row(4, "Quarry")];
  const entries = groupByEmployer(rows);
  assert.deepEqual(
    entries.map((e) => (e.kind === "set" ? `set:${e.company}` : `single:${e.app.company}`)),
    ["set:Northstar", "single:Cedar", "single:Quarry"],
  );
  assert.deepEqual(
    entries[0].items.map((r) => r.id),
    [1, 3],
  );
});

test("no row is lost or duplicated across any mix of sets and singles", () => {
  const rows = [
    row(1, "A"),
    row(2, "B"),
    row(3, "A"),
    row(4, "C"),
    row(5, "B"),
    row(6, "A"),
  ];
  const entries = groupByEmployer(rows);
  const ids = entries.flatMap((e) => (e.kind === "set" ? e.items.map((r) => r.id) : [e.app.id]));
  assert.deepEqual([...ids].sort((a, b) => a - b), [1, 2, 3, 4, 5, 6]);
});

test("elsewhereLabel names the one other stage, or 'other stages' for a spread", () => {
  assert.equal(elsewhereLabel(1, ["interviewing"]), "+1 in interviewing");
  assert.equal(elsewhereLabel(3, ["applied"]), "+3 in applied");
  // Duplicate labels are still ONE stage.
  assert.equal(elsewhereLabel(2, ["closed", "closed"]), "+2 in closed");
  assert.equal(elsewhereLabel(3, ["interviewing", "closed"]), "+3 in other stages");
});

test("elsewhereLabel renders nothing when there is nothing elsewhere", () => {
  assert.equal(elsewhereLabel(0, []), null);
  assert.equal(elsewhereLabel(0, ["applied"]), null);
  assert.equal(elsewhereLabel(2, []), null);
});
