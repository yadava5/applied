/**
 * Unit tests for the HTML → text reduction in the in-browser mail parser
 * (`lib/import/parseMail.ts`), and for the fixture the /import page ships.
 *
 * These exist for two CodeQL alerts on the old chained-regex `stripHtml`, both
 * of which are ordinary correctness bugs before they are anything else — the
 * text this function returns is what the on-device rules classifier scores, so
 * a message it mangles is filed against words the sender never wrote:
 *
 *  1. `js/bad-tag-filter` — `/<script[\s\S]*?<\/script>/` only recognises the
 *     one end-tag shape `</script>`. HTML closes an element on `</script`
 *     followed by whitespace, `/` or `>`, so `</script >`, `</style\n>` and
 *     `</script foo=bar>` all left the element's contents in the extracted
 *     text. The same rigidity ran through `<[^>]+>`, which cannot see an
 *     attribute value containing `>` and mistakes the rest of the tag for
 *     prose.
 *  2. `js/double-escaping` — entities were decoded as a CHAIN of replacements,
 *     `&amp;` first, so `&amp;lt;` became `&lt;` became `<`. Text that was
 *     escaped precisely so it would NOT be markup came out as markup. The
 *     property the fix has to hold is that no replacement ever re-reads
 *     another's output: one pass, each `&…;` resolved once.
 *
 * Neither was a live XSS — the parsed body reaches the DOM only through React
 * text nodes — but a sanitizer that does not sanitize is a landmine, and the
 * corruption is real regardless of where the text is rendered.
 *
 * The last block is a guard, not a feature: the /import page's screen capture
 * is recorded against the inline `sample.mbox` fixture and its counters (4
 * scanned / 3 auto-filed / 1 held). Classification is a pure function of
 * subject + body + sender, so pinning this parse pins those counters. The
 * fixture is read out of the component that ships it rather than copied here —
 * a copy is a twin, and twins drift.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parseMailFile, stripHtml } from "../../lib/import/parseMail.ts";
import { readSource } from "./helpers/renderTsx.mjs";

// --- End-tag shape: alert 58, js/bad-tag-filter -----------------------------

test("script contents are dropped whatever shape the end tag takes", () => {
  assert.equal(stripHtml("A<script>alert(1)</script>B"), "A B");
  assert.equal(stripHtml("A<script >alert(1)</script >B"), "A B");
  assert.equal(stripHtml("A<script>alert(1)</script\n>B"), "A B");
  assert.equal(stripHtml("A<script>alert(1)</script foo=bar>B"), "A B");
  assert.equal(stripHtml("A<SCRIPT>alert(1)</SCRIPT\t>B"), "A B");
});

test("style contents are dropped whatever shape the end tag takes", () => {
  assert.equal(stripHtml("A<style>p{color:red}</style>B"), "A B");
  assert.equal(stripHtml("A<style>p{color:red}</style >B"), "A B");
  assert.equal(stripHtml("A<style type='text/css'>p{color:red}</style\n>B"), "A B");
});

test("an unterminated script eats to the end rather than leaking its source", () => {
  assert.equal(stripHtml("keep me<script>alert(1);document.cookie"), "keep me");
});

test("a tag is read to its real end, not to the first `>` inside an attribute", () => {
  assert.equal(stripHtml('<a title="a>b">text</a>'), "text");
  assert.equal(stripHtml("<img alt='x>y'>caption"), "caption");
});

test("comments are dropped whole, including a `>` inside them", () => {
  assert.equal(stripHtml("A<!-- a > b -->B"), "A B");
  assert.equal(stripHtml("<!DOCTYPE html><p>hello</p>"), "hello");
});

test("a bare `<` in prose stays prose, and an unterminated tag is left as text", () => {
  assert.equal(stripHtml("3 < 4 and 5 > 4"), "3 < 4 and 5 > 4");
  assert.equal(stripHtml('text<div class="x"'), 'text<div class="x"');
});

// --- Entity decoding: alert 57, js/double-escaping --------------------------

test("an escaped entity decodes exactly once", () => {
  // The alert, in one line: `&amp;lt;` is the ESCAPING of the text "&lt;", so
  // it must decode to "&lt;" and stop — not go on to "<".
  assert.equal(stripHtml("&amp;lt;"), "&lt;");
  assert.equal(stripHtml("&amp;amp;"), "&amp;");
  assert.equal(stripHtml("&amp;gt;"), "&gt;");
  // Numerically escaped ampersand, same property.
  assert.equal(stripHtml("&#38;lt;"), "&lt;");
  assert.equal(stripHtml("&#x26;lt;"), "&lt;");
});

test("plain entities still decode, in either case", () => {
  assert.equal(stripHtml("Tom &amp; Jerry"), "Tom & Jerry");
  assert.equal(stripHtml("&lt;p&gt;"), "<p>");
  assert.equal(stripHtml("&AMP; &LT; &GT; &QUOT; &#39; &apos;"), "& < > \" ' '");
  assert.equal(stripHtml("a&nbsp;b"), "a b");
  assert.equal(stripHtml("&#8217;&#x2014;"), "’—");
});

test("a bare ampersand and an unknown reference are left alone", () => {
  assert.equal(stripHtml("R&D budget"), "R&D budget");
  assert.equal(stripHtml("&notareal; &#0; &#x110000;"), "&notareal; &#0; &#x110000;");
});

// --- Both defects through the real entry point ------------------------------

const HTML_EML = [
  "From: Careers <careers@example.test>",
  "Subject: Your application",
  'Content-Type: text/html; charset="utf-8"',
  "",
  "<html><body><script >window.leaked = 1;</script >",
  "<p>Filed under R&amp;amp;D. The token &amp;lt;script&amp;gt; is literal text.</p>",
  "</body></html>",
].join("\n");

test("parseMailFile hands the classifier text, not script source or forged markup", () => {
  const { messages } = parseMailFile("mail.eml", HTML_EML);
  assert.equal(messages.length, 1);
  const { body } = messages[0];

  // The script element's contents never reach the classifier.
  assert.ok(!body.includes("window.leaked"), `script source leaked: ${body}`);

  // Escaped text arrives as the text it was, decoded once.
  assert.ok(body.includes("R&amp;D"), `double-unescaped: ${body}`);
  assert.ok(body.includes("&lt;script&gt;"), `double-unescaped: ${body}`);
  assert.ok(!body.includes("<script>"), `entity turned into markup: ${body}`);
});

// --- The neighbouring decoder's replacement order ---------------------------

/**
 * Characterisation, not a regression: `decodeQuotedPrintable` also applies two
 * replacements before its main loop (soft line breaks, then `_` → space for
 * headers), so the survey had to answer whether either re-reads the other's
 * output the way the entity chain did. It does not — an ENCODED underscore
 * (`=5F`) is still hex at that point and only becomes `_` in the byte loop,
 * after the `_` → space pass has gone by. These pin that order down so the
 * answer stays executable instead of argued. They pass before and after the
 * stripHtml fix.
 */
