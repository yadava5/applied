/**
 * The closing act PLAYS — once, slowed, while the pin holds the page — and
 * this file is the contract for that tempo AND for the timeline it plays.
 *
 * TWO LINEAGES, MERGED DELIBERATELY (2026-08-19). The scroll-scrubbed act
 * shipped a gate that derived its playhead map (`ACT_BEATS` / `ACT_STOPS`)
 * from globals.css; the owner then rejected the scrub itself — the close
 * should play, not be operated — and the pin-and-play rebuild shipped a gate
 * for the clock. The beats map retired WITH the scrub: a piecewise map
 * existed to spend scroll runway on events, and a real-time clock spends
 * time exactly as the CSS authors it, so there are no beat constants left to
 * hold. What did NOT retire is everything the scrub gate protected that the
 * play still relies on:
 *
 *   · `ACT_SECONDS` must be the timeline's own end — derived here as the
 *     largest delay + duration over every animation `.act--play` starts,
 *     resolving each `var(--d)` to the component's own `at("…s")` value.
 *     Retime the CSS without moving the constant and the clock clips the
 *     tail of every play; this fails on drift in either direction.
 *   · THE SCRUB MIRROR STILL RUNS THE PLAY. The clock positions the frozen
 *     sequence through `.act--scrub`'s `calc(delay - var(--act-t))` delays —
 *     a second copy of every `.act--play` delay by construction, because a
 *     paused animation can only be positioned through its delay. The zip
 *     below fails on any mismatch, and on any animated class missing from
 *     the pause list (it would run on its own clock mid-play).
 *
 * The ending has failed twice, in opposite directions, and each failure is a
 * bound here:
 *
 *   · fired-and-forgotten in an unpinned 596px band, the fixed timeline
 *     outran its runway — fragments for a fast reader, already-finished for
 *     a slow one. The guard against that coming back is the GEOMETRY: the
 *     band pins through a real runway and sits last on the page with only
 *     the footer beyond it, so the scene cannot leave the viewport while the
 *     clock runs. Both halves (the pin CSS, the page order) are asserted.
 *   · scrubbed off the scroll, it demanded the reader operate the ending by
 *     hand, and the owner rejected it. The guard against THAT coming back is
 *     the clock itself: `--act-t` is written from elapsed time at AUTO_RATE,
 *     clamped to the sequence's length, and no scroll listener drives it.
 *
 * WHY A SOURCE SCAN. Same boundary as landing-variants.test.mjs: a CSS
 * timeline and a TS constant meet nowhere this harness can render, and the
 * failure that actually happens is one number moving in one file. Comments
 * are stripped first on both sides — the docblocks around these values quote
 * the very numbers under test.
 *
 * MUTATION-TESTED AT THE MERGE (2026-08-19): the hint's play delay in
 * globals.css 1.55s → 1.7s went red twice (scrub mirror AND ACT_SECONDS),
 * AUTO_RATE 0.55 → 1.2 went red, each restored byte-identical and the file
 * ran green. Companion bounds not independently reddened, and named as
 * such: the pause-list membership, the ≥ 7 strokes floor, the threshold and
 * wall-time bands.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Comments out, code only. */
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

const act = code(readFileSync(join(webRoot, "components", "marketing", "ClosingAct.tsx"), "utf8"));
const css = code(readFileSync(join(webRoot, "app", "globals.css"), "utf8"));
const page = code(readFileSync(join(webRoot, "app", "landing-b", "page.tsx"), "utf8"));

const num = (name) => {
  const m = new RegExp(`const ${name}\\s*=\\s*([\\d.]+)`).exec(act);
  assert.ok(m, `${name} is gone from ClosingAct — the tempo contract has no number to hold`);
  return Number(m[1]);
};

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
      `.${cls}: scrub delays ${JSON.stringify(mirrored)} != play delays — the clock and the CSS now play different sequences`,
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

test("ACT_SECONDS is the timeline's own end, not a stale copy", () => {
  const total = ms(num("ACT_SECONDS"));
  const runs = resolveTimeline();
  const timelineEnd = Math.max(...runs.map((r) => r.delay + r.duration));
  assert.equal(
    total,
    timelineEnd,
    `ACT_SECONDS (${total}ms) must be the timeline's end — the largest delay + duration .act--play starts (${timelineEnd}ms). The clock will stop early or run past the last animation.`,
  );
});

