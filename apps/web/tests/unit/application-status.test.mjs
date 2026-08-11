/**
 * Unit tests for the stage list the board offers and the column it files a row
 * under.
 *
 * The bugs these guard, both measured on the live app:
 *
 *  1. The card's <select> carried its own literal array including
 *     `assessment` — a value the API has never accepted. Choosing it answered
 *
 *       422 · Input should be 'applied', 'interviewing', 'offered', 'rejected',
 *             'accepted', 'withdrawn' or 'ghosted'
 *
 *     while `ghosted`, which the API DOES accept, was absent from the dropdown.
 *     The list now lives in `lib/dashboard/status.ts` and the component imports
 *     it, so the assertion below is the dropdown's contents, not a parallel
 *     model of them.
 *  2. A `withdrawn` application sat in a column whose `aria-label` read
 *     `rejected — 1`. The user withdrew; the board said they were rejected.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { COLUMN_LABELS, boardColumns, cardQualifier } from "../../lib/dashboard/board.ts";
import {
  APPLICATION_STATUSES,
  isApplicationStatus,
  normalizeStatus,
  statusOptions,
  statusSelectValue,
} from "../../lib/dashboard/status.ts";

/**
 * Exactly the values named in the API's own 422, in the order it named them —
 * which is `ApplicationStatus`'s declaration order and what
 * `GET /applications/statuses` serves. Written out here rather than derived, so
 * a change to the frontend list has to be made deliberately in two places.
 */
const API_ACCEPTS = ["applied", "interviewing", "offered", "rejected", "accepted", "withdrawn", "ghosted"];

/** The four stages as `summary.ts` declares them (membership is not ours). */
const STAGES_FIXTURE = [
  { key: "applied", label: "applied", statuses: ["applied"], color: "var(--text-muted)" },
  {
    key: "interviewing",
    label: "interviewing",
    statuses: ["interviewing", "interview", "assessment"],
    color: "var(--viz-embeddings)",
  },
  { key: "offered", label: "offered", statuses: ["offered", "offer", "accepted"], color: "var(--green)" },
  { key: "rejected", label: "rejected", statuses: ["rejected", "rejection", "withdrawn"], color: "var(--red)" },
];

test("the settable stages are exactly the ones the API accepts, in its order", () => {
  // Same members AND same order as `ApplicationStatus` / the list
  // `GET /applications/statuses` serves, so wiring this module to that endpoint
  // later is a straight equality check rather than a set comparison.
  assert.deepEqual([...APPLICATION_STATUSES], API_ACCEPTS);
});

test("the value that returned 422 is not offered, and the one that was missing is", () => {
  assert.equal(isApplicationStatus("assessment"), false);
  assert.equal(isApplicationStatus("ghosted"), true);

  const offered = statusOptions("applied");
  assert.equal(
    offered.some((o) => o.value === "assessment"),
    false,
    "assessment is back in the dropdown; the API answers 422 to it",
  );
  assert.deepEqual(
    offered.filter((o) => !o.disabled).map((o) => o.value),
    [...APPLICATION_STATUSES],
  );
});

test("a row holding an unaccepted status shows THAT, disabled — never a substitute", () => {
  // The old control fell back to "applied" for anything it did not recognize,
  // i.e. it displayed a stage the row was not at.
  const options = statusOptions("assessment");
  assert.deepEqual(options[0], { value: "assessment", label: "assessment (legacy)", disabled: true });
  assert.equal(statusSelectValue("assessment"), "assessment");
  assert.deepEqual(
    options.slice(1).map((o) => o.value),
    [...APPLICATION_STATUSES],
  );

  const unknown = statusOptions(null);
  assert.deepEqual(unknown[0], { value: "", label: "unknown (legacy)", disabled: true });
  assert.equal(statusSelectValue(undefined), "");
});

test("statuses are compared normalized, so casing never desyncs the control", () => {
  assert.equal(normalizeStatus("  Applied "), "applied");
  assert.equal(statusSelectValue("REJECTED"), "rejected");
  assert.equal(
    statusOptions("Interviewing").some((o) => o.disabled),
    false,
    "a canonical status in another case must not be tagged legacy",
  );
});

test("the resolved column is headed `closed`, and nothing else is renamed", () => {
  assert.deepEqual(Object.keys(COLUMN_LABELS), ["rejected"]);
  assert.equal(COLUMN_LABELS.rejected, "closed");

  const columns = boardColumns(STAGES_FIXTURE);
  assert.deepEqual(
    columns.map((c) => c.label),
    ["applied", "interviewing", "offered", "closed"],
  );
  // Keys (membership) and colours are passed through untouched: the board still
  // groups exactly as `stageOf`/`summarizeCounts` do.
  assert.deepEqual(
    columns.map((c) => c.key),
    STAGES_FIXTURE.map((s) => s.key),
  );
  assert.deepEqual(
    columns.map((c) => c.color),
    STAGES_FIXTURE.map((s) => s.color),
  );
});

test("a card states its own status whenever its column heading does not", () => {
  // The measured bug: withdrawn under a heading that claimed "rejected".
  assert.equal(cardQualifier("withdrawn", "closed"), "withdrawn");
  assert.equal(cardQualifier("rejected", "closed"), "rejected");
  assert.equal(cardQualifier("accepted", "offered"), "accepted");
  // `ghosted` has no column of its own — `stageOf` drops it into `applied` —
  // so the card must say so rather than pass for a live application.
  assert.equal(cardQualifier("ghosted", "applied"), "ghosted");

  // The heading already said it: no badge.
  assert.equal(cardQualifier("applied", "applied"), null);
  assert.equal(cardQualifier("Interviewing", "interviewing"), null);
  assert.equal(cardQualifier("", "applied"), null);
  assert.equal(cardQualifier(null, "applied"), null);
});
