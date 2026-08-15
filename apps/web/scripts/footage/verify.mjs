/**
 * Step 3's gate: look at the SHIPPED files, at the size they will be shown.
 *
 * Not the captured frames and not the Remotion preview — the encoded clip, in a
 * 26rem box, which is the only thing a visitor ever sees. It answers what the
 * byte counts cannot: does the file decode in a browser, does the clip loop
 * without a seam, and does anything actually happen in it.
 *
 * THE INSTRUMENT MATTERS HERE, AND THE OBVIOUS ONE IS WRONG. Seeking a <video>
 * with `currentTime` and waiting for `seeked` — even through a `requestAnimationFrame`
 * — returns the PREVIOUS frame. It was checked against `board-syncs`, whose
 * counters visibly change, and reported all eight sample points identical.
 * Frames therefore come out of ffmpeg, which decodes deterministically. A
 * browser is still used, for the one question only a browser can answer (does
 * this file play), and to compare still images, where there is no seeking to get
 * wrong.
 *
 * `verify-negative.mjs` proves both gates fire. Run it after touching either.
 */
import { chromium } from "@playwright/test";
import { RenderInternals } from "@remotion/renderer";
import { createReadStream } from "node:fs";
import { createServer } from "node:http";
import { mkdir, readFile, rm } from "node:fs/promises";
import path from "node:path";

import { CLIPS } from "./clips.mjs";
import { changedPct, MOVED_MIN_PCT, SEAM_MAX_PCT } from "./metrics.mjs";

const WEB = process.cwd();
const FRAMES = process.env.FOOTAGE_FRAMES ?? path.join(WEB, ".footage-frames");
const OUT = path.join(FRAMES, "verify");
const DIR = path.join(WEB, "public", "footage");

/** The width the artifact column gives a clip (`minmax(0,26rem)`). */
const CARD = 416;
const SAMPLES = 8;

export const ff = (args) =>
  RenderInternals.callFf({ bin: "ffmpeg", args, indent: false, logLevel: "error", binariesDirectory: null });

export async function probe(file) {
  const { stdout } = await RenderInternals.callFf({
    bin: "ffprobe",
    args: ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file],
    indent: false, logLevel: "error", binariesDirectory: null,
  });
  return parseFloat(stdout.trim());
}

/** `SAMPLES` frames spread across a clip, as base64 PNGs. */
export async function sample(clip, dir) {
  const duration = await probe(clip);
  await mkdir(dir, { recursive: true });
  const shots = [];
  for (let i = 0; i < SAMPLES; i++) {
    const t = +((duration - 0.05) * (i / (SAMPLES - 1))).toFixed(3);
    const f = path.join(dir, `${String(i).padStart(2, "0")}.png`);
    await ff(["-y", "-ss", String(t), "-i", clip, "-frames:v", "1", f]);
    shots.push({ t, b64: (await readFile(f)).toString("base64") });
  }
  return { duration, shots };
}

/** The two measurements, on one clip's samples. Shared with the negative
 *  control so both run the same code. */
export async function judge(page, shots) {
  return {
    // The frame the clip ends on, against the frame it restarts from.
    seam: await changedPct(page, shots[0].b64, shots.at(-1).b64),
    // The opening beat against the closing beat, before the loop dissolve.
    moved: await changedPct(page, shots[0].b64, shots[SAMPLES - 2].b64),
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  // Served over HTTP for the decode check, because that is how the page will
  // fetch them.
  const server = createServer((req, res) => {
    res.writeHead(200, { "content-type": req.url.endsWith(".webm") ? "video/webm" : "video/mp4" });
    createReadStream(path.join(DIR, path.basename(decodeURIComponent(req.url)))).pipe(res);
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const origin = `http://127.0.0.1:${server.address().port}`;

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: CARD + 110, height: 1200 }, deviceScaleFactor: 2 });

  let failed = 0;
  for (const id of CLIPS) {
    // 1. does a browser decode it? Both encodes, since the page ships both.
    for (const ext of ["webm", "mp4"]) {
      await page.setContent(`<video id="v" muted src="${origin}/${id}.${ext}"></video>`);
      const ok = await page.evaluate(
        () => new Promise((res) => {
          const v = document.getElementById("v");
          if (v.readyState >= 1) return res(true);
          v.onloadedmetadata = () => res(true);
          v.onerror = () => res(false);
          setTimeout(() => res(false), 15000);
        }),
      );
      if (!ok) {
        console.error(`  ${id}.${ext}: the browser could not decode this file`);
        failed++;
      }
    }

    const { duration, shots } = await sample(path.join(DIR, `${id}.webm`), path.join(OUT, id));
    const { seam, moved } = await judge(page, shots);
    const seamOk = seam <= SEAM_MAX_PCT;
    const movedOk = moved >= MOVED_MIN_PCT;
    if (!seamOk || !movedOk) failed++;
    console.log(
      `  ${id}: ${duration.toFixed(2)}s · loop seam ${seam.toFixed(3)}% ${seamOk ? "ok" : "!! VISIBLE SEAM"}` +
        ` · ${moved.toFixed(2)}% of the frame changes ${movedOk ? "ok" : "!! NOTHING MOVES"}`,
    );

    // The contact sheet is the point of this script as much as the gates are:
    // the numbers cannot tell you whether the clip is any good, and it is shown
    // at the real 416px so legibility is judged where it matters.
    await page.setContent(
      `<style>body{margin:0;background:#0f1011;font:10px ui-monospace,monospace;color:#8a8}
       .r{display:flex;gap:8px;padding:5px;align-items:center}img{width:${CARD}px;display:block}</style>` +
        shots.map((s) => `<div class="r"><div style="width:46px">${s.t}s</div><img src="data:image/png;base64,${s.b64}"></div>`).join(""),
    );
    await page.waitForTimeout(350);
    await page.screenshot({ path: path.join(OUT, `${id}.png`), fullPage: true });
  }

  await browser.close();
  server.close();
  console.log(`contact sheets -> ${OUT}`);
  if (failed) {
    console.error(`${failed} check(s) failed.`);
    process.exit(1);
  }
}
