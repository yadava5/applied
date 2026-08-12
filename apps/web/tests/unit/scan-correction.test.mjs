/**
 * Unit tests for correcting a verdict in the LIVE SCAN view, and for the one
 * chip vocabulary both mail views now draw from.
 *
 * The complaint these exist for, verbatim: "this is clearly an assessment, but
 * I don't see anywhere to classify, and there is no field for showing anything
 * for assessment anywhere". Both halves are real and they are different bugs:
 *
 *   1. the scan view offered no correction at all — its rows are verdicts about
 *      mail the backend has never stored, so the classify endpoint answered 404
 *      for every one of them, and filing could not rescue them either (the sync
 *      drops everything below the 0.70 review floor, which the 0%-confidence
 *      message in the screenshot is);
 *   2. a chip only exists for a category some message HOLDS, so a correction
 *      that reaches the row but not the counts corrects a message into a
 *      category the reader still cannot see or filter by.
 *
 * `applyVerdictCorrection` is where (2) is decided, and the summary it moves is
 * usually the whole-set analysis from `POST /gmail/pipeline` — NOT a tally of
 * the rendered rows — so "just recompute it" is not available.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { classifyRequestBody } from "../../lib/dashboard/review.ts";
import {
  applyVerdictCorrection,
  scanMessagePayload,
  UNSTORABLE_ROW_NOTE,
} from "../../lib/gmail/scan-correction.ts";
import { categoryChips, chipTotal } from "../../lib/gmail/types.ts";

/** The owner's screenshot, as the mine reports it. */
const ASSESSMENT_CALLED_OTHER = {
  message_id: "m-1",
  subject: "Your HackerRank assessment for Software Engineer II",
  sender_email: "no-reply@hackerrank.harboranalytics.com",
  sender_name: "Harbor Analytics",
  category: "other",
  confidence: 0,
  method: "rules",
  needs_review: false,
  received_at: "2026-08-11T09:30:00Z",
  company: "harboranalytics",
};

const APPLIED_ROW = {
  message_id: "m-2",
  subject: "Thanks for applying",
  sender_email: "careers@northwind.test",
  sender_name: "Northwind",
  category: "applied",
  confidence: 0.94,
  method: "rules",
  needs_review: false,
  received_at: "2026-08-10T09:30:00Z",
  company: "northwind",
};

// --- The chip vocabulary -----------------------------------------------------

test("chips cover every canonical category the counts name, in pipeline order", () => {
  const chips = categoryChips({ other: 3, assessment: 1, applied: 2, offer: 1 });

  assert.deepEqual(
    chips.map((c) => c.value),
    ["applied", "assessment", "offer", "other"],
  );
  assert.equal(chips.find((c) => c.value === "assessment").label, "assessment");
  assert.equal(chips.find((c) => c.value === "assessment").count, 1);
});

test("a category this build has never heard of is still offered, never dropped", () => {
  // The scan view used to filter through CATEGORY_ORDER only, so a category
  // the backend added later was invisible rather than merely unstyled.
  const chips = categoryChips({ applied: 1, screening_call: 4 });

  assert.deepEqual(
    chips.map((c) => c.value),
    ["applied", "screening_call"],
  );
  assert.equal(chips.at(-1).label, "screening call", "an unknown value still reads as prose");
});

test("zero-count categories are omitted — a chip that filters to nothing is worse than none", () => {
  const chips = categoryChips({ applied: 2, assessment: 0, offer: -1 });

  assert.deepEqual(
    chips.map((c) => c.value),
    ["applied"],
  );
});

test("the all chip sums the same counts the chips are drawn from", () => {
  // Not the row count: the summary is the WHOLE-SET analysis and legitimately
  // covers more messages than the list is rendering.
  assert.equal(chipTotal({ applied: 2, assessment: 1, other: 3 }), 6);
  assert.equal(chipTotal({}), 0);
});

// --- Row → control props -----------------------------------------------------

test("a dated scan row yields the payload that lets the backend store it", () => {
  const payload = scanMessagePayload(ASSESSMENT_CALLED_OTHER);

  assert.deepEqual(payload, {
    sender_email: "no-reply@hackerrank.harboranalytics.com",
    received_at: "2026-08-11T09:30:00Z",
    subject: "Your HackerRank assessment for Software Engineer II",
    sender_name: "Harbor Analytics",
    category: "other",
    confidence: 0,
    method: "rules",
  });
});

