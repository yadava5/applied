/**
 * Unit tests for the stage list the board offers and the column it files a row
 * under.
 *
 * The bugs these guard, both measured on the live app:
 *
 *  1. The card's <select> carried its own literal array including
 *     `assessment` — a value the API did not accept at the time. Choosing it
 *     answered
 *
 *       422 · Input should be 'applied', 'interviewing', 'offered', 'rejected',
 *             'accepted', 'withdrawn' or 'ghosted'
 *
 *     while `ghosted`, which the API DOES accept, was absent from the dropdown.
 *     The list now lives in `lib/dashboard/status.ts` and the component imports
 *     it, so the assertion below is the dropdown's contents, not a parallel
 *     model of them. `assessment` became a real API status on 2026-08-12 and is
 *     back in the list — through the one definition, which is the fix; the bug
 *     was the second list, not the word.
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
import { STAGES, stageOf, summarizeCounts } from "../../lib/dashboard/summary.ts";

/**
 * Exactly the values named in the API's own 422, in the order it named them —
 * which is `ApplicationStatus`'s declaration order and what
 * `GET /applications/statuses` serves. Written out here rather than derived, so
 * a change to the frontend list has to be made deliberately in two places.
 */
const API_ACCEPTS = [
  "applied",
  "assessment",
  "interviewing",
  "offered",
  "rejected",
  "accepted",
  "withdrawn",
  "ghosted",
];

/**
 * The stages, imported from `summary.ts` — not a copy of them.
 *
 * This was a hand-written fixture until 2026-08-12, because `summary.ts`
 * value-imported through the `@/` alias and `node --test` cannot resolve it. A
 * fixture asserts the fixture: it would have gone on passing while `STAGES`
 * lost a stage's statuses entirely, and `stageOf`'s `?? "applied"` fallback
 * would have filed those rows under `applied` in silence. That import is now
 * relative, so this reads the real thing.
 */
const STAGES_FIXTURE = STAGES;

test("the settable stages are exactly the ones the API accepts, in its order", () => {
  // Same members AND same order as `ApplicationStatus` / the list
  // `GET /applications/statuses` serves, so wiring this module to that endpoint
  // later is a straight equality check rather than a set comparison.
  assert.deepEqual([...APPLICATION_STATUSES], API_ACCEPTS);
});

test("both values the dropdown used to get wrong are offered, and offered once", () => {
  // `assessment` was in the dropdown while the API refused it (422); `ghosted`
  // was accepted by the API and missing from the dropdown. One list, both fixed.
  assert.equal(isApplicationStatus("assessment"), true);
  assert.equal(isApplicationStatus("ghosted"), true);
  // A classifier category that is NOT a stage stays out — the two vocabularies
  // now share a member, which is exactly when they start being conflated.
  assert.equal(isApplicationStatus("follow_up"), false);
  assert.equal(isApplicationStatus("needs_review"), false);

  const offered = statusOptions("applied");
  assert.equal(
    offered.filter((o) => o.value === "assessment").length,
    1,
    "assessment must appear exactly once — it is one stage, not a legacy alias",
  );
  assert.deepEqual(
    offered.filter((o) => !o.disabled).map((o) => o.value),
    [...APPLICATION_STATUSES],
  );
});

test("a row holding an unaccepted status shows THAT, disabled — never a substitute", () => {
  // The old control fell back to "applied" for anything it did not recognize,
  // i.e. it displayed a stage the row was not at. `interview` (the classifier's
  // word, not the API's) stands in for the case `assessment` used to cover.
  const options = statusOptions("interview");
  assert.deepEqual(options[0], { value: "interview", label: "interview (legacy)", disabled: true });
  assert.equal(statusSelectValue("interview"), "interview");
  assert.deepEqual(
    options.slice(1).map((o) => o.value),
    [...APPLICATION_STATUSES],
  );

  // ... and a row at `assessment` is no longer one of those cases: it is a
  // real stage, so nothing about it is disabled.
  const assessment = statusOptions("assessment");
  assert.deepEqual(
    assessment.map((o) => o.value),
    [...APPLICATION_STATUSES],
  );
  assert.equal(
    assessment.some((o) => o.disabled),
    false,
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
    ["applied", "assessment", "interviewing", "offered", "closed"],
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

test("every settable status is claimed by a stage — none reaches the fallback", () => {
  // `stageOf` answers `applied` for anything it does not recognise, so a status
  // missing from every stage does not throw, does not fail a build and does not
  // look wrong: it is silently counted as applied. That is how `ghosted` was
  // counted as in-motion, and it is the one way `assessment` could have been
  // added everywhere else and still shown up in the wrong column.
  for (const status of APPLICATION_STATUSES) {
    const owner = STAGES.find((stage) => stage.statuses.includes(status));
    assert.ok(owner, `"${status}" belongs to no stage; stageOf would file it under "applied"`);
    assert.equal(stageOf(status), owner.key);
  }

  // ... and `assessment` specifically is its own stage, not folded anywhere.
  assert.equal(stageOf("assessment"), "assessment");
  assert.equal(stageOf("interviewing"), "interviewing");
});

test("assessment counts as in motion and as advanced, and never as applied", () => {
  const summary = summarizeCounts({ applied: 2, assessment: 3, interviewing: 1, rejected: 4 }, 10, 0);
  const counts = Object.fromEntries(summary.stages.map(({ stage, count }) => [stage.key, count]));

  assert.deepEqual(counts, { applied: 2, assessment: 3, interviewing: 1, offered: 0, rejected: 4 });
  // The board is in flow order, so the new stage is second.
  assert.deepEqual(
    summary.stages.map(({ stage }) => stage.key),
    ["applied", "assessment", "interviewing", "offered", "rejected"],
  );
  // An unmet deadline is the most live an application gets: in motion, and past
  // applied. 4 of 10 rows advanced (3 assessment + 1 interviewing).
  assert.equal(summary.inMotion, 6);
  assert.equal(summary.advancedPct, 40);
  assert.equal(summary.closed, 4);
});

test("a card states its own status whenever its column heading does not", () => {
  // The measured bug: withdrawn under a heading that claimed "rejected".
  assert.equal(cardQualifier("withdrawn", "closed"), "withdrawn");
  assert.equal(cardQualifier("rejected", "closed"), "rejected");
  assert.equal(cardQualifier("accepted", "offered"), "accepted");
  // `ghosted` has no column of its own — `stageOf` drops it into `applied` —
  // so the card must say so rather than pass for a live application.
  assert.equal(cardQualifier("ghosted", "applied"), "ghosted");

  // `assessment` has a column of its own now, so a card in it adds nothing —
  // under the old fold it sat below a heading that read "interviewing" and had
  // to contradict it, which is the same shape as the withdrawn/rejected bug.
  assert.equal(cardQualifier("assessment", "assessment"), null);
  assert.equal(cardQualifier("assessment", "interviewing"), "assessment");

  // The heading already said it: no badge.
  assert.equal(cardQualifier("applied", "applied"), null);
  assert.equal(cardQualifier("Interviewing", "interviewing"), null);
  assert.equal(cardQualifier("", "applied"), null);
  assert.equal(cardQualifier(null, "applied"), null);
});
