/**
 * THREE BOUNDS ON `/import`, AND THE INPUT EACH ONE WAS MISSING.
 *
 * `/import` is public, needs no account, and parses on the main thread of the
 * visitor's tab with no worker, no progress and no cancel. Everything the
 * parser is handed is therefore either bounded or a freeze.
 *
 * 1. THE BODY WAS DECODED IN FULL AND THEN THROWN AWAY. `MAX_BODY_CHARS`
 *    truncates the decode's OUTPUT, so a 33 MB quoted-printable body cost
 *    888 ms and +334 MB of heap to produce 8,000 characters. `decodeBody`
 *    bounds its INPUT now (MAX_RAW_BODY_CHARS).
 *
 * 2. THE `.eml` PATH HAD NO MESSAGE CAP AT ALL — `raws = [text.trim()]`, where
 *    the mbox path has DEFAULT_MESSAGE_CAP. It refuses now, with a sentence,
 *    rather than truncating: classifying the first N bytes of somebody's mail
 *    and reporting the verdict as though it were about the message is worse
 *    than saying no.
 *
 * 3. ONE `null` IN A JSON BATCH DISCARDED THE WHOLE FILE:
 *      TypeError: Cannot read properties of null (reading 'subject')
 *    `ImportMail.ingest` wraps the entire parse in one try/catch, so 400 good
 *    records became "Couldn't parse that file" — the same shape as the
 *    prototype-pollution bug fixed in #404, arriving through the other input.
 *
 * EVERY BOUND HERE IS TESTED FROM BOTH SIDES. A limit that only ever refuses
 * has not been shown to leave real mail alone, and that is the half that costs
 * a user their import.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_BODY_CHARS,
  MAX_SINGLE_MESSAGE_CHARS,
  MailTooLargeError,
  parseMailFile,
  parseRfc822,
} from "../../lib/import/parseMail.ts";

const eml = (headers, body) => `${headers}\r\n\r\n${body}`;

/** base64 of the UTF-8 bytes — `btoa` alone refuses anything past Latin-1. */
const b64 = (text) =>
  btoa(Array.from(new TextEncoder().encode(text), (b) => String.fromCharCode(b)).join(""));

// ---------------------------------------------------------------------------
// 1. The decode is bounded before it runs
// ---------------------------------------------------------------------------

test("a 33MB quoted-printable body is not decoded in full to keep 8,000 characters", () => {
  // `=41` is "A": three raw characters per output character, the worst honest
  // expansion ratio quoted-printable has.
  const raw = eml(
    "Subject: Update\r\nFrom: talent@cedar.example\r\nContent-Transfer-Encoding: quoted-printable",
    "=41".repeat(11_000_000),
  );

  const started = performance.now();
  const msg = parseRfc822(raw, "m0");
  const elapsed = performance.now() - started;

  assert.equal(msg.body.length, MAX_BODY_CHARS);
  assert.ok(
    /^A+$/.test(msg.body),
    "the body is not the decoded text, so the bound cut something it should not have",
  );
  assert.ok(
    elapsed < 200,
    `parseRfc822 took ${elapsed.toFixed(0)}ms on a 33MB quoted-printable body. It cost 888ms before MAX_RAW_BODY_CHARS; the truncation has moved back after the decode.`,
  );
});

test("a base64 body larger than the bound still decodes to text, not to base64", () => {
  /**
   * THE MID-QUANTUM CUT. base64 is read four characters at a time and real
   * base64 is line-wrapped, so stripping the newlines out of a CUT stream
   * leaves a length that need not be a multiple of four. `atob` throws on that,
   * and `base64ToUtf8`'s catch would then hand the classifier the RAW BASE64 to
   * score — a body made of `VGhhbmtz…` instead of words.
   *
   * THE TWO LOOPS ARE THE POINT, not decoration. `atob` implements forgiving
   * base64: a survivor whose length leaves a remainder of 2 or 3 is decoded as
   * unpadded, and ONLY a remainder of 1 throws. Cutting at MAX_RAW_BODY_CHARS
   * removes one character per line break for `\n` and two for `\r\n`, so a
   * CRLF-wrapped body can never land on that remainder and a single CRLF
   * fixture proves nothing — the first draft of this test was exactly that, and
   * it passed with the guard deleted.
   *
   * `\n` is not the exotic half of this either. `splitMbox` rejoins every
   * message with `\n`, so the format `/import` exists to read hands this
   * function LF-wrapped base64 as a matter of course.
   */
  const plain = "Thanks for applying to Cedar. ".repeat(40_000); // 1.2 MB
  const encoded = btoa(plain);

  for (const eol of ["\r\n", "\n"]) {
    const wrapped = (encoded.match(/.{1,76}/g) ?? []).join(eol); // as a mailer emits it

    // Each extra leading blank line shifts the cut by one line break, walking
    // the survivor's length through every remainder mod 4.
    for (let blankLines = 0; blankLines < 8; blankLines++) {
      const where = `${JSON.stringify(eol)} + ${blankLines} blank line(s)`;
      const msg = parseRfc822(
        eml(
          "Subject: Update\r\nFrom: talent@cedar.example\r\nContent-Transfer-Encoding: base64",
          eol.repeat(blankLines) + wrapped,
        ),
        "m0",
      );

      assert.equal(msg.body.length, MAX_BODY_CHARS, where);
      assert.ok(
        msg.body.startsWith("Thanks for applying to Cedar."),
        `at ${where} the base64 was not decoded — the classifier is being handed ${JSON.stringify(msg.body.slice(0, 40))}`,
      );
    }
  }
});

