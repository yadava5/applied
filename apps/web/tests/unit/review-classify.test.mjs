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
  canSubmitReview,
  classifyRequestBody,
  confirmCompanyPrompt,
  pickerAnswered,
  employerPromptFor,
  readClassifyOutcome,
  reviewCandidates,
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

/**
 * The body the backend returns when the company typed is one edit from one
 * already on the board — "Verkeda" against "Verkada". BOTH flags are set, and
 * that pairing is deliberate on the backend's side: a client that has never
 * heard of the confirmation still reads `needs_employer` and keeps the row in
 * the queue, rather than reading a resolved 2xx and dropping an item that filed
 * nothing (the Crusoe bug, at the presentation layer, again).
 */
const NEEDS_CONFIRMATION_BODY = {
  classified_as: "rejection",
  application_id: null,
  needs_employer: true,
  needs_company_confirmation: true,
  suggested_company: "Verkada",
  message_id: "198d0f2c9a1b4e78",
  detail:
    "'Verkeda' looks like 'Verkada', which is already on your board. Re-send with company='Verkada' to file this against it, or with 'confirm_new_company' to open a separate application.",
};

test("a near-miss company asks which employer it is, and files nothing", () => {
  const outcome = readClassifyOutcome(true, NEEDS_CONFIRMATION_BODY);

  assert.equal(outcome.kind, "needs-confirmation");
  assert.equal(outcome.suggestedCompany, "Verkada");
  assert.equal(rowStaysInQueue(outcome), true, "nothing was filed — the row must stay");
  assert.equal(outcome.messageId, "198d0f2c9a1b4e78");
  // The confirmation must WIN over the employer flag both are carrying, or the
  // suggestion is thrown away and the user is asked to type the name again —
  // which is how they typed the typo in the first place.
  assert.notEqual(outcome.kind, "needs-employer");
});

test("the question names the company; it never merges on the user's behalf", () => {
  assert.equal(confirmCompanyPrompt("Verkada"), "Did you mean Verkada? It's already on your board.");
  assert.match(confirmCompanyPrompt("Verkada"), /Verkada/);
  // Plain language, not the API's own wording.
  assert.notEqual(confirmCompanyPrompt("Verkada"), NEEDS_CONFIRMATION_BODY.detail);
});

test("the confirmation is honoured only when the flag is literally true and names something", () => {
  // Spoofed flags fall back to the employer prompt (which this body also
  // carries), never to a resolved 2xx.
  for (const spoof of [{ needs_company_confirmation: "true" }, { needs_company_confirmation: 1 }]) {
    const outcome = readClassifyOutcome(true, { ...NEEDS_CONFIRMATION_BODY, ...spoof });
    assert.equal(outcome.kind, "needs-employer", JSON.stringify(spoof));
  }
  // A confirmation with no name to offer is not a question anyone can answer.
  for (const empty of [undefined, null, "", "   ", 42]) {
    const outcome = readClassifyOutcome(true, {
      ...NEEDS_CONFIRMATION_BODY,
      suggested_company: empty,
    });
    assert.equal(outcome.kind, "needs-employer", `suggested_company: ${JSON.stringify(empty)}`);
  }
  // And a backend that has never sent the flag behaves exactly as before.
  assert.equal(readClassifyOutcome(true, NEEDS_EMPLOYER_BODY).kind, "needs-employer");
});

test("both answers to the question are real requests, and neither is the default", () => {
  // "Yes, it's the one on my board" — the suggested spelling, no override flag.
  assert.deepEqual(classifyRequestBody("rejection", "Verkada"), {
    category: "rejection",
    company: "Verkada",
  });
  // "No, these are two companies" — the typed spelling plus the acknowledgement.
  assert.deepEqual(classifyRequestBody("rejection", "Verkeda", null, null, true), {
    category: "rejection",
    company: "Verkeda",
    confirm_new_company: true,
  });
  // Never sent otherwise: an override that rides along by default is the silent
  // acceptance this whole round trip exists to stop.
  for (const off of [undefined, null, false, "true", 1]) {
    assert.deepEqual(
      classifyRequestBody("rejection", "Verkeda", null, null, off),
      { category: "rejection", company: "Verkeda" },
      `confirmNewCompany: ${JSON.stringify(off)}`,
    );
  }
});

test("the assign-to-application choice rides the body only when it is a real id", () => {
  // One employer can hold several applications; the picker's choice is sent as
  // `application_id`, which ReviewClassifyRequest accepts and validates.
  assert.deepEqual(classifyRequestBody("rejection", "", 42), {
    category: "rejection",
    application_id: 42,
  });
  assert.deepEqual(classifyRequestBody("rejection", "Amazon", 42), {
    category: "rejection",
    company: "Amazon",
    application_id: 42,
  });
  // UNANSWERED, or garbage → the field is simply not sent. This list used to
  // begin with the comment "not one of these, absent, or garbage", which is the
  // defect #554 is about written down as a contract: it made a deliberate human
  // answer and an unanswered control produce the same wire body. `"none"` is
  // now its own value and is asserted separately below.
  for (const empty of [undefined, null, 0, -1, 1.5, Number.NaN]) {
    assert.deepEqual(
      classifyRequestBody("rejection", "", empty),
      { category: "rejection" },
      `classifyRequestBody("rejection", "", ${String(empty)})`,
    );
  }
});