test("the play is slowed, and by a watchable amount", () => {
  const rate = num("AUTO_RATE");
  // Slower than authored — that is the owner's whole instruction — but not
  // slow-motion: the authored choreography reads as narration down to about
  // 0.4x and as a screensaver below it.
  assert.ok(rate < 1, `AUTO_RATE (${rate}) is not a slowdown`);
  assert.ok(rate >= 0.4, `AUTO_RATE (${rate}) is slow motion, not narration`);
  const wall = num("ACT_SECONDS") / rate;
  assert.ok(
    wall > 2.5 && wall < 6,
    `the slowed play takes ${wall.toFixed(2)}s — outside the 2.5–6s band a pinned reader will actually watch`,
  );
});

test("the clock is elapsed time, clamped, and no scroll listener drives it", () => {
  // The playhead walks min(ACT_SECONDS, elapsed · AUTO_RATE): the clamp is
  // what holds the composed end frame instead of running the delays past
  // every animation's tail.
  assert.match(
    act,
    /Math\.min\(ACT_SECONDS,/,
    "the clock no longer clamps at ACT_SECONDS — the playhead runs off the end of the sequence",
  );
  assert.ok(act.includes("requestAnimationFrame"), "the clock lost its frame loop");
  assert.ok(
    act.includes('setProperty("--act-t"'),
    "the clock no longer writes --act-t — nothing positions the frozen animations",
  );
  // The scroll-driven playhead is retired: the ending plays, it is not
  // operated. A scroll subscription here means someone rebuilt the rejected
  // mechanism.
  assert.ok(
    !act.includes("trackProgress") && !/addEventListener\(\s*["']scroll/.test(act),
    "ClosingAct reads the scroll again — the owner rejected the scrubbed ending; the play owns its own clock",
  );
});

test("the trigger waits for the scene, and only for the scene", () => {
  const threshold = num("PLAY_THRESHOLD");
  assert.ok(
    threshold >= 0.15 && threshold <= 0.6,
    `PLAY_THRESHOLD (${threshold}) is outside [0.15, 0.6] — too low burns the opening under the fold, too high can leave a parked reader waiting forever`,
  );
  // The observer watches the SCENE's box. Observing the band would make the
  // ratio meaningless once the runway grows it to a screen and a half.
  assert.ok(
    act.includes("io.observe(scene)"),
    "the play trigger no longer watches the scene's own box",
  );
  assert.match(
    act,
    /intersectionRatio >= PLAY_THRESHOLD/,
    "the trigger stopped comparing against PLAY_THRESHOLD",
  );
});

test("the pin and the page order make the enter-only trigger safe", () => {
  // Half one: the band still grows a runway and pins its stage through it.
  // This is what was measured missing when the ending was "too fast to see"
  // — without the pin, a fixed timeline in a short band IS the old defect.
  assert.match(css, /\.act--runway\s*\{[^}]*--closing-runway:\s*1000px/, "the sub-lg runway is gone");
  assert.match(
    css,
    /\.act--runway \.act__stage\s*\{[^}]*position:\s*sticky/,
    "the stage no longer pins — the play can be scrolled off screen mid-run",
  );
  assert.match(
    css,
    /height:\s*calc\(100vh \+ var\(--closing-runway\)\)/,
    "the band's height is no longer viewport + runway",
  );
  // Half two: the band is the page's last section, footer excepted — the
  // geometry that guarantees the scene is still on screen at max scroll.
  assert.match(
    page,
    /<ClosingAct \/>\s*<MarketingFooter \/>/,
    "ClosingAct is no longer immediately before the footer — the cannot-escape-the-viewport argument no longer holds",
  );
  // And the component only grows the runway for a band still below the fold,
  // so no-JS, reduced-motion and an on-screen band never strand anyone in
  // empty scroll.
  assert.ok(
    act.includes("getBoundingClientRect().top < window.innerHeight"),
    "the below-the-fold guard is gone — a composed band on screen at load can be yanked apart",
  );
});

test("reduced motion, the server and no-JS all get the composed frame", () => {
  assert.match(
    act,
    /useState<"static" \| "auto">\("static"\)/,
    "the SSR default is no longer the composed static frame",
  );
  assert.ok(
    act.includes('matchMedia("(prefers-reduced-motion: reduce)")'),
    "the reduced-motion guard is gone from ClosingAct",
  );
  // The frozen-animation machinery the clock positions: paused, delays
  // shifted by --act-t. Without these the clock writes a variable nothing
  // reads.
  assert.ok(
    css.includes("calc(var(--d, 0s) - var(--act-t, 0s))"),
    "the delay-shift arithmetic is gone — --act-t no longer positions the sequence",
  );
});
