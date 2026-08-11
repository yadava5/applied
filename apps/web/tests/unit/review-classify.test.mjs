/**
 * Unit tests for how the review queue reads a classify response.
 *
 * The bug these guard is a production incident: the owner classified
 * "Crusoe | Application Received", `POST /applications/review/{id}/classify`
 * answered 200 with `application_id: null`, the row left the queue and no
 * application was ever created. The backend is honest now — it returns
 * `needs_employer: true` and leaves the email un-reviewed — but a UI that reads
 * HTTP 200 as "done" reproduces the identical user-visible bug at the
 * presentation layer. So the two branches are asserted here directly:
 *
 *   needs_employer: true  → the row STAYS and the user is prompted
 *   re-submit + company   → the request carries it, the response resolves, the
 *                           row LEAVES
 *
 * `ReviewQueue.tsx` takes both decisions from this module and nowhere else, so
 * these assertions are the component's behaviour, not a parallel model of it.
 * (JSX cannot load under Node's built-in type stripping and the repo has no
 * component-test framework, which is why the branch logic lives in a plain
 * `.ts` module instead of inside the component.)
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  CLASSIFY_FAILED,
  MIN_COMPANY_LENGTH,
  NEEDS_EMPLOYER_PROMPT,
  NEEDS_EMPLOYER_RETRY,
  canNameCompany,
  classifyRequestBody,
  employerPromptFor,
  readClassifyOutcome,
  rowStaysInQueue,
} from "../../lib/dashboard/review.ts";

/** The exact body the backend now returns for the Crusoe message. */
const NEEDS_EMPLOYER_BODY = {
  classified_as: "applied",
  application_id: null,
  needs_employer: true,
  message_id: "198d0f2c9a1b4e77",
  detail:
    "Could not identify the employer for this email. Re-send the same classification with a 'company' to file it.",
};

test("needs_employer:true keeps the row in the queue and prompts for the company", () => {
  const outcome = readClassifyOutcome(true, NEEDS_EMPLOYER_BODY);

  assert.equal(outcome.kind, "needs-employer");
  assert.equal(rowStaysInQueue(outcome), true, "the row must NOT be removed on this 2xx");
  // `message_id` and `detail` must survive the proxy to the client.
  assert.equal(outcome.messageId, "198d0f2c9a1b4e77");
  assert.equal(outcome.detail, NEEDS_EMPLOYER_BODY.detail);
  // ...and the first-time wording is what the user is shown.
  assert.equal(employerPromptFor(""), NEEDS_EMPLOYER_PROMPT);
});

test("the prompt the user sees is plain language, not the API's own wording", () => {
  assert.notEqual(NEEDS_EMPLOYER_PROMPT, NEEDS_EMPLOYER_BODY.detail);
  assert.match(NEEDS_EMPLOYER_PROMPT, /company/i);
  assert.doesNotMatch(NEEDS_EMPLOYER_PROMPT, /re-send|classification/i);
});

test("a null application_id is not by itself read as a failure to file", () => {
  // "not job-related" legitimately files nothing and still leaves the queue.
  const outcome = readClassifyOutcome(true, {
    classified_as: "other",
    application_id: null,
    needs_employer: false,
  });
  assert.equal(outcome.kind, "resolved");
  assert.equal(outcome.applicationId, null);
  assert.equal(rowStaysInQueue(outcome), false);
});

test("re-submitting with a company sends it and, when it files, the row leaves", () => {
  // First half: the request actually carries the name the user typed.
  assert.deepEqual(classifyRequestBody("applied", "Crusoe"), {
    category: "applied",
    company: "Crusoe",
  });
  assert.deepEqual(classifyRequestBody("applied", "  Crusoe Energy  "), {
    category: "applied",
    company: "Crusoe Energy",
  });

  // Second half: the response that comes back files a row and clears the item.
  const outcome = readClassifyOutcome(true, {
    classified_as: "applied",
    application_id: 42,
    needs_employer: false,
  });
  assert.equal(outcome.kind, "resolved");
  assert.equal(outcome.applicationId, 42);
  assert.equal(rowStaysInQueue(outcome), false, "a filed application must clear the row");
});

test("no company is sent when the user has not supplied one", () => {
  for (const empty of [undefined, null, "", "   "]) {
    assert.deepEqual(
      classifyRequestBody("applied", empty),
      { category: "applied" },
      `classifyRequestBody("applied", ${JSON.stringify(empty)})`,
    );
  }
});

test("a company the backend still cannot use re-prompts instead of wedging", () => {
  // `pipeline.employer_from_text` rejects stopword-only and numeric strings, so
  // the second round trip can come back needs_employer:true as well — with a
  // company already typed. The row stays, and the wording changes so the user
  // can tell the re-submit was answered rather than ignored.
  const outcome = readClassifyOutcome(true, { ...NEEDS_EMPLOYER_BODY });
  assert.equal(outcome.kind, "needs-employer");
  assert.equal(rowStaysInQueue(outcome), true);

  assert.equal(employerPromptFor("The"), NEEDS_EMPLOYER_RETRY);
  assert.equal(employerPromptFor("  Crusoe  "), NEEDS_EMPLOYER_RETRY);
  assert.notEqual(NEEDS_EMPLOYER_RETRY, NEEDS_EMPLOYER_PROMPT);
  // Whitespace is not an answer — that is still the first-time prompt.
  assert.equal(employerPromptFor("   "), NEEDS_EMPLOYER_PROMPT);
});

test("the company input gates on the backend's own minimum length", () => {
  assert.equal(MIN_COMPANY_LENGTH, 2);
  assert.equal(canNameCompany(""), false);
  assert.equal(canNameCompany("   "), false);
  assert.equal(canNameCompany("a"), false);
  assert.equal(canNameCompany(" a "), false);
  assert.equal(canNameCompany("Ai"), true);
  assert.equal(canNameCompany("  Crusoe  "), true);
});

test("needs_employer is honoured only when it is literally true", () => {
  // Never invent the flag: a backend that omits it behaves as it always did.
  for (const body of [
    { application_id: 7 },
    { application_id: null, needs_employer: false },
    { application_id: null, needs_employer: "true" },
    { application_id: null, needs_employer: 1 },
  ]) {
    assert.equal(
      readClassifyOutcome(true, body).kind,
      "resolved",
      `readClassifyOutcome(true, ${JSON.stringify(body)})`,
    );
  }
});

test("a rejected request reports the backend's reason and keeps the row", () => {
  const outcome = readClassifyOutcome(false, { detail: "Review item not found." });
  assert.equal(outcome.kind, "failed");
  assert.equal(outcome.detail, "Review item not found.");
  assert.equal(rowStaysInQueue(outcome), true);

  // No parseable body (or no reason given) still says something usable.
  for (const body of [{}, null, undefined, "<html>502</html>", { detail: 500 }]) {
    const fallback = readClassifyOutcome(false, body);
    assert.equal(fallback.kind, "failed");
    assert.equal(fallback.detail, CLASSIFY_FAILED, `readClassifyOutcome(false, ${JSON.stringify(body)})`);
  }
});