const QP_EML = [
  "From: =?utf-8?Q?Ren=C3=A9_Bl=C3=A5?= <rene@example.test>",
  "Subject: =?utf-8?Q?a=5Fb_c?=",
  "Content-Type: text/plain",
  "Content-Transfer-Encoding: quoted-printable",
  "",
  "Hello =",
  "world =E2=80=94 done",
].join("\n");

test("quoted-printable decoding keeps an encoded underscore out of the space pass", () => {
  const { messages } = parseMailFile("qp.eml", QP_EML);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].subject, "a_b c");
  assert.equal(messages[0].senderName, "Ren\u00e9 Bl\u00e5");
  assert.equal(messages[0].body, "Hello world \u2014 done");
});

// --- The /import fixture must parse identically ------------------------------

/** The sample mbox as the page ships it — no `${}` or backticks in the literal. */
const SAMPLE_MBOX = readSource("components/import/ImportMail.tsx").match(
  /const SAMPLE_MBOX = `([\s\S]*?)`;/,
)[1];

test("the sample.mbox fixture parses exactly as recorded", () => {
  const result = parseMailFile("sample.mbox", SAMPLE_MBOX);
  assert.equal(result.format, "mbox");
  assert.equal(result.totalFound, 4);
  assert.equal(result.truncated, false);
  assert.deepEqual(result.messages, [
    {
      id: "m0",
      subject: "We received your application",
      senderName: "Cedar Labs Recruiting",
      senderEmail: "no-reply@greenhouse.io",
      body: "Thank you for applying to the Software Engineer role at Cedar Labs. Your application has been received and our team is reviewing it.",
      snippet:
        "Thank you for applying to the Software Engineer role at Cedar Labs. Your application has been received and our team is reviewing it.",
      receivedAt: "Thu, 16 Jul 2026 09:00:00 +0000",
    },
    {
      id: "m1",
      subject: "Let's schedule your technical interview",
      senderName: "Juniper Cloud",
      senderEmail: "recruiting@junipercloud.io",
      body: "We'd like to schedule a 45-minute technical interview next week. Please use the Calendly link to book a time to meet the hiring team.",
      snippet:
        "We'd like to schedule a 45-minute technical interview next week. Please use the Calendly link to book a time to meet the hiring team.",
      receivedAt: "Thu, 16 Jul 2026 10:00:00 +0000",
    },
    {
      id: "m2",
      subject: "Update on your application to Atlas Freight",
      senderName: "Atlas Freight Careers",
      senderEmail: "careers@atlasfreight.com",
      body: "After careful consideration we have decided to move forward with other candidates at this time. We wish you the best in your search.",
      snippet:
        "After careful consideration we have decided to move forward with other candidates at this time. We wish you the best in your search.",
      receivedAt: "Thu, 16 Jul 2026 11:00:00 +0000",
    },
    {
      id: "m3",
      subject: "Quick question about your background",
      senderName: "Maya Chen",
      senderEmail: "maya@earlystage.xyz",
      body: "Hi, I had a quick question about your background and some recent projects. Do you have a few minutes this week?",
      snippet:
        "Hi, I had a quick question about your background and some recent projects. Do you have a few minutes this week?",
      receivedAt: "Thu, 16 Jul 2026 12:00:00 +0000",
    },
  ]);
});
