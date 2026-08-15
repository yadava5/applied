/**
 * The capture-instrument bake-off, kept so nobody has to re-derive it.
 *
 *   node scripts/footage/instrument.mjs            # needs a server on :3437
 *   FOOTAGE_BASE=http://127.0.0.1:3437 node scripts/footage/instrument.mjs
 *
 * Two findings decided how `capture.mjs` is built, and neither is in any
 * documentation:
 *
 *   A. Playwright's emulated `deviceScaleFactor` does NOT reach a CDP
 *      screencast. Frames come back at the CSS viewport size — 1440x900 —
 *      however large `maxWidth` is set. Launching Chromium with
 *      `--force-device-scale-factor=2` gives the compositor a real 2x surface
 *      and the same screencast returns 2880x1800.
 *
 *   B. A `page.screenshot()` loop is the alternative. It honours
 *      `deviceScaleFactor` and manages ~30 fps on a clipped region (~8 fps on a
 *      full viewport), which is enough — but it SAMPLES: it decides when to
 *      look. The screencast emits a frame when the compositor paints one and
 *      stamps it, so the real timing survives into the edit.
 *
 * If a future Playwright or Chromium changes either answer, this is the script
 * that says so.
 */
import { chromium } from "@playwright/test";

const BASE = process.env.FOOTAGE_BASE ?? "http://localhost:3437";
const PATH_ = process.env.FOOTAGE_PROBE_PATH ?? "/demo";

/** PNG IHDR: width at byte 16, height at 20. */
const pngSize = (b64) => {
  const buf = Buffer.from(b64, "base64");
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
};

async function screencastSize(launchOpts, label) {
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(BASE + PATH_, { waitUntil: "domcontentloaded" });
  const client = await ctx.newCDPSession(page);
  const size = await new Promise((resolve) => {
    client.on("Page.screencastFrame", async ({ data, sessionId }) => {
      resolve(pngSize(data));
      try { await client.send("Page.screencastFrameAck", { sessionId }); } catch { /* stopped */ }
    });
    client.send("Page.startScreencast", { format: "png", everyNthFrame: 1, maxWidth: 6000, maxHeight: 6000 });
  });
  console.log(`A. screencast [${label}] -> ${size.join("x")} (CSS viewport is 1440x900)`);
  await browser.close();
}

if (!(await fetch(BASE + PATH_).catch(() => null))?.ok) {
  console.error(`No server answering at ${BASE}${PATH_}.`);
  process.exit(1);
}

await screencastSize({}, "emulated deviceScaleFactor: 2");
await screencastSize({ args: ["--force-device-scale-factor=2"] }, "--force-device-scale-factor=2");

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  reducedMotion: "no-preference",
});
const page = await ctx.newPage();
await page.goto(BASE + PATH_, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);

for (const clip of [undefined, { x: 350, y: 0, width: 720, height: 460 }]) {
  const N = 40;
  const t0 = Date.now();
  let first;
  for (let i = 0; i < N; i++) {
    const buf = await page.screenshot({ clip, animations: "allow", caret: "hide", type: "png" });
    if (i === 0) first = `${buf.readUInt32BE(16)}x${buf.readUInt32BE(20)}`;
  }
  const ms = Date.now() - t0;
  console.log(
    `B. screenshot loop ${clip ? "clipped 720x460" : "full viewport"}: ${first} px · ` +
      `${(ms / N).toFixed(1)} ms/frame = ${((1000 * N) / ms).toFixed(1)} fps`,
  );
}
await browser.close();
