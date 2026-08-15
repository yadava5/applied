/**
 * The negative control for `verify.mjs`.
 *
 * `verify.mjs` passed on all three clips the first time it ran, which on its own
 * is evidence of nothing. This builds two deliberately broken clips out of a
 * real one and asserts each gate goes red on the defect it exists for:
 *
 *   · SEAM      — the same clip with its loop dissolve chopped off, so the last
 *                 frame no longer matches the first.
 *   · NO MOTION — a single frame given a duration, which is what a clip becomes
 *                 when the capture records a page that never moved. A context
 *                 that inherited `prefers-reduced-motion: reduce` produces
 *                 exactly this, and it is the failure most likely to ship
 *                 unnoticed because every other number still looks healthy.
 *
 * IT HAS ALREADY EARNED ITS PLACE. On its first run the seam gate came back
 * GREEN on a clip whose dissolve had been cut off: the metric was a mean over
 * the whole frame, and what differs between the opening and closing states of
 * `board-syncs` is a handful of digits, which averages away to 1.77 against a
 * tolerance of 3. Both gates now count the SHARE of the frame that moved, and
 * both live in `metrics.mjs` — imported here rather than reimplemented, because
 * a control that exercises its own copy of the arithmetic can pass while the
 * real gate is broken.
 */
import { chromium } from "@playwright/test";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";

import { MOVED_MIN_PCT, SEAM_MAX_PCT } from "./metrics.mjs";
import { ff, judge, sample } from "./verify.mjs";

const WEB = process.cwd();
const DIR = path.join(WEB, "public", "footage");
const TMP = path.join(process.env.FOOTAGE_FRAMES ?? path.join(WEB, ".footage-frames"), "negative");
/** Any shipped clip works; this one is the hardest case for the seam gate,
 *  because so little of its frame changes. */
const SUBJECT = process.env.FOOTAGE_NEGATIVE_SUBJECT ?? "board-syncs";

await rm(TMP, { recursive: true, force: true });
await mkdir(TMP, { recursive: true });

const source = path.join(DIR, `${SUBJECT}.webm`);
const { duration: full } = await sample(source, path.join(TMP, "src"));

// DEFECT 1 — the loop dissolve, removed. `-t` is an output option; this ffmpeg
// build has nearly every filter compiled out, so everything here is done with
// demuxer and muxer options only.
const seamClip = path.join(TMP, "seam.webm");
await ff(["-y", "-i", source, "-t", (full - 0.8).toFixed(3), "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", seamClip]);

// DEFECT 2 — one frame, held. `-loop 1` is an input option on the image demuxer.
const still = path.join(TMP, "still.png");
await ff(["-y", "-ss", "0", "-i", source, "-frames:v", "1", still]);
const stillClip = path.join(TMP, "still.webm");
await ff(["-y", "-loop", "1", "-i", still, "-t", "4", "-r", "30", "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", "-pix_fmt", "yuv420p", stillClip]);

const browser = await chromium.launch();
const page = await browser.newPage();

const broken = await judge(page, (await sample(seamClip, path.join(TMP, "seam"))).shots);
const frozen = await judge(page, (await sample(stillClip, path.join(TMP, "still"))).shots);
// The healthy clip, measured alongside, so the contrast is on the same screen
// as the defects rather than in another run's scrollback.
const healthy = await judge(page, (await sample(source, path.join(TMP, "healthy"))).shots);

await browser.close();

const checks = [
  {
    gate: "SEAM",
    what: `${SUBJECT} with its loop dissolve cut off`,
    value: `${broken.seam.toFixed(3)}%`,
    threshold: `must exceed ${SEAM_MAX_PCT}%`,
    red: broken.seam > SEAM_MAX_PCT,
  },
  {
    gate: "NO MOTION",
    what: `a single frame of ${SUBJECT}, held for 4s`,
    value: `${frozen.moved.toFixed(3)}%`,
    threshold: `must fall below ${MOVED_MIN_PCT}%`,
    red: frozen.moved < MOVED_MIN_PCT,
  },
];

console.log(`  reference · healthy ${SUBJECT}: seam ${healthy.seam.toFixed(3)}% · motion ${healthy.moved.toFixed(2)}%`);
let bad = 0;
for (const c of checks) {
  console.log(
    `  ${c.gate.padEnd(10)} ${c.red ? "RED (correct)     " : "GREEN — DECORATION"} ${c.value.padStart(8)} · ${c.threshold} · ${c.what}`,
  );
  if (!c.red) bad++;
}
if (bad) {
  console.error(`\n${bad} gate(s) did not fire on the defect they exist to catch. They are not checking anything.`);
  process.exit(1);
}
console.log("\nboth gates fire on the defect they exist for.");
