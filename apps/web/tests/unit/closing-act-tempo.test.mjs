/**
 * The closing act's playhead map agrees with the timeline it maps — measured
 * from the sources, never restated.
 *
 * WHAT THE CONTRACT IS. `ClosingAct` scrubs a CSS-authored sequence by
 * writing `--act-t`, and its map is three numbers that MEAN events in
 * globals.css: `ACT_BEATS[1]` is the rules rail's completed draw (its `--d`
 * plus its draw duration), `ACT_BEATS[2]` is the last stroke's completed draw
 * (max `--d` over the drawn strokes plus each one's duration), and
 * `ACT_SECONDS` is the whole timeline's end (max delay + duration over every
 * animation `.act--play` starts). Those correspondences used to be
 * transcription — `[0, 0.3, 0.9]` typed next to a comment promising "if a
 * delay or duration in globals.css moves, the boundaries here move with it" —
 * which is exactly the promise nothing kept. This test recomputes all three
 * from `globals.css` plus the component's own `at("…s")` delays and fails on
 * drift in either direction: retime the CSS and the constants go stale;
 * retype the constants and they stop matching the CSS.
 *
 * IT ALSO HOLDS THE SCRUB MIRROR. `.act--scrub` restates every `.act--play`
 * delay inside a `calc(delay - var(--act-t))` — a second copy by construction,
 * because a paused animation can only be positioned through its delay. A delay
 * retimed in the play block but not the scrub block ships two different
 * sequences, one for the click and one for the scroll; this test zips the two
 * blocks per class and fails on any mismatch, and it checks every play-block
 * class is in the scrub's `animation-play-state: paused` list — an animated
 * element missing there would run on its own clock mid-scrub.
 *
 * WHY A SOURCE SCAN. Same boundary as landing-variants.test.mjs: a CSS
 * timeline and a TS constant meet nowhere this harness can render, and the
 * failure that actually happens is one number moving in one file. Comments
 * are stripped first on both sides — the docblocks around these values quote
 * the very numbers under test.
 *
 * MUTATION-TESTED AT INTRODUCTION (2026-08-19). Each watched go red, then
 * green again on a byte-identical restore (shasum-verified):
 *   · globals.css alone: the hint's play delay 1.55s → 1.7s (ACT_SECONDS
 *     stale AND the scrub mirror broken — two failures, as it should be);
 *   · ClosingAct.tsx alone: ACT_BEATS 0.9 → 0.8 (drawing-end stale);
 *   · globals.css alone: the draw duration 0.4s → 0.45s (both beats' spans
 *     move; drawing-end stale).
 * Companion bounds NOT independently reddened, and named as such: the
 * strictly-increasing checks on beats and stops, the pause-list membership,
 * and the ≥ 7 strokes floor.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const css = readFileSync(join(webRoot, "app", "globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);
const act = readFileSync(join(webRoot, "components", "marketing", "ClosingAct.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/(^|[^:])\/\/[^\n]*/g, "$1");

/** Milliseconds, so 0.02 + 0.3 has one representation on both sides. */
const ms = (seconds) => Math.round(seconds * 1000);

/** Split on top-level commas only — `cubic-bezier(0.45, 0, 0.3, 1)` is one token. */
function splitTop(value) {
  const parts = [];
  let depth = 0;
  let cur = "";
  for (const ch of value) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      parts.push(cur);
      cur = "";
    } else cur += ch;
  }
  parts.push(cur);
  return parts.map((p) => p.trim()).filter(Boolean);
}

/**
 * One `animation:` shorthand entry → { duration, delay } in ms, where a
 * `var(--d, …)` delay is the sentinel "--d" (the element supplies it).
 * In the shorthand the first <time> is the duration and the second the delay;
 * easing keywords and cubic-bezier() carry no `s`-suffixed numbers.
 */
function parseAnimation(entry) {
  const perElement = /var\(\s*--d\b[^)]*\)/.test(entry);
  const times = [...entry.replace(/var\([^)]*\)/g, " ").matchAll(/(?<![\w.])(\d*\.?\d+)s(?![\w])/g)].map(
    (m) => ms(Number(m[1])),
  );
  assert.ok(times.length >= 1, `no duration in animation entry: ${entry}`);
  return { duration: times[0], delay: perElement ? "--d" : (times[1] ?? 0) };
}

