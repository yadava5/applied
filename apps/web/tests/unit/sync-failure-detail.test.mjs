/**
 * The backend's failure sentence surviving the Next proxy (#848).
 *
 * WHAT WAS BROKEN. `POST /gmail/sync` answers a failed cursor stamp with a
 * sentence naming what survived — "3 filed and 1 queued of 4 scanned before it
 * failed; sync again to finish" (#643). `syncGmailPipeline` classified every
 * non-OK response from `status` and `headers` alone:
 *
 *     if (!res.ok) return classifyBadResponse(res.status, res.headers);
 *     return { kind: "ok", result: (await res.json()) as GmailSyncOutcome };
 *
 * `res.json()` was only ever reached on the OK path. The sentence was
 * reachable by direct API consumers and by tests, and by nothing a user would
 * ever see.
 *
 * Each test below names the mutation that reds it, because a test that passes
 * against the broken proxy is worth nothing.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { backendSyncDetail, withBackendSyncDetail } from "../../lib/gmail/sync-detail.ts";

/** Verbatim from `backend/jobtracker/cloud/gmail_oauth.py` — the sentence the
 *  whole issue exists to deliver. Kept literal so a reword on either side
 *  shows up as a diff here rather than as silence. */
const TYPED_500 =
  "Could not record this sync. 3 filed and 1 queued of 4 scanned before it failed; sync again to finish.";

/** What `classifyBadResponse` builds from a 500 with no body read. */
const GENERIC = { kind: "backend", message: "Backend responded 500", status: 500 };

// --- the extractor ----------------------------------------------------------

test("the typed 500's own sentence is what comes out", () => {
  // MUTATION: return null unconditionally -> red. This is the case the issue is.
  assert.equal(backendSyncDetail({ detail: TYPED_500 }), TYPED_500);
});

test("a body with nothing to quote yields null, so the caller keeps its generic", () => {
  // MUTATION: return String(body?.detail) -> red on every row here, and each
  // row is a shape a real failure actually produces.
  for (const body of [
    null, // res.json() threw: an HTML error page, a 502 from the edge
    undefined,
    {}, // the client transport's own `.catch(() => ({}))` fallback
    { message: "nope" }, // not the field this proxy emits
    [{ loc: ["body"], msg: "bad" }], // a pydantic validation error is a LIST
    { detail: "" },
    { detail: "   " }, // present, falsy-adjacent, and not a message
    { detail: 500 },
    { detail: { nested: "object" } }, // `String()` here shipped "[object Object]" once (#490)
    "a bare string body",
    42,
  ]) {
    assert.equal(
      backendSyncDetail(body),
      null,
      `unusable body was quoted to the reader: ${JSON.stringify(body)}`,
    );
  }
});

test("a quotable detail is trimmed, never blanked", () => {
  // MUTATION: drop the .trim() -> the rendered line opens with a stray space
  // after its separator. Cheap to get wrong, invisible in review.
  assert.equal(backendSyncDetail({ detail: `  ${TYPED_500}  ` }), TYPED_500);
});

// --- the proxy's decision ---------------------------------------------------

test("the backend failure carries the backend's sentence, replacing the generic", () => {
  // MUTATION: `return failure` unconditionally -> red. This IS the fix.
  const out = withBackendSyncDetail(GENERIC, { detail: TYPED_500 });
  assert.equal(out.message, TYPED_500);
  assert.equal(out.status, 500, "the status a reader can quote must survive");
  assert.equal(out.kind, "backend");
});

test("an unquotable body leaves the status-derived line intact", () => {
  // MUTATION: `{...failure, message: detail ?? ""}` -> red. A failure with no
  // text at all is worse than a generic one: the alert renders an empty
  // sentence and the reader has nothing to report.
  for (const body of [null, {}, { detail: "  " }]) {
    assert.deepEqual(withBackendSyncDetail(GENERIC, body), GENERIC);
  }
});

test("the kinds rendered from their kind are never rewritten", () => {
  // MUTATION: drop the `kind !== "backend"` guard -> red on all three. A
  // sentence written into `auth` or `rate_limited` lands in a field nothing
  // reads, which is exactly the shape of the bug being fixed.
  const others = [
    { kind: "auth", status: 401 },
    { kind: "unavailable" },
    { kind: "rate_limited", retryAfterSeconds: 60 },
  ];
  for (const failure of others) {
    assert.deepEqual(
      withBackendSyncDetail(failure, { detail: TYPED_500 }),
      failure,
      `${failure.kind} was rewritten with a message nothing renders`,
    );
  }
});

test("the input is not mutated in place", () => {
  // MUTATION: `failure.message = detail; return failure` -> red. React state
  // holds these; an in-place write is a stale-render bug that would not show
  // up in any assertion about the returned value.
  const original = { ...GENERIC };
  withBackendSyncDetail(original, { detail: TYPED_500 });
  assert.deepEqual(original, GENERIC);
});
