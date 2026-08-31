/**
 * Unit tests for the mail row's preview + "open in Gmail" link, and for both
 * mail views actually using them.
 *
 * The complaint these exist for, verbatim: "there is no option to look at the
 * mail in the inbox live scan, so how can i classify when i don't even know
 * the contect or don't have the link to look at it!"
 *
 * That was exactly true. A live-scan row rendered subject, sender, a category
 * chip, a confidence meter and a correction control — and nothing of the
 * message itself. The FILED tab, one click away, had shown a snippet and an
 * external link since it was written, so the product already knew how; the
 * scan view read a different endpoint (`GET /gmail/inbox`) whose response
 * model carried neither field. Both are now on that wire, and both views draw
 * them from ONE component rather than a second copy of the same markup —
 * three copies of the status vocabulary is how this repo shipped a 422.
 *
 * The absent cases are the point as much as the present ones. A message Gmail
 * returned no snippet for must draw no line, and a row with no resolvable link
 * must offer no control: a dead "open" button is worse than no button, because
 * it costs a click to discover it does nothing.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { importTsx, markup, readSource, stubModule } from "./helpers/renderTsx.mjs";

// `MailPreview` now draws its mail-supplied strings through `MailText` (#424),
// and `renderTsx` rewrites only the ENTRY module — so a nested `.tsx` import is
// one Node cannot load. This routes the REAL component through the stub
// registry: same file, same transpiler, same React, nothing stood in for. See
// `mail-rows-neutralise-hostile-text.test.mjs` for why the helper cannot do it.
const { MailText } = await importTsx("components/mail/MailText.tsx");
const { MailSnippet, OpenInGmail } = await importTsx("components/mail/MailPreview.tsx", {
  stubs: { "@/components/mail/MailText": stubModule({ MailText }) },
});

/** A real snippet, as Gmail hands one over (already entity-decoded server-side). */
const SNIPPET =
  "Dear Ayush, Thank you for your interest in potential opportunities with " +
  "Jump Trading. Your details have been added to our database and…";

const GMAIL_LINK = "https://mail.google.com/mail/?authuser=owner%40example.test#all/t1";

// --- The preview ------------------------------------------------------------

test("a row with a snippet renders it", () => {
  const html = markup(MailSnippet({ snippet: SNIPPET }));
  assert.match(html, /Jump Trading/);
  assert.match(html, /Your details have been added to our database/);
});

test("the preview is clamped to one line — this is a list people triage", () => {
  const html = markup(MailSnippet({ snippet: SNIPPET }));
  assert.match(html, /line-clamp-1/);
});

test("a row with no snippet renders nothing at all — never a blank line", () => {
  // null (the wire's "no preview"), undefined (a verdict from an older
  // session snapshot, which predates the field) and "" must all draw nothing.
  for (const empty of [null, undefined, ""]) {
    assert.equal(markup(MailSnippet({ snippet: empty })), "");
  }
});

// --- The link ---------------------------------------------------------------

test("a row with a gmail_link exposes a link to it", () => {
  const html = markup(OpenInGmail({ href: GMAIL_LINK, subject: "Your application" }));
  assert.match(html, /<a /);
  assert.match(html, /href="https:\/\/mail\.google\.com\/mail\/\?authuser=owner%40example\.test#all\/t1"/);
});

test("the link opens externally, safely, and says which message it opens", () => {
  const html = markup(OpenInGmail({ href: GMAIL_LINK, subject: "Your application" }));
  assert.match(html, /target="_blank"/);
  // Without noopener the opened tab gets a handle on this one.
  assert.match(html, /rel="noopener noreferrer"/);
  // A column of identical "open" links is unusable by screen reader; the
  // subject is the only thing that tells one row from the next.
  assert.match(html, /aria-label="Open “Your application” in Gmail"/);
});

test("a row with a null gmail_link renders no dead control", () => {
  for (const empty of [null, undefined, ""]) {
    assert.equal(markup(OpenInGmail({ href: empty, subject: "Your application" })), "");
  }
});

// --- Both views are wired to it ---------------------------------------------
//
// Rendering the rows themselves is out of reach here: both modules import
// `next/link` and `next/navigation`, which do not resolve under plain Node.
// So the wiring is asserted against the source — weaker than a render, but it
// is the difference between "the component works" and "the component is
// actually used", and without it every test above could pass while the scan
// row still showed the reader nothing. The Playwright suite covers the
// rendered page.

test("the live-scan row draws both, from the verdict's own fields", () => {
  const src = readSource("components/gmail/InboxWorkbench.tsx");
  assert.match(src, /from "@\/components\/mail\/MailPreview"/);
  assert.match(src, /<MailSnippet snippet=\{v\.snippet\}/);
  assert.match(src, /<OpenInGmail href=\{v\.gmail_link\}/);
});

test("the filed row draws both from the SAME component, not a copy", () => {
  const src = readSource("components/mail/FiledMailList.tsx");
  assert.match(src, /from "@\/components\/mail\/MailPreview"/);
  assert.match(src, /<MailSnippet snippet=\{m\.snippet\}/);
  assert.match(src, /<OpenInGmail href=\{m\.gmail_link\}/);
  // The markup it used to hold inline must be GONE, or the two views can drift
  // apart again exactly as they did the first time.
  assert.doesNotMatch(src, /line-clamp-1/);
  assert.doesNotMatch(src, /aria-label=\{`Open/);
});

// --- The session snapshot ----------------------------------------------------

test("the verdict snapshot key was bumped past the pre-snippet shape", () => {
  const src = readSource("components/gmail/InboxWorkbench.tsx");
  // Verdicts are cached in sessionStorage for 15 minutes and rehydrated
  // verbatim on remount. Left at v1, a reader who was mid-session when this
  // deployed would keep being served rows with no preview and no link — the
  // bug this change exists to fix — with every gate green, because nothing on
  // the server can see a sessionStorage entry.
  assert.match(src, /applied:inbox:snapshot:v2/);
  assert.doesNotMatch(src, /applied:inbox:snapshot:v1/);
});

// --- The demo twin -----------------------------------------------------------

test("the demo mine carries both fields, including a row missing them", async () => {
  const { demoScanMine } = await import("../../lib/demo/scanMine.ts");
  const mine = demoScanMine(Date.parse("2026-08-11T12:00:00Z"));

  // A twin that cannot show the new fields makes any e2e run against it
  // worthless — it would pass whether or not the real view renders them.
  assert.ok(mine.some((v) => typeof v.snippet === "string" && v.snippet.length > 0));
  // Pinned to the ORIGIN, not a substring anywhere in the URL: "contains
  // mail.google.com" is satisfied by https://evil.test/?x=mail.google.com,
  // which is why CodeQL treats that shape as a real defect wherever it appears.
  assert.ok(
    mine.some(
      (v) => typeof v.gmail_link === "string" && v.gmail_link.startsWith("https://mail.google.com/"),
    ),
  );
  // …and one row with neither, so the absent branches are exercised too.
  assert.ok(mine.some((v) => v.snippet === null && v.gmail_link === null));
});
