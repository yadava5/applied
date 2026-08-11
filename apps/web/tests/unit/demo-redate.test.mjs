/**
 * Re-dating the demo store when the reader's day turns out not to be the UTC
 * day — the operation that used to be a wholesale rebuild.
 *
 * The bug these tests pin is not arithmetic, it is loss. `/demo` seeds against
 * the UTC day (the only day the server and the hydrating client agree on), and
 * once the reader's own day is known the fixtures have to follow it. The old
 * code did that by committing a freshly built store, which threw away every
 * stage change, hand-set deadline, dismissal and sync the visitor had already
 * made. It fired within milliseconds of hydration, so it usually got away with
 * it — but the demo's transports await 300ms before committing, and a visitor
 * who leaves the page open past their own midnight gets a second one.
 *
 * So: dates move, the session does not. The three deadline cases are the
 * subtle part and are why this is a function rather than a spread — a fixture
 * deadline follows the day, a deadline the visitor typed is absolute, and a
 * deadline they cleared must stay cleared rather than being resurrected by the
 * fixtures it came from.
 *
 * Run: node --test tests/unit/demo-redate.test.mjs
 */
import assert from "node:assert/strict";
import test from "node:test";

import { datedById, redate } from "../../lib/demo/redate.ts";

/** The pristine fixtures, as they would be built against the reader's day. */
const PRISTINE = [
  { id: 1, created_at: "2026-08-05T12:00:00.000Z", applied_date: null, due_at: null, due_source: null },
  { id: 2, created_at: "2026-08-09T12:00:00.000Z", applied_date: null, due_at: "2026-08-14", due_source: "mail" },
  { id: 3, created_at: "2026-08-01T12:00:00.000Z", applied_date: null, due_at: "2026-08-10", due_source: "mail" },
];
const DATED = datedById(PRISTINE);

test("fixture dates follow the new day", () => {
  const live = [
    { id: 2, company: "Kestrel", status: "interviewing", created_at: "2026-08-08T12:00:00.000Z", applied_date: null, due_at: "2026-08-13", due_source: "mail" },
  ];
  const [row] = redate(live, DATED);
  assert.equal(row.created_at, "2026-08-09T12:00:00.000Z");
  assert.equal(row.due_at, "2026-08-14");
});

test("everything the visitor did survives the re-dating", () => {
  const live = [
    // A stage the visitor chose, on a row whose fixture status is `applied`.
    { id: 1, company: "Quarry Data", status: "interviewing", notes: "kept", created_at: "2026-08-04T12:00:00.000Z", applied_date: null, due_at: null, due_source: null },
  ];
  const [row] = redate(live, DATED);
  assert.equal(row.status, "interviewing", "a stage correction is not a date");
  assert.equal(row.company, "Quarry Data");
  assert.equal(row.notes, "kept");
  assert.equal(row.created_at, "2026-08-05T12:00:00.000Z", "…but the date did move");
});

test("a deadline the visitor typed is absolute and does not shift", () => {
  const live = [
    { id: 2, created_at: "2026-08-08T12:00:00.000Z", applied_date: null, due_at: "2026-09-30", due_source: "user" },
  ];
  const [row] = redate(live, DATED);
  assert.equal(row.due_at, "2026-09-30");
  assert.equal(row.due_source, "user");
  assert.equal(row.created_at, "2026-08-09T12:00:00.000Z", "the filed date still moves");
});

test("a deadline the visitor cleared stays cleared", () => {
  const live = [
    // Row 3 has a `mail` deadline in the fixtures; this visitor cleared it, so
    // the row carries no source at all. Re-dating must not hand it back.
    { id: 3, created_at: "2026-08-01T12:00:00.000Z", applied_date: null, due_at: null, due_source: null },
  ];
  const [row] = redate(live, DATED);
  assert.equal(row.due_at, null);
  assert.equal(row.due_source, null);
});

test("a row the fixtures do not know is returned untouched", () => {
  const live = [
    { id: 99, company: "Added by hand", created_at: "2026-08-07T12:00:00.000Z", due_at: "2026-08-20", due_source: "user" },
  ];
  const [row] = redate(live, DATED);
  assert.deepEqual(row, live[0]);
});

test("order and length are preserved", () => {
  const live = [
    { id: 3, created_at: "x", applied_date: null, due_at: "2026-08-09", due_source: "mail" },
    { id: 1, created_at: "y", applied_date: null, due_at: null, due_source: null },
    { id: 2, created_at: "z", applied_date: null, due_at: "2026-08-13", due_source: "mail" },
  ];
  assert.deepEqual(
    redate(live, DATED).map((row) => row.id),
    [3, 1, 2],
  );
});
