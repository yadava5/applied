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

/**
 * THE RAW BUDGET MUST NOT STARVE THE DECODED BOUND, and the first version did.
 *
 * `MAX_RAW_SUBJECT_CHARS` was 8,000, justified as "four raw characters yield
 * three bytes, so 2,000 decoded characters need at most ~2,667 raw ones" —
 * which counts BYTES and spends them as CHARACTERS. Measured against
 * `decodeEncodedWords` itself, at 8,000 raw:
 *
 *     B-encoded  ASCII 5706   CJK 2078   emoji 2668
 *     Q-encoded  ASCII 7412   CJK 1412   emoji 1358   <- under the bound
 *
 * Quoted-printable spends three raw characters per byte, so a four-byte
 * character costs twelve. A Q-encoded CJK subject reached the classifier 30%
 * short of the bound it was supposed to get, on well-formed mail.
 *
 * This is the guard. It is parametrized over BOTH encodings and three byte
 * widths, because ASCII passes at 8,000 under either constant and would have
 * shown nothing.
 */
const b64Word = (s) => "=?utf-8?B?" + Buffer.from(s, "utf8").toString("base64") + "?=";
const qWord = (s) =>
  "=?utf-8?Q?" +
  [...Buffer.from(s, "utf8")]
    .map((b) =>
      b >= 33 && b <= 126 && b !== 61 && b !== 63 && b !== 95
        ? String.fromCharCode(b)
        : "=" + b.toString(16).toUpperCase().padStart(2, "0"),
    )
    .join("") +
  "?=";

for (const [encoding, word] of [
  ["B", b64Word],
  ["Q", qWord],
])
  for (const [width, unit] of [
    ["1-byte", "abcdefghij"],
    ["3-byte", "日本語テスト"],
    ["4-byte", "🙂"],
  ])
    test(`a ${encoding}-encoded ${width} subject still fills the decoded bound`, () => {
      const words = [];
      while (words.join(" ").length < 40_000) words.push(word(unit.repeat(15)));
      const raw = words.join(" ");

      const { messages } = parseMailFile(
        "s.eml",
        `Subject: ${raw}\nFrom: a@b.example\n\nbody`,
      );
      // The raw cut must leave at least a full decoded bound behind it, or the
      // subject the classifier reads is shorter for non-ASCII mail than for
      // ASCII — a different classifier per language, which is the asymmetry
      // this whole change exists to remove.
      assert.equal(messages[0].subject.length, EXPECTED);
    });
