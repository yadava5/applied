/**
 * Unit tests for `errorDetail` in `lib/applications/export.ts`.
 *
 * The export proxy used to report every backend failure as the literal string
 * `"[object Object]"` (#490). The expression was:
 *
 *     detail: String(res.error ?? `Export failed while reading page ${page}`)
 *
 * `res.error` is the PARSED JSON body, so a 401 arrives as
 * `{detail: "unauthenticated"}` — an object, which `String()` renders
 * uselessly — and the `??` fallback never fired, because an object is not
 * nullish. The readable string beside it was unreachable in exactly the case
 * it was written for.
 *
 * Measured against production on 2026-08-23: `GET /api/applications` without a
 * session returned `{"detail":"[object Object]"}` while every sibling proxy
 * returned `{"detail":"unauthenticated"}`. This is the one feature whose whole
 * job is handing the user their data back.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { errorDetail } from "../../lib/applications/export.ts";

const FALLBACK = "Export failed while reading page 2";

test("the shape that actually shipped is no longer stringified", () => {
  // Exactly what openapi-fetch hands back for a 401 from this backend.
  const detail = errorDetail({ detail: "unauthenticated" }, FALLBACK);
  assert.equal(detail, "unauthenticated");
  assert.notEqual(detail, "[object Object]");
});

test("a plain string error passes through", () => {
  assert.equal(errorDetail("Backend rejected the request", FALLBACK), "Backend rejected the request");
});

test("an error with no usable message falls back", () => {
  // The `??` in the original could only ever fire for these two.
  assert.equal(errorDetail(undefined, FALLBACK), FALLBACK);
  assert.equal(errorDetail(null, FALLBACK), FALLBACK);
});

test("an object without a detail field falls back rather than stringifying", () => {
  // A pydantic validation error is a list, not a {detail: string}; whatever
  // arrives, the user must never be shown "[object Object]".
  for (const shape of [{}, { message: "nope" }, [{ loc: ["body"], msg: "bad" }], 42, true]) {
    const result = errorDetail(shape, FALLBACK);
    assert.equal(result, FALLBACK, `unexpected render for ${JSON.stringify(shape)}`);
    assert.ok(!result.includes("[object"), "never leak a stringified object");
  }
});

test("a blank or whitespace detail is not a message", () => {
  // An empty string is falsy-but-present: `??` would have kept it, and the
  // user would get a failure with no text at all.
  assert.equal(errorDetail({ detail: "" }, FALLBACK), FALLBACK);
  assert.equal(errorDetail({ detail: "   " }, FALLBACK), FALLBACK);
  assert.equal(errorDetail("", FALLBACK), FALLBACK);
});

test("a non-string detail inside the object falls back", () => {
  assert.equal(errorDetail({ detail: { nested: "object" } }, FALLBACK), FALLBACK);
  assert.equal(errorDetail({ detail: 500 }, FALLBACK), FALLBACK);
});
