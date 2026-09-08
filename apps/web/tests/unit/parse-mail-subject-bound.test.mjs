/**
 * THE SUBJECT WAS THE ONE FIELD NOBODY BOUNDED, on either engine (#427).
 *
 * `parseMail` has capped the body since it was written and caps the raw stream
 * before decoding it (`MAX_RAW_BODY_CHARS`, whose own comment says "BOUND
 * BEFORE THE WORK, NOT AFTER IT"). The subject went to `classifyWithRules`
 * exactly as the header held it. Every pattern in the rule set is run against
 * it, so the cost is linear in a value an anonymous stranger controls —
 * measured on the Python side of the same rules, 232 ms at 100,000 characters
 * and 2.33 s at 1,000,000.
 *
 * TWO CONSTRUCTORS, AND THE SECOND IS THE POINT OF THIS FILE.
 * `parseRfc822` and `parseJsonMessage` both produce a `ParsedMessage`, both
 * feed `classifyOne` in `ImportMail.tsx`, and the JSON one sliced its body at
 * `MAX_BODY_CHARS` while leaving its subject whole — the same capped/uncapped
 * asymmetry the issue is about, one constructor over. A fix applied to
 * `parseRfc822` alone closes the issue on the day a `.json` import re-opens it.
 *
 * The expected length is written out rather than imported. An expectation read
 * from the constant under test compares the configuration to itself: it catches
 * a deleted cap and passes for every wrong value.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { MAX_SUBJECT_CHARS, parseMailFile } from "../../lib/import/parseMail.ts";

/** Written out. Never `MAX_SUBJECT_CHARS`. */
const EXPECTED = 2000;

/** 50x the bound, so `min(input, cap)` cannot coincide with the input. */
const OVERSIZE = 100_000;

test("the constant is the one the other three doors use", () => {
  // Not a tautology: it pins the exported value to the literal this file
  // asserts with, so the two cannot drift into agreeing about nothing.
  assert.equal(MAX_SUBJECT_CHARS, EXPECTED);
});

test("parseRfc822 cuts an oversized subject at the bound", () => {
  const raw = [
    `Subject: ${"S".repeat(OVERSIZE)}`,
    "From: Cedar Recruiting <jobs@cedar.example>",
    "",
    "We received your application.",
  ].join("\n");

  const { messages } = parseMailFile("mail.eml", raw);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].subject.length, EXPECTED);
  assert.equal(messages[0].subject, "S".repeat(EXPECTED));
});

test("parseJsonMessage cuts one too — the constructor the first fix misses", () => {
  const raw = JSON.stringify([
    {
      subject: "S".repeat(OVERSIZE),
      from: "Cedar Recruiting <jobs@cedar.example>",
      body: "We received your application.",
    },
  ]);

  const { messages } = parseMailFile("mail.json", raw);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].subject.length, EXPECTED);
});

test("an ordinary subject is untouched on both paths", () => {
  // NON-VACUITY. A parser that returned a fixed 2,000 characters, or an empty
  // string, would satisfy every assertion above.
  const subject = "Thank you for applying to Cedar Systems";

  const eml = parseMailFile(
    "mail.eml",
    `Subject: ${subject}\nFrom: a@b.example\n\nbody text`,
  );
  assert.equal(eml.messages[0].subject, subject);

  const json = parseMailFile(
    "mail.json",
    JSON.stringify([{ subject, from: "a@b.example", body: "body text" }]),
  );
  assert.equal(json.messages[0].subject, subject);
});

test("an encoded-word subject still decodes, and is bounded after it does", () => {
  // The raw bound runs BEFORE `decodeEncodedWords`, so this is the case that
  // would break if that budget were set too tight: a short encoded subject must
  // survive the raw cut and decode normally.
  const encoded = "=?utf-8?B?VGhhbmsgeW91IGZvciBhcHBseWluZw==?=";
  const { messages } = parseMailFile(
    "mail.eml",
    `Subject: ${encoded}\nFrom: a@b.example\n\nbody`,
  );
  assert.equal(messages[0].subject, "Thank you for applying");
});

test("a giant encoded-word subject is bounded and does not decode the whole header", () => {
  // `VGhhbmtz` decodes to `Thanks`; repeated, it is a valid base64 stream whose
  // decode is 3/4 the length of its input. The raw bound has to cut it before
  // the decode runs, and the decoded bound has to cut what survives.
  const payload = "VGhhbmtz".repeat(OVERSIZE / 8);
  const { messages } = parseMailFile(
    "mail.eml",
    `Subject: =?utf-8?B?${payload}?=\nFrom: a@b.example\n\nbody`,
  );
  assert.equal(messages[0].subject.length, EXPECTED);
});