test("the bound leaves an ordinary mail's body byte-identical", () => {
  /**
   * THE CONTROL, and the half that matters to a real import. Every assertion
   * above is satisfied by a `decodeBody` that returns "". These are the three
   * shapes `/import` actually meets, each with the whole of its text well
   * inside the bound, compared against the exact string it should produce.
   */
  const text = "Hi Nadia — we would like to schedule a 30 minute interview next Thursday.";

  const plain = parseRfc822(eml("Subject: Interview\r\nFrom: talent@cedar.example", text), "m0");
  assert.equal(plain.body, text);

  const qp = parseRfc822(
    eml(
      "Subject: Interview\r\nFrom: talent@cedar.example\r\nContent-Transfer-Encoding: quoted-printable",
      "Hi Nadia =E2=80=94 we would like to schedule a 30 minute interview next Thursday.",
    ),
    "m0",
  );
  assert.equal(qp.body, text);

  const fromB64 = parseRfc822(
    eml(
      "Subject: Interview\r\nFrom: talent@cedar.example\r\nContent-Transfer-Encoding: base64",
      b64(text),
    ),
    "m0",
  );
  assert.equal(fromB64.body, text);
});

test("a markup-heavy HTML mail is unaffected: the bound is on the raw, and markup is most of it", () => {
  // 30 characters of text per ~120 characters of markup, repeated until the
  // raw body is 240 KB — under MAX_RAW_BODY_CHARS, which is the point: a real
  // newsletter-shaped mail is nowhere near it.
  const cell = (i) =>
    `<table><tr><td style="font-family:Helvetica;font-size:14px;color:#333333" class="body-cell-${i}">Update number ${i}. </td></tr></table>`;
  const parts = [];
  let html = "";
  for (let i = 0; html.length < 240_000; i++) {
    parts.push(`Update number ${i}.`);
    html += cell(i);
  }

  const msg = parseRfc822(
    eml("Subject: Update\r\nFrom: news@cedar.example\r\nContent-Type: text/html", html),
    "m0",
  );

  assert.equal(msg.body, parts.join(" ").slice(0, MAX_BODY_CHARS));
});

test("a multipart body is still split whole, so the bound cannot lose a part", () => {
  /**
   * WHY THE BOUND IS AT `decodeBody` AND NOT AT `extractText`. `extractText`
   * splits a multipart body on its boundary before any part is decoded, so a
   * bound applied to the container would cut it mid-part and the `text/plain`
   * part — which may be the LAST one — would never be found. Here the plain
   * part sits behind 300 KB of HTML, past MAX_RAW_BODY_CHARS.
   */
  const filler = `<p>${"x".repeat(300_000)}</p>`;
  const body =
    `--BOUND\r\nContent-Type: text/html\r\n\r\n${filler}\r\n` +
    "--BOUND\r\nContent-Type: text/plain\r\n\r\nAre you free Thursday?\r\n" +
    "--BOUND--\r\n";

  const msg = parseRfc822(
    eml(
      'Subject: Interview\r\nFrom: talent@cedar.example\r\nContent-Type: multipart/alternative; boundary="BOUND"',
      body,
    ),
    "m0",
  );

  assert.equal(msg.body.trim(), "Are you free Thursday?");
});

// ---------------------------------------------------------------------------
// 2. The single-message path is bounded, and refuses rather than truncating
// ---------------------------------------------------------------------------

