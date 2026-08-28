/**
 * Unit tests for `lib/applications/classify-request.ts` — BOTH rebuilds of the
 * classify body the proxy performs.
 *
 * The client side of this is already covered (`review-classify.test.mjs`
 * asserts the body carries `application_id` only when it is a real id). What
 * was NOT covered is the hops after it: the proxy REBUILDS the body twice —
 * once reading it, once sending it on — so any field neither names is silently
 * dropped. That has happened four times in this codebase — `confidence` in the
 * inbox relay, `applied_date` and `url` on create, and `confirm_new_company`
 * across both proxy hops, which shipped the near-miss employer confirmation
 * (#167 / PR #181) as a question with no answerable "no".
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

import {
  classifyBackendBody,
  readClassifyBody,
} from "../../lib/applications/classify-request.ts";
import { classifyRequestBody } from "../../lib/dashboard/review.ts";

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

// --- The scan message payload -----------------------------------------------
// Same defect shape as `application_id`, with a worse failure: the live scan's
// rows are verdicts about mail the backend has NEVER STORED, so this payload is
// the only thing that lets a correction land at all. Dropped here, every
// correction made from the scan view is a 404 with a working-looking UI in
// front of it.

test("the scan message survives the proxy, so a correction has something to land on", () => {
  const parsed = readClassifyBody({
    category: "assessment",
    message: {
      sender_email: "no-reply@hackerrank.harboranalytics.com",
      received_at: "2026-08-11T09:30:00Z",
      subject: "Your HackerRank assessment",
      sender_name: "Harbor Analytics",
      category: "other",
      confidence: 0,
      method: "rules",
    },
  });

  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.message, {
    sender_email: "no-reply@hackerrank.harboranalytics.com",
    received_at: "2026-08-11T09:30:00Z",
    subject: "Your HackerRank assessment",
    sender_name: "Harbor Analytics",
    category: "other",
    confidence: 0,
    method: "rules",
  });
});

test("confidence 0 is a real confidence and is not dropped as falsy", () => {
  // The complaint's own message scored 0%. A `if (m.confidence)` guard would
  // drop it and store the row with no verdict at all.
  const parsed = readClassifyBody({
    category: "assessment",
    message: { sender_email: "a@b.test", received_at: "2026-08-11T09:30:00Z", confidence: 0 },
  });

  assert.equal(parsed.message.confidence, 0);
});

test("a message with no sender or no receive time is refused, not half-forwarded", () => {
  // `Email.received_at` is NOT NULL and the employer is resolved from the
  // sender: forwarding either half turns an honest client-side refusal into a
  // 422 the reader has to interpret.
  const halves = [
    { received_at: "2026-08-11T09:30:00Z" },
    { sender_email: "a@b.test" },
    { sender_email: "   ", received_at: "2026-08-11T09:30:00Z" },
    { sender_email: "a@b.test", received_at: "  " },
    "not an object",
    null,
  ];
  for (const message of halves) {
    const parsed = readClassifyBody({ category: "assessment", message });
    assert.equal(parsed.ok, true);
    assert.equal(parsed.message, undefined, `expected ${JSON.stringify(message)} to be refused`);
  }
});

test("unknown keys on the message are dropped — the handler names what it sends", () => {
  const parsed = readClassifyBody({
    category: "offer",
    message: {
      sender_email: "a@b.test",
      received_at: "2026-08-11T09:30:00Z",
      body_text: "SHOULD NOT TRAVEL",
      user_id: "someone-else",
    },
  });

  assert.deepEqual(parsed.message, {
    sender_email: "a@b.test",
    received_at: "2026-08-11T09:30:00Z",
  });
});

// --- Answering the near-miss employer question (#167 / PR #181) -------------
//
// The backend asks before a company one edit from one already on the board
// opens a second application: it answers `needs_company_confirmation` with a
// `suggested_company` and files NOTHING. Two answers file it — re-send with
// the suggested spelling, or re-send with `confirm_new_company: true` to say
// the two employers are genuinely different.
//
// The second answer never arrived. `classifyRequestBody` built the flag and
// `review-classify.test.mjs` asserted it built it — and then BOTH rebuilds
// between the browser and FastAPI dropped it, because neither named the field.
// So "no — a different company" re-asked forever, and an employer one edit from
// one on the board could not be filed from the review queue at all. That is a
// worse and less recoverable outcome than the duplicate row the check prevents:
// the duplicate is a row to merge, this is an application that cannot exist.
//
// A test that stops one hop short of where a field is lost certifies the bug.
// These cross every hop.

test("the answer 'no, a different company' survives the proxy's read", () => {
  const parsed = readClassifyBody({
    category: "rejection",
    company: "Strive",
    confirm_new_company: true,
  });

  assert.equal(parsed.ok, true);
  assert.equal(parsed.confirmNewCompany, true);
});

test("the answer reaches the body the backend is actually sent", () => {
  const body = classifyBackendBody({
    category: "rejection",
    company: "Strive",
    confirmNewCompany: true,
  });

  assert.equal(body.confirm_new_company, true);
  assert.equal(body.company, "Strive");
});

test("browser to backend, whole: the confirmation crosses every rebuild", () => {
  // The real chain, in order, with a JSON round trip standing in for the wire:
  //   classifyRequestBody  (browser)  →  readClassifyBody  (proxy in)
  //                                   →  classifyBackendBody (proxy out)
  // Stripping the flag at ANY of the three makes this fail, which is the only
  // reason it is written as a chain rather than three isolated assertions.
  const fromBrowser = classifyRequestBody("rejection", "Strive", null, null, true);
  const parsed = readClassifyBody(JSON.parse(JSON.stringify(fromBrowser)));
  assert.equal(parsed.ok, true);

  const toBackend = classifyBackendBody(parsed);

  assert.deepEqual(toBackend, {
    category: "rejection",
    company: "Strive",
    confirm_new_company: true,
  });
});

// --- Answering "which application is this about?" with "none" (#554) --------
//
// The same trap, one field later, and this one is worse if it springs. An
// absent `application_id` means "nobody asked" — the single-candidate queue
// rows, the mail reclassify surface, the live scan — and the backend answers
// silence with `_pick_application`'s rule 4, the employer's OLDEST live row. On
// a rejection that moves a live application to a terminal status, which
// `advance_application_status` never walks back.
//
// So "none of these" cannot travel as an absent id. It has its own field, and
// if any hop drops it the request degrades to exactly the silence above — a
// green `tsc`, a working-looking UI, and a destroyed record. That is why the
// chain is asserted whole rather than at the browser end.

test("'none of these' survives the proxy's read", () => {
  const parsed = readClassifyBody({ category: "rejection", none_of_these: true });

  assert.equal(parsed.ok, true);
  assert.equal(parsed.noneOfThese, true);
});

test("'none of these' reaches the body the backend is actually sent", () => {
  const body = classifyBackendBody({ category: "rejection", noneOfThese: true });

  assert.equal(body.none_of_these, true);
});

test("browser to backend, whole: 'none of these' crosses every rebuild", () => {
  const fromBrowser = classifyRequestBody("rejection", "", "none");
  const parsed = readClassifyBody(JSON.parse(JSON.stringify(fromBrowser)));
  assert.equal(parsed.ok, true);

  assert.deepEqual(classifyBackendBody(parsed), {
    category: "rejection",
    none_of_these: true,
  });
});

test("browser to backend, whole: a PICKED row still crosses, and carries no flag", () => {
  // The control for the chain above. A rewrite that sets `none_of_these` from
  // "the id is absent" rather than from the user's answer would satisfy every
  // assertion in the previous test and mint a row for every anonymous
  // reclassify on the board.
  const fromBrowser = classifyRequestBody("rejection", "", 42);
  const parsed = readClassifyBody(JSON.parse(JSON.stringify(fromBrowser)));
  assert.equal(parsed.ok, true);

  assert.deepEqual(classifyBackendBody(parsed), {
    category: "rejection",
    application_id: 42,
  });
});

test("silence stays silence: an unanswered picker sends neither field", () => {
  // The other control, and the one the whole design turns on. "Nobody asked"
  // and "the user said none" must not produce the same body — if they do, the
  // flag is decoration and rule 4 still decides.
  const fromBrowser = classifyRequestBody("rejection", "", null);
  const parsed = readClassifyBody(JSON.parse(JSON.stringify(fromBrowser)));
  const toBackend = classifyBackendBody(parsed);

  assert.deepEqual(toBackend, { category: "rejection" });
  assert.equal("none_of_these" in toBackend, false);
  assert.equal("application_id" in toBackend, false);
});

test("'none of these' is never manufactured — only a literal true", () => {
  // This flag makes the backend OPEN A ROW rather than resolve one, so a
  // coerced truthy value mints applications nobody asked for.
  for (const raw of [undefined, false, null, 0, 1, "true", "false", "yes", {}, []]) {
    const parsed = readClassifyBody({ category: "rejection", none_of_these: raw });
    assert.equal(parsed.ok, true);
    assert.equal(
      parsed.noneOfThese,
      undefined,
      `none_of_these ${JSON.stringify(raw)} must not become an answer`,
    );
    assert.equal(
      "none_of_these" in classifyBackendBody(parsed),
      false,
      `none_of_these ${JSON.stringify(raw)} must not reach the backend`,
    );
  }
});

test("the flag is never manufactured — only a literal true is an answer", () => {
  // The safety half, and the one that decides whether forwarding this is
  // sound. `confirm_new_company` is the single input that makes the backend
  // SKIP the typo check, so coercing a truthy value into it would reintroduce
  // the silent acceptance by the back door — a "Verkeda" row opened because a
  // client sent the string "false", which is truthy.
  for (const raw of [undefined, false, null, 0, 1, "true", "false", "yes", {}, []]) {
    const parsed = readClassifyBody({ category: "rejection", confirm_new_company: raw });
    assert.equal(parsed.ok, true);
    assert.equal(
      parsed.confirmNewCompany,
      undefined,
      `confirm_new_company ${JSON.stringify(raw)} must not become an answer`,
    );
    assert.equal(
      "confirm_new_company" in classifyBackendBody(parsed),
      false,
      `confirm_new_company ${JSON.stringify(raw)} must not reach the backend`,
    );
  }
});

test("an unanswered classify sends no confirmation key at all", () => {
  // Omitted, not `false`. The backend's default and a caller who actively said
  // "no" have to stay distinguishable — the same rule `application_id` follows.
  const body = classifyBackendBody({ category: "interview" });

  assert.deepEqual(body, { category: "interview" });
});

test("the other three fields still cross the rebuild they were moved out of", () => {
  // `classifyBackendBody` was lifted out of `lib/applications/server.ts`, which
  // no test can load. Pin what it carries so the move itself cannot have
  // dropped the fields three earlier incidents were about.
  const message = { sender_email: "a@b.test", received_at: "2026-08-11T09:30:00Z" };
  const body = classifyBackendBody({
    category: "assessment",
    company: "  Globex  ",
    applicationId: 42,
    message,
  });

  assert.deepEqual(body, {
    category: "assessment",
    company: "Globex",
    application_id: 42,
    message,
  });
});