test("the classifier's own verdict rides along, including a 0% confidence", () => {
  // Stored on the minted row so it starts as a faithful copy of what the
  // reader was looking at. A falsy-check would drop exactly this case.
  assert.equal(scanMessagePayload(ASSESSMENT_CALLED_OTHER).confidence, 0);
  assert.equal(scanMessagePayload(ASSESSMENT_CALLED_OTHER).category, "other");
});

test("an undated row yields no payload — the store refuses undated mail", () => {
  // `Email.received_at` is NOT NULL and `_persist_message_refs` skips undated
  // messages rather than fabricating a receive time. The control must say so
  // instead of firing a request that cannot succeed.
  assert.equal(scanMessagePayload({ ...ASSESSMENT_CALLED_OTHER, received_at: null }), null);
  assert.equal(scanMessagePayload({ ...ASSESSMENT_CALLED_OTHER, received_at: "   " }), null);
  assert.equal(scanMessagePayload({ ...ASSESSMENT_CALLED_OTHER, sender_email: "" }), null);
  assert.match(UNSTORABLE_ROW_NOTE, /date/i);
});

test("the payload rides on the classify body, on every attempt", () => {
  const payload = scanMessagePayload(ASSESSMENT_CALLED_OTHER);
  const first = classifyRequestBody("assessment", null, null, payload);
  const retry = classifyRequestBody("assessment", "Harbor Analytics", null, payload);

  assert.deepEqual(first, { category: "assessment", message: payload });
  assert.deepEqual(retry, {
    category: "assessment",
    company: "Harbor Analytics",
    message: payload,
  });
  // A filed row is stored by definition and sends nothing extra.
  assert.deepEqual(classifyRequestBody("assessment"), { category: "assessment" });
});

// --- Folding an accepted correction back into the mine -----------------------

test("a correction moves the ROW and the COUNTS together", () => {
  const state = {
    verdicts: [ASSESSMENT_CALLED_OTHER, APPLIED_ROW],
    // The whole-set analysis: it covers more messages than are rendered, which
    // is why it has to be moved rather than recomputed from the rows.
    summary: { other: 9, applied: 4 },
  };

  const next = applyVerdictCorrection(state, "m-1", "assessment");

  assert.equal(next.changed, true);
  assert.equal(next.verdicts[0].category, "assessment");
  assert.equal(next.verdicts[0].user_corrected, true);
  assert.equal(next.verdicts[0].needs_review, false);
  assert.equal(next.verdicts[1].category, "applied", "other rows are untouched");
  assert.deepEqual(next.summary, { other: 8, applied: 4, assessment: 1 });
  // The chip the complaint is about now exists.
  assert.ok(
    categoryChips(next.summary).some((c) => c.value === "assessment"),
    "an assessment chip must appear once a message holds that category",
  );
});

test("the machine's confidence is left alone — the user's label is not a 100% classifier", () => {
  const next = applyVerdictCorrection(
    { verdicts: [ASSESSMENT_CALLED_OTHER], summary: { other: 1 } },
    "m-1",
    "assessment",
  );

  assert.equal(next.verdicts[0].confidence, 0);
  assert.equal(next.verdicts[0].method, "rules");
});

test("the last message of a category takes its chip with it", () => {
  const next = applyVerdictCorrection(
    { verdicts: [ASSESSMENT_CALLED_OTHER], summary: { other: 1, applied: 4 } },
    "m-1",
    "assessment",
  );

  assert.deepEqual(next.summary, { applied: 4, assessment: 1 });
  assert.equal(
    categoryChips(next.summary).some((c) => c.value === "other"),
    false,
    "a category nothing holds any more must not keep an empty chip",
  );
});

test("nothing moves for an unknown message, an empty category, or the same category", () => {
  const state = { verdicts: [ASSESSMENT_CALLED_OTHER], summary: { other: 1 } };

  for (const [id, category] of [
    ["nope", "assessment"],
    ["m-1", ""],
    ["m-1", "other"],
  ]) {
    const next = applyVerdictCorrection(state, id, category);
    assert.equal(next.changed, false, `${id}/${category} should be a no-op`);
    assert.deepEqual(next.summary, { other: 1 });
    assert.deepEqual(next.verdicts, state.verdicts);
  }
});

test("the input state is never mutated — the caller decides what to keep", () => {
  const state = { verdicts: [ASSESSMENT_CALLED_OTHER], summary: { other: 1 } };
  applyVerdictCorrection(state, "m-1", "assessment");

  assert.equal(state.verdicts[0].category, "other");
  assert.deepEqual(state.summary, { other: 1 });
});