test('"none of these" is an answer on the wire, not the absence of one', () => {
  // The whole point: this body must be DISTINGUISHABLE from the one above.
  // Absent means "nobody asked", which the backend answers by tie-breaking onto
  // the employer's oldest live row. On a rejection that moves a live
  // application to a terminal status, and terminal is the one thing
  // `advance_application_status` will not walk back.
  assert.deepEqual(classifyRequestBody("rejection", "", "none"), {
    category: "rejection",
    none_of_these: true,
  });
  assert.deepEqual(classifyRequestBody("rejection", "Amazon", "none"), {
    category: "rejection",
    company: "Amazon",
    none_of_these: true,
  });

  // …and it is not the same body as a picked row, in either direction. Both
  // halves are asserted because one value builds both fields: a mapping that
  // sent `application_id` alongside the flag, or the flag alongside an id,
  // would leave the backend two answers to one question.
  const picked = classifyRequestBody("rejection", "", 42);
  assert.equal(picked.application_id, 42);
  assert.equal("none_of_these" in picked, false);
  const none = classifyRequestBody("rejection", "", "none");
  assert.equal("application_id" in none, false);
});

test("the submit gate blocks a shown picker that has not been answered", () => {
  const CATEGORY = "rejection";

  // The defect, stated as an assertion: a picker on screen with nothing chosen
  // must not be sendable.
  assert.equal(canSubmitReview(CATEGORY, true, null), false);

  // CONTROL — an answered picker sends. Without this, `() => false` passes the
  // line above and the queue stops working entirely.
  assert.equal(canSubmitReview(CATEGORY, true, 42), true);

  // CONTROL — "none of these" IS an answer. The fix adds a click; it does not
  // remove the option. Without this, "only a number counts" passes both lines
  // above and wedges every user whose message really is about no card shown.
  assert.equal(canSubmitReview(CATEGORY, true, "none"), true);

  // CONTROL — no picker, no extra click. This is the single-candidate employer
  // and it is most of the queue; without it, "always require an assignment"
  // passes everything above and puts a mandatory question on rows that have
  // none to ask.
  assert.equal(canSubmitReview(CATEGORY, false, null), true);

  // CONTROL — the stage is still required, picker or not. This is the rule that
  // was already there, and a rewrite that only looks at the assignment would
  // let an unclassified row be sent.
  assert.equal(canSubmitReview("", false, null), false);
  assert.equal(canSubmitReview("", true, 42), false);
});

test("pickerAnswered treats none as answered and null as not", () => {
  assert.equal(pickerAnswered(null), false);
  assert.equal(pickerAnswered("none"), true);
  assert.equal(pickerAnswered(42), true);
});

/** A board shaped like the owner's: several applications at one employer. */
const BOARD = [
  { id: 1, company: "Amazon", position: "SDE II, 2026", status: "applied" },
  { id: 2, company: "Amazon", position: "SDE, Database Services", status: "applied" },
  { id: 3, company: "Amazon", position: "SDE, AWS Data", status: "interviewing" },
  { id: 4, company: "Crusoe", position: "Software Engineer", status: "applied" },
  { id: 5, company: "GE", position: "Controls Engineer", status: "applied" },
];

test("reviewCandidates matches by company in sender/subject, conservatively", () => {
  // A rejection from amazon.jobs matches all three Amazon rows — the picker's
  // whole reason to exist — and nothing else.
  const matched = reviewCandidates(
    {
      sender_email: "no-reply@amazon.jobs",
      sender_name: "Amazon Jobs",
      subject: "Update on your application",
    },
    BOARD,
  );
  assert.deepEqual(
    matched.map((a) => a.id),
    [1, 2, 3],
  );

  // Nothing in the message names a company on the board → no question asked.
  assert.deepEqual(
    reviewCandidates(
      { sender_email: "noreply@lever.co", sender_name: null, subject: "Interview availability" },
      BOARD,
    ),
    [],
  );

  // Subject-only mentions count too (ATS mail often hides the employer there).
  assert.equal(
    reviewCandidates(
      { sender_email: "no-reply@myworkday.com", sender_name: null, subject: "Crusoe | Application Received" },
      BOARD,
    )[0]?.id,
    4,
  );
});

test("two-character companies only match the sender's domain label exactly", () => {
  // "GE" as a substring would match half an inbox ("get", "manager", …).
  assert.deepEqual(
    reviewCandidates(
      { sender_email: "recruiting@ge.com", sender_name: null, subject: "Your application" },
      BOARD,
    ).map((a) => a.id),
    [5],
  );
  assert.deepEqual(
    reviewCandidates(
      { sender_email: "noreply@greenhouse.io", sender_name: null, subject: "Getting started" },
      BOARD,
    ),
    [],
  );
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
