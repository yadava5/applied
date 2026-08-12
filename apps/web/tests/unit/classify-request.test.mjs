/**
 * Unit tests for `lib/applications/classify-request.ts` — how the classify
 * proxy reads its request body.
 *
 * The client side of this is already covered (`review-classify.test.mjs`
 * asserts the body carries `application_id` only when it is a real id). What
 * was NOT covered is the hop after it: the route handler REBUILDS the body
 * rather than forwarding it, so any field it fails to name is silently
 * dropped. That has happened three times in this codebase — `confidence` in
 * the inbox relay, `applied_date` and `url` on create.
 *
 * Dropping `application_id` specifically is not a no-op. It is the user's
 * answer to "which of these is it about?" when an employer holds several
 * applications; without it the backend falls back to the employer's first row,
 * which is exactly the arbitrary-sibling filing `_pick_application` exists to
 * stop. So the user's explicit choice would be discarded and replaced with a
 * guess, with a 200 on the response.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readClassifyBody } from "../../lib/applications/classify-request.ts";

test("the user's choice of application survives the proxy", () => {
  const parsed = readClassifyBody({ category: "interview", application_id: 42 });

  assert.equal(parsed.ok, true);
  assert.equal(parsed.category, "interview");
  assert.equal(parsed.applicationId, 42);
});

test("a category is required, and whitespace is not a category", () => {
  for (const raw of [{}, { category: "" }, { category: "   " }, { category: 7 }, null]) {
    const parsed = readClassifyBody(raw);
    assert.equal(parsed.ok, false, `expected refusal for ${JSON.stringify(raw)}`);
    assert.equal(parsed.status, 422);
  }
});

test("an application id that is not a real integer is treated as absent, never coerced", () => {
  // Coercing any of these would send the backend an id the user never chose,
  // which is worse than falling back to the documented behaviour.
  for (const bad of ["42", 4.2, null, NaN, Infinity, true, {}]) {
    const parsed = readClassifyBody({ category: "offer", application_id: bad });
    assert.equal(parsed.ok, true);
    assert.equal(
      parsed.applicationId,
      undefined,
      `application_id ${JSON.stringify(bad)} should not become an id`,
    );
  }
});

test("a company is trimmed, and an empty one is omitted rather than sent blank", () => {
  assert.equal(readClassifyBody({ category: "offer", company: "  Acme  " }).company, "Acme");
  assert.equal(readClassifyBody({ category: "offer", company: "   " }).company, undefined);
  assert.equal(readClassifyBody({ category: "offer" }).company, undefined);
});

test("category is trimmed too, so a padded value is not rejected as missing", () => {
  assert.equal(readClassifyBody({ category: "  rejection " }).category, "rejection");
});

test("both optional fields ride together when both are given", () => {
  const parsed = readClassifyBody({
    category: "assessment",
    company: "Globex",
    application_id: 7,
  });

  assert.deepEqual(parsed, {
    ok: true,
    category: "assessment",
    company: "Globex",
    applicationId: 7,
  });
});
