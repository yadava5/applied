/**
 * The pulse's worklist filters (`lib/dashboard/pulseFilter.ts`) — specifically
 * the contract that makes the detail panel a work surface rather than a
 * poster: the rows a click reveals are EXACTLY the rows the drawn unit
 * counted. A panel that opens a set which disagrees with the bar above it is
 * worse than no panel, and nothing else in this repo checks that agreement.
 *
 * Written with the deadline panel (2026-08-13), so the deadline vocabulary is
 * covered first and hardest: every runway bin is re-derived here through the
 * predicate and compared against the count the bin drew.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { deadlinePulse, deadlineRunway } from "../../lib/dashboard/deadline.ts";
import { matchesPulseFilter, pulseFilterLabel } from "../../lib/dashboard/pulseFilter.ts";

const TODAY = "2026-08-11";

/** A board whose rows carry only what these filters read. */
const board = [
  { company: "Late Co", status: "applied", source: "gmail", due_at: "2026-08-04T23:59:59Z" },
  { company: "Late Too Co", status: "applied", source: "manual", due_at: "2026-08-10T23:59:59Z" },
  { company: "Today Co", status: "interviewing", source: "gmail", due_at: "2026-08-11T23:59:59Z" },
  { company: "Edge Co", status: "applied", source: "gmail", due_at: "2026-08-13T23:59:59Z" },
  { company: "Ahead Co", status: "applied", source: "gmail", due_at: "2026-08-30T23:59:59Z" },
  { company: "No Deadline Co", status: "applied", source: "gmail", due_at: null },
];

const shown = (filter) => board.filter((row) => matchesPulseFilter(row, filter, TODAY));

test("every runway bin opens exactly the rows it counted", () => {
  const pulse = deadlinePulse(board, TODAY);
  const runway = deadlineRunway(pulse.rows);
  for (const bin of runway) {
    const filter =
      bin.kind === "day"
        ? { kind: "dueIn", days: bin.days }
        : { kind: "due", state: bin.kind === "overdue" ? "overdue" : "ahead" };
    assert.equal(
      shown(filter).length,
      bin.count,
      `the ${bin.kind === "day" ? `+${bin.days} d` : bin.kind} column draws ${bin.count} and opens ${shown(filter).length}`,
    );
  }
});

test("a named row opens the set it belongs to, never the empty one", () => {
  const pulse = deadlinePulse(board, TODAY);
  for (const row of pulse.rows) {
    const rows = shown({ kind: "dueIn", days: row.daysLeft });
    assert.ok(
      rows.some((match) => match.company === row.company),
      `${row.company} is not in the set its own row opens`,
    );
  }
});

test("a row without a deadline is in no deadline filter at all", () => {
  for (const filter of [
    { kind: "due", state: "overdue" },
    { kind: "due", state: "soon" },
    { kind: "due", state: "ahead" },
    { kind: "dueIn", days: 0 },
    { kind: "dueIn", days: -7 },
  ]) {
    assert.ok(
      !shown(filter).some((row) => row.company === "No Deadline Co"),
      `an undated row leaked into ${pulseFilterLabel(filter)}`,
    );
  }
});

test("the filter band says what the caption says — one set, one name", () => {
  assert.equal(pulseFilterLabel({ kind: "due", state: "overdue" }), "overdue");
  assert.equal(pulseFilterLabel({ kind: "due", state: "soon" }), "due within 2 days");
  assert.equal(pulseFilterLabel({ kind: "due", state: "ahead" }), "due after 2 days");
  // Days-left filters quote the phrase the card tag already prints.
  assert.equal(pulseFilterLabel({ kind: "dueIn", days: 0 }), "due today");
  assert.equal(pulseFilterLabel({ kind: "dueIn", days: 2 }), "due in 2d");
  assert.equal(pulseFilterLabel({ kind: "dueIn", days: -3 }), "overdue 3d");
});

test("the filters the panel already had still narrow to their own rows", () => {
  assert.deepEqual(
    shown({ kind: "source", source: "hand" }).map((row) => row.company),
    ["Late Too Co"],
  );
  assert.equal(shown({ kind: "source", source: "mail" }).length, 5);
});