/** `.act--play .act__X { animation: …; }` → class → [{ duration, delay }] */
function readPlayBlock() {
  const map = new Map();
  for (const m of css.matchAll(/\.act--play\s+\.(act__[a-z]+)\s*\{\s*animation:([^;]+);/g)) {
    map.set(m[1], splitTop(m[2]).map(parseAnimation));
  }
  return map;
}

/** `.act--scrub …` `animation-delay:` rules → class → [delay] (ms or "--d"). */
function readScrubDelays() {
  const map = new Map();
  for (const m of css.matchAll(/((?:\.act--scrub[^{]*?)+)\{\s*animation-delay:([^;]+);/g)) {
    const classes = [...m[1].matchAll(/\.act--scrub\s+\.(act__[a-z]+)/g)].map((c) => c[1]);
    const delays = splitTop(m[2]).map((calc) => {
      const c = /calc\(\s*(var\(\s*--d\b[^)]*\)|\d*\.?\d+s)\s*-\s*var\(\s*--act-t\b/.exec(calc);
      assert.ok(c, `unparsed scrub delay: ${calc}`);
      return c[1].startsWith("var") ? "--d" : ms(parseFloat(c[1]));
    });
    for (const cls of classes) map.set(cls, delays);
  }
  return map;
}

/** The classes `.act--scrub` pauses. */
function readPausedClasses() {
  const m = /((?:\.act--scrub[^{]*?)+)\{\s*animation-play-state:\s*paused/.exec(css);
  assert.ok(m, "the scrub's pause rule is gone — nothing freezes the sequence");
  return new Set([...m[1].matchAll(/\.(act__[a-z]+)/g)].map((c) => c[1]));
}

/** The component's per-element delays: [{ classes, delay }] from `at("…s")`. */
function readElementDelays() {
  return [...act.matchAll(/className="([^"]*)"\s+style=\{at\("(\d*\.?\d+)s"\)\}/g)].map((m) => ({
    classes: m[1].split(/\s+/),
    delay: ms(Number(m[2])),
  }));
}

function readConst(name) {
  const m = new RegExp(`const ${name}\\s*=\\s*(\\[[^\\]]*\\]|[\\d.]+)`).exec(act);
  assert.ok(m, `${name} is gone from ClosingAct.tsx`);
  return m[1].startsWith("[")
    ? m[1]
        .slice(1, -1)
        .split(",")
        .map((s) => Number(s))
        .filter((n) => !Number.isNaN(n))
    : Number(m[1]);
}

const play = readPlayBlock();
const elements = readElementDelays();

test("the play block and the component still describe a scene this gate can read", () => {
  // Guards against the gate going green by parsing nothing: the classes the
  // assertions below index must all still exist under these names.
  for (const cls of ["act__draw", "act__rail", "act__pop", "act__hint", "act__ask"]) {
    assert.ok(play.has(cls), `.act--play .${cls} has no animation — renamed or removed?`);
  }
  const strokes = elements.filter((e) => e.classes.includes("act__draw"));
  assert.ok(strokes.length >= 7, `only ${strokes.length} drawn strokes found — the wordmark is gone`);
  assert.ok(
    elements.some((e) => e.classes.includes("act__rail")),
    "the rules rail carries no at() delay",
  );
});

test("every .act--play delay is mirrored, verbatim, by the .act--scrub block", () => {
  const scrub = readScrubDelays();
  const paused = readPausedClasses();
  for (const [cls, animations] of play) {
    assert.ok(paused.has(cls), `.${cls} animates in .act--play but .act--scrub never pauses it`);
    const mirrored = scrub.get(cls);
    assert.ok(mirrored, `.${cls} animates in .act--play but .act--scrub gives it no delay`);
    assert.deepEqual(
      mirrored,
      animations.map((a) => a.delay),
      `.${cls}: scrub delays ${JSON.stringify(mirrored)} != play delays — the click and the scroll now play different sequences`,
    );
  }
});

/**
 * Resolve every animation `.act--play` starts to its real (delay, duration),
 * substituting each element's `at()` value where the CSS says `var(--d)`.
 * Precedence follows the cascade: `.act__rail` and `.act__pop` rules come
 * after `.act__draw`'s at equal specificity, so an element carrying both
 * classes runs the later rule's animations.
 */
function resolveTimeline() {
  const runs = [];
  for (const el of elements) {
    const cls = ["act__rail", "act__pop", "act__draw"].find((c) => el.classes.includes(c));
    assert.ok(cls, `an at() delay on ${el.classes.join(" ")} feeds no animated class`);
    for (const a of play.get(cls)) {
      runs.push({ cls, delay: a.delay === "--d" ? el.delay : a.delay, duration: a.duration });
    }
  }
  for (const [cls, animations] of play) {
    for (const a of animations) {
      if (a.delay === "--d") continue; // covered per element above
      runs.push({ cls, delay: a.delay, duration: a.duration });
    }
  }
  return runs;
}

test("ACT_BEATS and ACT_SECONDS are the timeline's own numbers, not stale copies", () => {
  const beats = readConst("ACT_BEATS").map(ms);
  const stops = readConst("ACT_STOPS");
  const total = ms(readConst("ACT_SECONDS"));
  const runs = resolveTimeline();

  const railDraw = runs.find((r) => r.cls === "act__rail");
  const drawingEnds = runs
    .filter((r) => r.cls === "act__draw" || r === railDraw)
    .map((r) => r.delay + r.duration);
  const timelineEnd = Math.max(...runs.map((r) => r.delay + r.duration));

  assert.equal(beats.length, 3, "ACT_BEATS is no longer three beats — rederive this gate with the map");
  assert.equal(beats[0], 0, "the map must start at t = 0");
  assert.equal(
    beats[1],
    railDraw.delay + railDraw.duration,
    "ACT_BEATS[1] must be the rules rail's completed draw (its --d + its draw duration)",
  );
  assert.equal(
    beats[2],
    Math.max(...drawingEnds),
    "ACT_BEATS[2] must be the last stroke's completed draw",
  );
  assert.equal(
    total,
    timelineEnd,
    "ACT_SECONDS must be the timeline's end — the largest delay + duration .act--play starts",
  );

  // The map's own coherence: beats climb toward the end, and each beat has a
  // runway share to spend, in order, strictly inside [0, 1).
  for (let i = 1; i < beats.length; i += 1) assert.ok(beats[i] > beats[i - 1], "beats must climb");
  assert.ok(beats[beats.length - 1] < total, "the last beat must precede the sequence's end");
  assert.equal(stops.length, beats.length, "every beat needs a runway stop");
  assert.equal(stops[0], 0, "the runway starts at 0");
  for (let i = 1; i < stops.length; i += 1) assert.ok(stops[i] > stops[i - 1], "stops must climb");
  assert.ok(stops[stops.length - 1] < 1, "the last span needs runway to spend");
});