test("a single .eml larger than any deliverable message is refused, with a sentence", () => {
  const raw = eml(
    "Subject: Update\r\nFrom: talent@cedar.example",
    "x".repeat(MAX_SINGLE_MESSAGE_CHARS + 1),
  );

  assert.throws(
    () => parseMailFile("one.eml", raw),
    (err) => {
      assert.ok(
        err instanceof MailTooLargeError,
        `a plain Error reaches ImportMail's generic "Couldn't parse that file" branch, which blames the file's FORMAT for a problem with its SIZE. Got ${err.constructor.name}.`,
      );
      assert.match(err.message, /\d+MB/, "the refusal does not tell the visitor how big the file is");
      assert.match(err.message, /\.mbox/, "the refusal does not say what to do about it");
      return true;
    },
  );
});

test("a message at the bound is still classified, so the refusal is not the behaviour", () => {
  /**
   * THE OTHER SIDE. A bound set below real mail would refuse a legitimate
   * export, so this parses a message sitting EXACTLY on the limit and asserts
   * it comes back whole — and separately that the limit is above what a
   * provider will actually carry (Gmail: 25 MB of attachments, ~34 MB once
   * base64 has expanded them).
   */
  assert.ok(
    MAX_SINGLE_MESSAGE_CHARS >= 34_000_000,
    `MAX_SINGLE_MESSAGE_CHARS is ${MAX_SINGLE_MESSAGE_CHARS}, below the ~34MB a 25MB Gmail attachment becomes on the wire — the bound now refuses mail that really exists.`,
  );

  const headers = "Subject: Interview scheduling\r\nFrom: Talent <talent@cedar.example>";
  const filler = "y".repeat(MAX_SINGLE_MESSAGE_CHARS - headers.length - 4);
  const result = parseMailFile("one.eml", eml(headers, filler));

  assert.equal(result.messages.length, 1);
  assert.equal(result.messages[0].subject, "Interview scheduling");
  assert.equal(result.messages[0].senderEmail, "talent@cedar.example");
  assert.equal(result.unreadable, 0);
});

test("the cap does not reach the mbox path, which supports far larger files on purpose", () => {
  /**
   * A 520 MB Takeout mbox holding 786,800 messages is a SUPPORTED input on
   * this page — `ImportMail.onFile` documents the measurement. The bound added
   * here is on the single-message format, and this is the assertion that keeps
   * it there: the same bytes that are refused as one `.eml` are read as an
   * mbox, because as an mbox they are not one message.
   */
  const one = (i) =>
    `From nobody@localhost\r\nFrom: talent@cedar.example\r\nSubject: Role ${i}\r\n\r\n${"z".repeat(200_000)}\r\n\r\n`;
  const text = Array.from({ length: 220 }, (_, i) => one(i)).join("");

  assert.ok(text.length > MAX_SINGLE_MESSAGE_CHARS, "the fixture is not over the single-message cap");
  const result = parseMailFile("export.mbox", text);
  assert.equal(result.messages.length, 220);
});

// ---------------------------------------------------------------------------
// 3. One bad entry in a JSON batch
// ---------------------------------------------------------------------------

const GOOD = [
  { subject: "Interview scheduling", from: "talent@cedar.example", body: "Are you free Thursday?" },
  { subject: "Thanks for applying", from: "noreply@cedar.example", body: "We received it." },
];

test("a well-formed batch loses nothing — the control for the two tests below", () => {
  const result = parseMailFile("batch.json", JSON.stringify(GOOD));

  assert.equal(result.totalFound, 2);
  assert.equal(result.messages.length, 2);
  assert.equal(result.unreadable, 0);
  assert.deepEqual(
    result.messages.map((m) => m.subject),
    ["Interview scheduling", "Thanks for applying"],
  );
});

test("a null entry is skipped and counted, not thrown", () => {
  const result = parseMailFile("batch.json", JSON.stringify([null, ...GOOD]));

  assert.equal(result.totalFound, 3);
  assert.equal(
    result.messages.length,
    2,
    "the good records did not survive the bad one, which is the whole defect",
  );
  assert.equal(
    result.unreadable,
    1,
    "the dropped record is not in the count, so the UI's summary sentence is false about it",
  );
});

test("every non-object entry behaves the same way, whatever it is", () => {
  /**
   * PINNED AS A SHAPE RATHER THAN AS `null`. `null` and `undefined` were the
   * two that threw; a number, a boolean or a string never did, because
   * property access on them yields `undefined` and the record simply came out
   * empty. Asserting only `null` would leave a fix that special-cased that one
   * value looking correct.
   */
  for (const bad of [null, 7, true, "a string", []]) {
    const result = parseMailFile("batch.json", JSON.stringify([bad, ...GOOD]));

    assert.equal(result.totalFound, 3, `entry ${JSON.stringify(bad)}`);
    assert.equal(result.messages.length, 2, `entry ${JSON.stringify(bad)}`);
    assert.equal(result.unreadable, 1, `entry ${JSON.stringify(bad)}`);
  }
});
