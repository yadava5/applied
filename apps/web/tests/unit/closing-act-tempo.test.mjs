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
 *   · THE COMPLETED RUNS OF THE STAGGERED ANIMATIONS — restored 2026-08-19,
 *     because the bullet above is a `max()` and a maximum guards exactly ONE
 *     animation. Every non-maximal duration and every per-element delay sat
 *     unguarded under it, which is precisely the coverage the scrub gate's
 *     `ACT_BEATS` carried and this file lost when the map retired with the
 *     scrub. Demonstrated, not suspected: `.act--play .act__draw` retimed
 *     0.4s → 1.5s finishes the wordmark at 2.0s, so the verdict seats and
 *     the ask rises mid-draw — and the whole file stayed green.
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
 * MUTATION-TESTED AGAIN WHEN THE COMPLETED RUNS WENT BACK IN (2026-08-19),
 * every mutation in globals.css and never in this file: `act-draw` 0.4s →
 * 1.5s red, 0.4s → 0.45s red (the scrub gate's own documented mutation, the
 * one that proved the loss), the rail's `act-draw` 0.3s → 0.35s red, the
 * dot's play delay 0.8s → 0.9s red on the mirror, and `.act__ask` 1.3s →
 * 0.2s moved CONSISTENTLY in both the play and scrub blocks — which passes
 * the mirror by construction — red on the reading order. And once in
 * ClosingAct.tsx, as the positive control that the left-hand side of the
 * beats really is derived from the component: the last stroke's at("0.5s")
 * → at("0.6s") reported 1000ms, not 900ms. Restored byte-identical (sha256
 * compared) and green after each.
 *
 * What that control does NOT reach: `completedRun` is max(delay) + duration,
 * so only the LAST element of each staggered class is pinned. A middle
 * stroke moving (at("0.2s") → at("0.25s")) changes nothing here — the same
 * shape of hole as the max() above, one level down, and left open
 * deliberately: the stagger ladder is a drawing decision with no second
 * copy to check it against either.
 *
 * STILL UNGUARDED, and said plainly rather than left to be discovered: the
 * durations of the fixed-delay animations (guide, ghosts, tag, travel,
 * envelope, dot, ripple, ask). `.act__ripple` 0.55s → 0.3s passes. They have
 * no second copy anywhere — `.act--scrub` overrides delay only, because the
 * durations ARE the play block's declarations, inherited — so guarding them
 * means transcribing a full timeline table, and the bound that matters (the
 * order events happen in) is asserted directly below instead.
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
const page = code(readFileSync(join(webRoot, "app", "page.tsx"), "utf8"));

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

/**
 * A block-element class name.
 *
 * BOTH WORKED EXAMPLES BELOW ARE NOW HISTORICAL, and they are kept as
 * historical rather than swapped for live ones, because the shapes are what
 * the pattern defends against and no surviving class has either shape. The
 * closing act lost its legend and its ghost rails on 2026-08-21, taking
 * `.act__key-mark` and `.act__tag--rules` with them; every remaining `act__`
 * class is a single unhyphenated word. A future rule that grows one of these
 * shapes is exactly the case this pattern exists for.
 *
 * Hyphenated names were part of the vocabulary (`.act__key-mark`), so a bare
 * `act__[a-z]+` would silently skip any rule that grew one — the gate would
 * parse nothing and say nothing. The trailing group is `-[a-z]+` and not
 * `[a-z-]+` on purpose: `.act__tag--rules` was a MODIFIER of `.act__tag` and
 * had to still resolve to `act__tag`, which is the class the animations are
 * written against.
 */
const CLS = "act__[a-z]+(?:-[a-z]+)*";

/** `.act--play .act__X { animation: …; }` → class → [{ duration, delay }] */
function readPlayBlock() {
  const map = new Map();
  for (const m of css.matchAll(new RegExp(`\\.act--play\\s+\\.(${CLS})\\s*\\{\\s*animation:([^;]+);`, "g"))) {
    map.set(m[1], splitTop(m[2]).map(parseAnimation));
  }
  return map;
}

