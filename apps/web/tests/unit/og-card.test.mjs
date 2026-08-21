/**
 * THE LINK PREVIEW CARD, held to the words it is supposed to be drawn from.
 *
 * `public/og.png` is the one image every share of Applied carries, and until
 * 2026-08-21 it was the cover of the System Card: a serif italic tagline the
 * product does not use anywhere, a volume number, and a byline the site
 * footer had already dropped on 2026-08-19. Its `alt` text in
 * `app/layout.tsx` described that picture in detail. Nobody noticed, for the
 * ordinary reason that nobody opens a PNG during a copy sweep.
 *
 * THIS IS THE FOURTH TIME THE SAME SHAPE HAS BITTEN, and the shape is the
 * point: text that reaches a reader from outside the landing's module set.
 * A filmed component, where the words were inside a video. `app/layout.tsx`,
 * which Next composes and no import walk reaches. `BetaBanner.HIDE_ON`, a
 * plain string list no import graph can see. Now an image, which no scan in
 * any language can read.
 *
 * The defence is not a smarter scan. It is that the card's words are drawn
 * FROM `components/marketing/copy.ts` and nowhere else, which puts them back
 * under the two gates in `landing-voice.test.mjs`, and that this file catches
 * the one drift that arrangement still allows: changing a word without
 * re-rendering the picture.
 *
 * WHAT THIS FILE DOES NOT PROVE. It cannot read the PNG's pixels, so it
 * cannot prove the committed image was rendered from these inputs. It proves
 * the inputs have not moved since the lock was written, and `pnpm og` writes
 * the lock and the PNG in the same statement. `pnpm og --check` re-renders
 * and compares bytes, which IS the exact proof, and it costs a Chromium
 * launch. Run that when the card changes; this runs on every commit.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { OG } from "../../components/marketing/copy.ts";
import { CARD, cardHtml } from "../../scripts/og/card.mjs";

const webRoot = join(import.meta.dirname, "..", "..");
const read = (p) => readFileSync(join(webRoot, p));
const sha = (input) => createHash("sha256").update(input).digest("hex");

const lock = JSON.parse(read("scripts/og/og.lock.json").toString("utf8"));
const png = read("public/og.png");

test("the committed card is the card the current copy describes", () => {
  const inputs = sha(JSON.stringify(OG) + read("scripts/og/card.mjs").toString("utf8"));
  assert.equal(
    inputs,
    lock.inputs,
    "the words in copy.ts's OG block, or the composition in scripts/og/card.mjs, have changed since public/og.png was last drawn. Every share of the site is still carrying the old picture. Run `pnpm og` from apps/web and commit both the PNG and the lock.",
  );
  assert.equal(
    sha(png),
    lock.png,
    "public/og.png does not match the lock, so it was edited or replaced by something other than `pnpm og`. Re-render it from source.",
  );
});

/**
 * A positive control on the fingerprint above, which is otherwise two hashes
 * agreeing with each other and would agree just as happily about an empty
 * file. This reads the PNG's own header, which is the only claim in this file
 * derived from the image rather than from a record about it.
 */
test("the card is a real 1200x630 PNG", () => {
  assert.equal(
    png.subarray(0, 8).toString("hex"),
    "89504e470d0a1a0a",
    "public/og.png is not a PNG",
  );
  assert.equal(png.readUInt32BE(16), CARD.width, "the card is the wrong width for a link preview");
  assert.equal(
    png.readUInt32BE(20),
    CARD.height,
    "the card is the wrong height for a link preview",
  );
  // Crawlers fetch this on every unfurl and several cap what they will read.
  assert.ok(
    png.length < 500_000,
    `the card is ${png.length} bytes; keep a link preview well under 500KB`,
  );
});

/**
 * THE ASSERTION THE WHOLE ARRANGEMENT RESTS ON: the card draws the copy and
 * nothing else.
 *
 * `card.mjs` is a pure function returning a string, so this does not need a
 * browser and does not need to read pixels. Render it with sentinels in place
 * of the real strings, strip the CSS, the mark and the tags, and whatever
 * text is left over is text somebody typed into the composition. That text
 * would be shipped to every reader of every share while sitting outside both
 * copy gates, which is the exact failure this file exists to prevent. The
 * previous card carried "VOL. 01 · SYSTEM CARD" and a byline that way.
 *
 * This is the test that makes the "no prose in card.mjs" rule mechanical
 * rather than a comment asking politely.
 */
test("the card draws the copy and nothing else", () => {
  const sentinels = { wordmark: "WORDMARKZZ", line: "LINEZZ", foot: "FOOTZZ" };
  const drawn = cardHtml(sentinels, "data:,");

  const text = drawn
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<svg[\s\S]*?<\/svg>/gi, "")
    .replace(/<!doctype[^>]*>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const leftover = Object.values(sentinels).reduce((s, v) => s.split(v).join(" "), text).trim();
  assert.equal(
    leftover,
    "",
    `scripts/og/card.mjs draws text that did not come from copy.ts: "${leftover}". Every word in the link preview has to arrive as an argument, because no gate in this repo can read a PNG and prose typed into the render script is prose nobody will ever scan.`,
  );

  // ...and the sentinels really were drawn, so an empty leftover is evidence
  // rather than the result of a template that renders nothing at all.
  const used = Object.values(sentinels).filter((v) => text.includes(v));
  assert.ok(
    used.length >= 2,
    `the card drew ${used.length} of the copy strings. A composition may drop one for balance, but a card drawing fewer than two is not drawing the copy.`,
  );
});

/**
 * The vocabulary that made the old card read as coursework rather than a
 * product, held against the strings themselves. `alt` is in scope: it is the
 * card as a screen-reader user receives it, and it is where the System Card's
 * cover description survived every sweep.
 *
 * THE PUNCTUATION IS FOLDED AWAY BEFORE MATCHING, and that is not tidiness:
 * the first version of this test listed "system card" and the string it was
 * written to catch said "system-card cover". Restoring the exact alt that
 * shipped for weeks left this assertion green. Only the fingerprint test
 * caught the mutation, and the fingerprint would have gone green again the
 * moment somebody re-rendered. So every separator collapses to a space and
 * the phrases are matched against a normalised surface.
 */
test("nothing in the link preview presents Applied as a project", () => {
  const PROJECT_WORDS = [
    "system card",
    "vol",
    "volume",
    "ayush",
    "yadav",
    "portfolio",
    "case study",
    "side project",
  ];
  const surface = ` ${Object.values(OG)
    .join(" ")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()} `;
  const found = PROJECT_WORDS.filter((w) => surface.includes(` ${w} `));
  assert.deepEqual(
    found,
    [],
    `the link preview presents Applied as a project rather than a product: ${found.join(", ")}. The image a stranger meets before the click is the product's, and the maker's byline came off the site on 2026-08-19.`,
  );
});
