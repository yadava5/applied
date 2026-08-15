/**
 * Step 1 of the footage pipeline: record the real app.
 *
 * Instrument: CDP `Page.startScreencast` under `--force-device-scale-factor=2`.
 * That combination was chosen by measurement, not from documentation — rerun
 * `scripts/footage/instrument.mjs` to see the bake-off:
 *
 *   · Playwright's emulated `deviceScaleFactor` does NOT reach the screencast.
 *     Frames come back 1440x900 however large `maxWidth` is set. The launch
 *     flag gives the compositor a real 2x surface and the frames arrive
 *     2880x1800 — which is what a clip has to be to stay sharp once a 26rem
 *     card downscales it.
 *   · A `page.screenshot()` loop is the alternative and manages ~30 fps on a
 *     clipped region, but it SAMPLES — it decides when to look. The screencast
 *     emits a frame when the compositor paints one, and stamps it, so the real
 *     timing survives into Remotion instead of being reconstructed from a
 *     nominal frame rate.
 *
 * Nothing is drawn onto the page and no cursor is composited: a screencast
 * frame is the page surface and nothing else. Everything in these clips is the
 * product doing what it does.
 *
 * Output: `<out>/<scene>/NNNN.png` + `scene.json` (frame timestamps, derived
 * crop). Frames are intermediate build output and are not committed; the
 * committed artifacts are the encoded clips under `public/footage/`.
 */
import { chromium } from "@playwright/test";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { MAX_CROP_W, SCENES } from "./scenes.mjs";

const BASE = process.env.FOOTAGE_BASE ?? "http://localhost:3437";
const OUT = process.env.FOOTAGE_FRAMES ?? path.join(process.cwd(), ".footage-frames");
const ONLY = process.env.FOOTAGE_ONLY?.split(",").map((s) => s.trim()).filter(Boolean);

/** Settle time after navigation, before the first frame: fonts resolved, the
 *  demo's relative re-dating pass done (`lib/demo/redate.ts` runs on a
 *  `setTimeout(0)` after hydration), nothing still moving. */
const SETTLE = 2500;

/**
 * The gate that keeps a name out of frame. Every element whose text contains a
 * forbidden string is measured against the crop rectangle; overlap fails the
 * capture. Run AFTER the interaction, when the rows that appear have appeared —
 * checking before it would be a check that cannot fail.
 */
async function assertNothingForbidden(page, scene, crop) {
  if (!scene.forbid?.length) return;
  const hits = await page.evaluate(
    ({ words, crop }) => {
      const out = [];
      for (const el of document.querySelectorAll("body *")) {
        if (el.children.length) continue; // leaf text nodes only
        const text = el.textContent ?? "";
        const word = words.find((w) => text.includes(w));
        if (!word) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const overlaps =
          r.right > crop.x && r.left < crop.x + crop.width &&
          r.bottom > crop.y && r.top < crop.y + crop.height;
        if (overlaps) out.push({ word, rect: { x: r.x, y: r.y, w: r.width, h: r.height } });
      }
      return out;
    },
    { words: scene.forbid, crop },
  );
  if (hits.length) {
    throw new Error(
      `[${scene.id}] forbidden text inside the crop: ` +
        hits.map((h) => `${h.word} @ ${Math.round(h.rect.x)},${Math.round(h.rect.y)}`).join("; "),
    );
  }
}

async function captureScene(browser, scene) {
  const ctx = await browser.newContext({
    viewport: scene.viewport,
    // The launch flag supplies the real 2x surface; this keeps CSS layout at the
    // scene's own width so the page is the page, not a scaled-down one.
    deviceScaleFactor: 2,
    // Motion neutralises every animation PROP under reduced motion
    // (PipelineBoard.tsx), so a context that inherited `reduce` would record a
    // slideshow of end states and look, frame for frame, like a broken app.
    reducedMotion: "no-preference",
    // /demo's fixtures are dated relative to today; pinning the zone is what
    // stops the captured dates depending on where the render ran. Same
    // reasoning as `playwright.config.ts`'s UTC baseline project.
    timezoneId: "UTC",
    colorScheme: "dark",
  });
  const page = await ctx.newPage();
  await page.goto(BASE + scene.url, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(SETTLE);

  // Prove the instrument before trusting the recording.
  if (await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)) {
    throw new Error("prefers-reduced-motion is REDUCE — every animation would record at duration 0");
  }

  await scene.prepare?.(page);

  const raw = await scene.crop(page);
  const crop = { ...raw, width: Math.min(raw.width, MAX_CROP_W) };
  if (raw.width > MAX_CROP_W) {
    console.log(`  ${scene.id}: crop trimmed ${raw.width} -> ${MAX_CROP_W} CSS px (legibility ceiling)`);
  }

  const dir = path.join(OUT, scene.id);
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });

  const client = await ctx.newCDPSession(page);
  const frames = [];
  const writes = [];
  let n = 0;
  client.on("Page.screencastFrame", ({ data, sessionId, metadata }) => {
    const file = `${String(n++).padStart(4, "0")}.png`;
    frames.push({ file, t: metadata.timestamp });
    writes.push(writeFile(path.join(dir, file), Buffer.from(data, "base64")));
    client.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });

  await client.send("Page.startScreencast", { format: "png", everyNthFrame: 1, maxWidth: 4000, maxHeight: 4000 });
  // A beat of the resting state before anything happens — the clip's held
  // opening, and the poster frame.
  await page.waitForTimeout(700);
  await scene.run(page);
  await client.send("Page.stopScreencast");
  await Promise.all(writes);
  await client.detach();

  await assertNothingForbidden(page, scene, crop);

  const first = frames[0]?.t ?? 0;
  const meta = {
    id: scene.id,
    title: scene.title,
    url: scene.url,
    capturedAt: new Date().toISOString(),
    viewport: scene.viewport,
    scale: 2,
    crop,
    frames: frames.map((f) => ({ file: f.file, t: +(f.t - first).toFixed(4) })),
  };
  await writeFile(path.join(dir, "scene.json"), JSON.stringify(meta, null, 2));
  await ctx.close();

  const dur = meta.frames.at(-1)?.t ?? 0;
  const down = (crop.width / 416).toFixed(2);
  console.log(
    `  ${scene.id}: ${frames.length} frames / ${dur.toFixed(2)}s · crop ${crop.width}x${crop.height} CSS · ${down}x downscale in a 416px card`,
  );
  return meta;
}

if (!(await fetch(BASE + "/demo").catch(() => null))?.ok) {
  console.error(`No server answering at ${BASE}. Use scripts/footage/render.sh, which starts one.`);
  process.exit(1);
}

const browser = await chromium.launch({ args: ["--force-device-scale-factor=2", "--hide-scrollbars"] });
console.log(`capturing from ${BASE}`);
for (const scene of ONLY ? SCENES.filter((s) => ONLY.includes(s.id)) : SCENES) {
  await captureScene(browser, scene);
}
await browser.close();
console.log(`frames -> ${OUT}`);
