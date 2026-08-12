/**
 * Unit tests for `lib/dashboard/detail.ts` — the reader that turns a detail
 * response into what the sheet renders.
 *
 * These exist because the split surface shipped unreachable. The backend has
 * sent `split_candidates` since the entity-model work landed, and every field
 * in the fixtures below is copied from the live contract
 * (`SplitCandidateResponse` in `backend/jobtracker/cloud/applications.py`):
 *
 *     role: str | None
 *     req_id: str | None
 *     message_ids: list[str]
 *     retains_row: bool
 *
 * The reader was looking for `position`, which the backend has never sent. Every
 * candidate failed the guard and was filtered out, so `splitCandidates` was
 * always `[]`, `SplitPrompt` returns null below a length of 2, and the whole
 * "this looks like N applications — split them?" surface could not mount for
 * anyone. Two stale TODO comments — one in each file — asserted that the
 * backend field did not exist yet, which is how it survived review.
 *
 * The lesson these tests encode: a reader that silently drops what it cannot
 * parse turns a field-name typo into a feature that is simply absent, with no
 * error anywhere. So they assert against the real wire shape, not against the
 * shape the reader happens to want.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readApplicationDetail } from "../../lib/dashboard/detail.ts";

/** A response body in exactly the shape FastAPI serialises. */
function detailBody(candidates) {
  return {
    application: {
      id: 42,
      company: "Amazon",
      position: "Software Development Engineer - 2026 (US)",
      status: "applied",
      notes: null,
      created_at: "2026-08-11T00:00:00",
      applied_date: "2026-08-11",
      source: "gmail",
      url: null,
    },
    messages: [],
    split_candidates: candidates,
  };
}

test("a merged row's split candidates survive the read", () => {
  const detail = readApplicationDetail(
    detailBody([
      {
        role: "Software Development Engineer - 2026 (US)",
        req_id: "3177934",
        message_ids: ["m1", "m2"],
        retains_row: true,
      },
      {
        role: "Software Development Engineer – Database 2026 (US)",
        req_id: "3130865",
        message_ids: ["m3"],
        retains_row: false,
      },
    ]),
  );

  // The whole point: two candidates in, two candidates out. Before the fix this
  // was [] and the prompt could never reach its `length >= 2` gate.
  assert.equal(detail.splitCandidates.length, 2);
  assert.equal(
    detail.splitCandidates[0].role,
    "Software Development Engineer - 2026 (US)",
  );
  assert.equal(detail.splitCandidates[0].req_id, "3177934");
  assert.deepEqual(detail.splitCandidates[0].message_ids, ["m1", "m2"]);
  assert.equal(detail.splitCandidates[0].retains_row, true);
  assert.equal(detail.splitCandidates[1].retains_row, false);
});

test("a role-less cluster is kept, because the backend really does send one", () => {
  // `role` is `str | None` on the wire and the retained cluster is exactly where
  // role-less mail collects — a verification email that names no requisition.
  // Dropping it would under-count the clusters and could pull a genuine
  // two-application row back below the prompt's threshold, hiding the split
  // for the rows that most need it.
  const detail = readApplicationDetail(
    detailBody([
      { role: null, req_id: null, message_ids: ["m1"], retains_row: true },
      { role: "TPU Kernel Engineer", req_id: null, message_ids: ["m2"], retains_row: false },
    ]),
  );

  assert.equal(detail.splitCandidates.length, 2);
  assert.equal(detail.splitCandidates[0].role, null);
});

test("the ordinary row offers nothing to split", () => {
  // Empty is the normal case and must stay empty — a prompt on a row with one
  // application would be an invitation to break it.
  assert.deepEqual(readApplicationDetail(detailBody([])).splitCandidates, []);
});

test("junk in the candidates array cannot crash the sheet", () => {
  const detail = readApplicationDetail(
    detailBody([
      null,
      "nonsense",
      { role: "Real Role", req_id: null, message_ids: ["m1"], retains_row: false },
      { role: "No ids", message_ids: "not-an-array", retains_row: false },
    ]),
  );

  // Two survive: the well-formed one, and the one whose only fault is a bad
  // message_ids — which degrades to [] rather than discarding the candidate.
  assert.equal(detail.splitCandidates.length, 2);
  assert.deepEqual(detail.splitCandidates[1].message_ids, []);
});

test("a missing split_candidates key reads as nothing to offer", () => {
  const body = detailBody([]);
  delete body.split_candidates;
  assert.deepEqual(readApplicationDetail(body).splitCandidates, []);
});