/** `.act--scrub …` `animation-delay:` rules → class → [delay] (ms or "--d").
 *
 *  The selector list is matched as one `[^{}]*` run rather than a repeated
 *  group. `((?:\.act--scrub[^{]*?)+)` — what this was — is ambiguous: every
 *  extra `.act--scrub` in the list can be attributed to the repetition or
 *  swallowed by a neighbouring `[^{]*?`, so a non-matching tail makes the
 *  engine try every split. CodeQL flagged it (js/redos, two alerts) and it is
 *  not theoretical: 24 repetitions took 1,248ms against 0ms for this form.
 *
 *  Only our own stylesheet is ever fed to it, so nothing was exploitable —
 *  the fix is here because a superlinear parser in a gate is a gate that can
 *  time out instead of failing honestly. `[^{}]` is also strictly tighter
 *  than `[^{]`: it cannot run past a closing brace into the next rule. */
function readScrubDelays() {
  const map = new Map();
  for (const m of css.matchAll(/(\.act--scrub[^{}]*)\{\s*animation-delay:([^;]+);/g)) {
    const classes = [...m[1].matchAll(new RegExp(`\\.act--scrub\\s+\\.(${CLS})`, "g"))].map((c) => c[1]);
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
  const m = /(\.act--scrub[^{}]*)\{\s*animation-play-state:\s*paused/.exec(css);
  assert.ok(m, "the scrub's pause rule is gone — nothing freezes the sequence");
  return new Set([...m[1].matchAll(new RegExp(`\\.(${CLS})`, "g"))].map((c) => c[1]));
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
 * The cascade order, READ from the stylesheet instead of declared here. Every
 * `.act--play .act__X` rule sits at the same specificity, so for an element
 * carrying two animated classes (`class="act__draw act__rail"`) the LAST rule
 * in source order wins outright — a second `animation:` shorthand replaces
 * the first, it does not merge with it. `readPlayBlock`'s Map is in source
 * order, so the winner is the first hit walking it backwards. This was the
 * literal ["act__rail", "act__pop", "act__draw"]; the two agree today, and
 * the reason to read it is that reordering the CSS moves the answer with it
 * rather than leaving this gate resolving the old cascade.
 */
const CASCADE = [...play.keys()].reverse();

/** The class whose `.act--play` rule actually runs on an `at()` element. */
function cascadeWinner(el) {
  const cls = CASCADE.find((c) => el.classes.includes(c));
  assert.ok(cls, `an at() delay on ${el.classes.join(" ")} feeds no animated class`);
  return cls;
}

/**
 * Resolve every animation `.act--play` starts to its real (delay, duration),
 * substituting each element's `at()` value where the CSS says `var(--d)`.
 */
function resolveTimeline() {
  const runs = [];
  for (const el of elements) {
    const cls = cascadeWinner(el);
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

/** The one `var(--d)` animation of `.act--play .cls` — the staggered one. */
function staggeredRun(cls) {
  const perElement = (play.get(cls) ?? []).filter((a) => a.delay === "--d");
  assert.equal(perElement.length, 1, `.${cls} no longer has exactly one var(--d) animation`);
  return perElement[0];
}

/** The one fixed-delay animation of `.act--play .cls`, in ms. */
function blockRun(cls) {
  const fixed = (play.get(cls) ?? []).filter((a) => a.delay !== "--d");
  assert.equal(fixed.length, 1, `.${cls} no longer has exactly one fixed-delay animation`);
  return fixed[0];
}

/** When the LAST element the cascade hands `cls` finishes its run, in ms. */
function completedRun(cls) {
  const mine = elements.filter((el) => cascadeWinner(el) === cls);
  assert.ok(mine.length, `no at() element resolves to .${cls} — its stagger is gone`);
  return Math.max(...mine.map((el) => el.delay)) + staggeredRun(cls).duration;
}

/**
 * THE COMPLETED RUNS — the beats `ACT_SECONDS` structurally cannot see.
 *
 * The scrub gate held these in `ACT_BEATS`: [1] was the rail's drawn state
 * and [2] the wordmark's. The map retired with the scrub (a piecewise scroll
 * map has nothing left to describe once a clock spends the time), but these
 * two beats were never ABOUT the scroll — they are when two things in the
 * drawing are finished, and the pin-and-play rewrite left them unguarded
 * under a `max()`. The i-dot's pop is here too: never in the beats map, and
 * unguarded in exactly the same way, for one more line of the same loop.
 *
 * Derived on the left — the component's `at()` × the stylesheet's duration,
 * resolved through the cascade, never transcribed. Declared on the right,
 * because with the beats map gone there is no second copy in the source to
 * compare against, and a value that appears once cannot disagree with
 * itself. A deliberate retime updates the right-hand side and says so in a
 * commit body; an accidental one lands here, which is the whole point.
 */
const COMPLETED_RUNS = {
  act__rail: 320, // the rules rail is drawn — the scrub gate's ACT_BEATS[1]
  act__pop: 720, // the i-dot has landed on its stem
  act__draw: 900, // the wordmark is fully drawn — the scrub gate's ACT_BEATS[2]
};

test("each staggered animation still completes on its own beat, not merely under ACT_SECONDS", () => {
  // Completeness first: a new `var(--d)` animation must be pinned here or it
  // inherits the same silence. This is the assertion that keeps the table
  // from quietly becoming a subset of the timeline.
  assert.deepEqual(
    [...play]
      .filter(([, animations]) => animations.some((a) => a.delay === "--d"))
      .map(([cls]) => cls)
      .sort(),
    Object.keys(COMPLETED_RUNS).sort(),
    "the play block's staggered (var(--d)) animations are no longer the ones this table pins — one is unguarded, or a pinned one is gone",
  );
  for (const [cls, expected] of Object.entries(COMPLETED_RUNS)) {
    assert.equal(
      completedRun(cls),
      expected,
      `.${cls} finishes at ${completedRun(cls)}ms, not ${expected}ms — its duration or its last element's at() delay moved. ACT_SECONDS is a max() and will not notice; the composition will.`,
    );
  }
  // And state what ACT_SECONDS only implies: the hint IS the timeline's last
  // event. Without this the maximum could migrate to another animation on a
  // retime with the constant still "matching" — every beat under it having
  // moved.
  const runs = resolveTimeline();
  const end = Math.max(...runs.map((r) => r.delay + r.duration));
  assert.deepEqual(
    [...new Set(runs.filter((r) => r.delay + r.duration === end).map((r) => r.cls))],
    ["act__hint"],
    "the hint is no longer the play's last event — ACT_SECONDS is now some other animation's tail",
  );
});

test("the reading order the component calls load-bearing is still the order in time", () => {
  const wordmarkDrawn = completedRun("act__draw");
  const railDrawn = completedRun("act__rail");
  const ask = blockRun("act__ask");
  const dot = blockRun("act__dot");
  const envelope = blockRun("act__envelope");

  // Relations, not more pinned numbers: the beats above catch drift, these
  // catch INVERSION, and they survive any retime that keeps the sequence a
  // sequence. NOTE what the docblock actually claims — the ask rises
  // "alongside the dot's landing", which is containment inside the verdict's
  // fall, not a link in a chain. The chain reading (strokes → verdict seats →
  // ask) is not what the CSS does in either direction: the verdict starts
  // falling at 0.8s, before the wordmark is drawn at 0.9s, and the ask rises
  // at 1.3s, before the verdict has seated at 1.4s. The overlap is the
  // composition; only the two orderings below are load-bearing.
  assert.ok(
    dot.delay <= ask.delay && ask.delay <= dot.delay + dot.duration,
    `the ask rises at ${ask.delay}ms, outside the verdict's fall (${dot.delay}–${dot.delay + dot.duration}ms) — the component's "alongside the dot's landing" is no longer true`,
  );
  // The one M4 inverts: retime the draw long enough and the ask asks while
  // the product's name is still being written.
  assert.ok(
    wordmarkDrawn < ask.delay,
    `the wordmark is still drawing at ${wordmarkDrawn}ms when the ask rises at ${ask.delay}ms — the reader is asked before the sentence is finished`,
  );
  // The rail is the thing the envelope is consumed AT; it has to exist first.
  assert.ok(
    railDrawn < envelope.delay,
    `the rules rail is still drawing at ${railDrawn}ms when the envelope collapses at ${envelope.delay}ms`,
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
    /<ClosingAct[^>]*\/>\s*<MarketingFooter[^>]*\/>/,
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
