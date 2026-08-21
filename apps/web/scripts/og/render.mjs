/**
 * Redraws `public/og.png`, the one image every share of Applied carries.
 *
 *   pnpm og            regenerate the card
 *   pnpm og --check    render to a temp file and fail if it differs from the
 *                      committed bytes
 *
 * WHY A SCRIPT AT ALL. The card it replaces was committed as 173KB of PNG with
 * no source anywhere in the repo, so the only way to change a word in it was
 * to open an image editor, and the only way to review a change to it was to
 * look at two pictures. It drifted, predictably: it went on describing the
 * System Card, in a serif the product does not use, under a byline the footer
 * dropped on 2026-08-19, for as long as nobody opened it. A card with a source
 * file diffs like code and its words come from the file every other landing
 * string comes from.
 *
 * WHY PLAYWRIGHT AND NOT `next/og`. An `opengraph-image.tsx` route would
 * render through Satori, which supports a subset of CSS and would constrain
 * the composition; it would also add a route to an app whose every route is
 * already dynamic (`layout.tsx` reads `headers()` for the CSP nonce). The card
 * changes when the copy changes, which is rarely, so a build-time artifact is
 * the honest shape. Chromium is already a dev dependency for the e2e suite.
 *
 * THE FONT ASSERTION IS THE POINT OF THE SCRIPT'S SECOND HALF. A `@font-face`
 * that fails to load produces a card set in the system UI face that looks
 * very nearly right, and would ship. `document.fonts.check()` alone is not
 * enough: it answers about the font's own load state, not about what the
 * element resolved to. So the check below MEASURES, twice, and demands the
 * two differ. That is a positive control on the assertion itself.
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

import { CARD, FONT_FAMILY, cardHtml } from "./card.mjs";
import { OG } from "../../components/marketing/copy.ts";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const fontPath = join(webRoot, "app/fonts/atkinson-hyperlegible-next-latin-wght.woff2");
const outPath = join(webRoot, "public/og.png");
const cardPath = join(webRoot, "scripts/og/card.mjs");
const lockPath = join(webRoot, "scripts/og/og.lock.json");
const check = process.argv.includes("--check");

if (!existsSync(fontPath)) {
  fail(`the card's typeface is not at ${fontPath}. It is Atkinson Hyperlegible Next, the
product's own voice; a card set in anything else is not the product's card.`);
}
const fontDataUri = `data:font/woff2;base64,${readFileSync(fontPath).toString("base64")}`;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: CARD.width, height: CARD.height },
  deviceScaleFactor: 1,
});
await page.setContent(cardHtml(OG, fontDataUri), { waitUntil: "load" });
await page.evaluate(() => document.fonts.ready);

/**
 * Did the headline actually get drawn in Atkinson?
 *
 * Render the same string twice at the same size, once through the card's
 * font stack and once through a stack that deliberately cannot resolve to it,
 * and compare advance widths. Identical widths mean the first measurement was
 * also the fallback, i.e. the @font-face silently did nothing.
 */
const fontState = await page.evaluate(
  ([family, sample]) => {
    const measure = (stack) => {
      const el = document.createElement("span");
      el.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:400 68px ${stack}`;
      el.textContent = sample;
      document.body.appendChild(el);
      const w = el.getBoundingClientRect().width;
      el.remove();
      return w;
    };
    return {
      loaded: document.fonts.check(`400 68px "${family}"`),
      withFace: measure(`"${family}", monospace`),
      withoutFace: measure("monospace"),
      resolved: getComputedStyle(document.querySelector(".line")).fontFamily,
    };
  },
  [FONT_FAMILY, OG.line],
);

if (!fontState.loaded || fontState.withFace === fontState.withoutFace) {
  await browser.close();
  fail(`the card fell back to a system typeface and would have shipped looking almost right.
  document.fonts.check  ${fontState.loaded}
  width with the face   ${fontState.withFace}
  width without it      ${fontState.withoutFace}   (equal widths mean the face never applied)
  resolved font-family  ${fontState.resolved}`);
}

const png = await page.screenshot({ type: "png" });
await browser.close();

// A PNG's IHDR carries the true pixel dimensions; a wrong deviceScaleFactor
// silently doubles them and every crawler then downscales the card.
const width = png.readUInt32BE(16);
const height = png.readUInt32BE(20);
if (width !== CARD.width || height !== CARD.height) {
  fail(`rendered ${width}x${height}, but a link preview card is ${CARD.width}x${CARD.height}`);
}

if (check) {
  const committed = existsSync(outPath) ? readFileSync(outPath) : Buffer.alloc(0);
  if (!committed.equals(png)) {
    fail(`public/og.png is stale: it does not match what scripts/og/card.mjs and the OG block
of components/marketing/copy.ts currently describe. Run \`pnpm og\` and commit the result.`);
  }
  console.log(`og.png is current (${width}x${height}, ${committed.length} bytes)`);
} else {
  writeFileSync(outPath, png);
  writeFileSync(lockPath, `${JSON.stringify(lockFor(png), null, 2)}\n`);
  console.log(`wrote public/og.png  ${width}x${height}  ${png.length} bytes`);
  console.log(`  line  ${OG.line}`);
  console.log(`  foot  ${OG.foot}`);
}

/**
 * The fingerprint `tests/unit/og-card.test.mjs` holds the card to.
 *
 * The `--check` path above is the exact one, but it costs a Chromium launch,
 * so it belongs in a developer's hands rather than in a unit suite that runs
 * on every commit. The lock is the cheap half of the same question: it
 * fingerprints the card's INPUTS, so editing a word in copy.ts or a rule in
 * card.mjs without re-rendering is caught by a test that needs no browser.
 *
 * WHAT IT CANNOT DO, said plainly rather than assumed: it cannot prove the
 * committed PNG was produced by these inputs, only that the inputs have not
 * moved since something last wrote the lock. Writing the lock and the PNG in
 * the same statement is what ties them together, and `--check` is what proves
 * it. A gate whose limits are not written down becomes a gate people trust
 * past its evidence.
 */
function lockFor(bytes) {
  return {
    inputs: sha(JSON.stringify(OG) + readFileSync(cardPath, "utf8")),
    png: sha(bytes),
    width,
    height,
    bytes: bytes.length,
  };
}

function sha(input) {
  return createHash("sha256").update(input).digest("hex");
}

function fail(message) {
  console.error(`\nog card: ${message}\n`);
  process.exit(1);
}
