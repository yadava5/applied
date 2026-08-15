/**
 * The Triage boot engine (`lib/boot/triage.ts`) — the render the post-auth
 * overlay plays. ~560 lines of deterministic simulation that shipped with no
 * executable coverage at all; this file is that coverage.
 *
 * WHAT IS TESTED, AND HOW. The module exports exactly one thing —
 * `createTriageBoot()` — so everything here goes through the returned
 * interface (`resize / setReduced / resolve / step / render / done /
 * exitProgress`). `lerp`, `easeInOut`, `markNodes` and friends are private and
 * are deliberately NOT reached for: they are the implementation, not the
 * behaviour. The engine's only output is the sequence of 2D-context calls it
 * makes, so `recordingContext()` below is a canvas stand-in that records each
 * painted path in WORLD coordinates (it tracks translate/scale itself). Every
 * assertion is phrased against that paint log: where the stations sit, whether
 * an envelope reached one, which shelf a verdict landed on.
 *
 * WHAT IS DELIBERATELY NOT ASSERTED. Nothing here pins a colour to a CSS
 * variable, an exact station coordinate, or an easing curve — those are design
 * choices a refactor may move. `getComputedStyle` is stubbed to return "" so
 * the engine falls back to its own `FALLBACK` palette: hue assertions then read
 * as stable literals and the tests do not depend on globals.css.
 *
 * WHERE THE OTHER BOOT TIMINGS LIVE. The 400 ms exit and the 200 ms
 * reduced-motion crossfade are this module's (the divisor in `step`), and are
 * tested here. MIN_VISIBLE (1500/700 ms) and MAX_HOLD (8 s) are NOT in this
 * file — they are private to `components/boot/BootOverlay.tsx`, and their
 * observable behaviour (when the cover clears) is gated in
 * `tests/e2e/boot.spec.ts` against a real browser.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

// The engine reads the palette off the document at construction and the theme
// off <html> while drawing. Both stubs must exist BEFORE createTriageBoot runs.
// Returning "" from every custom property is the point: it drives the module's
// FALLBACK palette, so the hues below are fixed literals rather than whatever
// globals.css happens to say today.
globalThis.document = { documentElement: { dataset: {} } };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });

const { createTriageBoot } = await import("../../lib/boot/triage.ts");

/** The engine's own fallback palette (lib/boot/triage.ts `FALLBACK`). */
const HUE = {
  rules: "#38bdf8",
  emb: "#a78bfa",
  setfit: "#34d399",
  amber: "#f59e0b",
};

const W = 1000;
const H = 800;
const FRAME = 1 / 60;

/* -------------------------------------------------------------------------
 * The recording canvas.
 * ---------------------------------------------------------------------- */

const STYLE_KEYS = [
  "globalAlpha",
  "strokeStyle",
  "fillStyle",
  "lineWidth",
  "lineCap",
  "shadowColor",
  "shadowBlur",
];

/**
 * A CanvasRenderingContext2D stand-in that records every painted path.
 *
 * It keeps its own transform stack, so each record carries the shape's WORLD
 * position — which is what the assertions want ("did an envelope reach the
 * third station?") rather than the local coordinates the drawing code uses.
 * `tx`/`ty` are kept on the record too, because they separate the two kinds of
 * dot the scene paints: the engine draws verdict dots and shelf dots in the
 * root transform, and an envelope's own dot inside a translate.
 */
function recordingContext() {
  const ops = [];
  const stack = [];
  let m = { tx: 0, ty: 0, sx: 1, sy: 1 };
  let pending = null;

  const emit = (paint) => {
    if (!pending) return;
    const base = {
      op: `${paint}:${pending.kind}`,
      alpha: ctx.globalAlpha,
      style: paint === "fill" ? ctx.fillStyle : ctx.strokeStyle,
      tx: m.tx,
      ty: m.ty,
    };
    if (pending.kind === "arc") {
      ops.push({ ...base, x: m.tx + pending.x * m.sx, y: m.ty + pending.y * m.sy, r: pending.r * m.sx });
    } else if (pending.kind === "rect") {
      ops.push({
        ...base,
        x: m.tx + (pending.x + pending.w / 2) * m.sx,
        y: m.ty + (pending.y + pending.h / 2) * m.sy,
        w: pending.w * m.sx,
        h: pending.h * m.sy,
        cr: pending.cr,
      });
    } else {
      ops.push(base);
    }
  };

  const ctx = {
    globalAlpha: 1,
    strokeStyle: "",
    fillStyle: "",
    lineWidth: 1,
    lineCap: "butt",
    shadowColor: "",
    shadowBlur: 0,
    ops,
    save() {
      const s = { ...m };
      for (const k of STYLE_KEYS) s[k] = ctx[k];
      stack.push(s);
    },
    restore() {
      const s = stack.pop();
      if (!s) return;
      m = { tx: s.tx, ty: s.ty, sx: s.sx, sy: s.sy };
      for (const k of STYLE_KEYS) ctx[k] = s[k];
    },
    translate(x, y) {
      m.tx += x * m.sx;
      m.ty += y * m.sy;
    },
    scale(x, y) {
      m.sx *= x;
      m.sy *= y;
    },
    clearRect() {
      ops.push({ op: "clear" });
    },
    beginPath() {
      pending = null;
    },
    roundRect(x, y, w, h, r) {
      pending = { kind: "rect", x, y, w, h, cr: r };
    },
    rect(x, y, w, h) {
      pending = { kind: "rect", x, y, w, h, cr: 0 };
    },
    arc(x, y, r) {
      pending = { kind: "arc", x, y, r };
    },
    moveTo() {
      pending = { kind: "line" };
    },
    lineTo() {},
    stroke() {
      emit("stroke");
    },
    fill() {
      emit("fill");
    },
  };
  return ctx;
}

const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;
const dist = (a, bx, by) => Math.hypot(a.x - bx, a.y - by);

/** A station's breathing ring: r = 9, painted in the root transform. */
const stationRings = (ops) => ops.filter((o) => o.op === "stroke:arc" && near(o.r, 9) && o.tx === 0);
/** An envelope body: the only rounded rect with a 3px corner. */
const envelopeBodies = (ops) => ops.filter((o) => o.op === "stroke:rect" && o.cr === 3);
/** A verdict dot in flight to its shelf (r = 3.2, root transform). */
const flyingVerdicts = (ops) => ops.filter((o) => o.op === "fill:arc" && o.tx === 0 && near(o.r, 3.2));
/** A dot that has landed on a shelf (r = 3.4, root transform). */
const shelvedVerdicts = (ops) => ops.filter((o) => o.op === "fill:arc" && o.tx === 0 && near(o.r, 3.4));
/** The composed mark tile — the only shape painted in the badge's ink. */
const markTiles = (ops) => ops.filter((o) => o.op === "fill:rect" && o.style === "#0A0A0B");

/** Swap Math.random for the duration of `body`, always restoring it. */
function withRandom(source, body) {
  const real = Math.random;
  Math.random = source;
  try {
    return body();
  } finally {
    Math.random = real;
  }
}

const constant = (v) => () => v;

/** A tiny LCG: uniform-ish, seeded, and identical on every machine. */
function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Step `seconds` of simulation, painting every `renderEvery`-th frame. */
function simulate(engine, ctx, seconds, renderEvery = 1) {
  const frames = Math.round(seconds / FRAME);
  for (let i = 0; i < frames; i++) {
    engine.step(FRAME);
    if (i % renderEvery === 0) engine.render(ctx);
  }
}

function sized() {
  const engine = createTriageBoot();
  engine.resize(W, H);
  return engine;
}

/* -------------------------------------------------------------------------
 * The loop: the pipeline actually runs.
 * ---------------------------------------------------------------------- */

test("the field is already mid-flight on the first frame", () => {
  // "A real wait can be short" — the boot may only be on screen for 1.5 s, so
  // the pipeline is seeded in flight rather than starting empty and filling.
  withRandom(constant(0.5), () => {
    const ctx = recordingContext();
    const engine = sized();
    engine.step(FRAME);
    engine.render(ctx);
    const centres = new Set(envelopeBodies(ctx.ops).map((e) => `${e.x}|${e.y}`));
    assert.equal(centres.size, 3, "one seeded envelope per stage of the pipeline");

    // And the positive control for every scene assertion below: seeding is
    // gated on the engine having been sized, so an engine that was never
    // resized has no field on its first frame — a "the pipeline did X" test
    // run against one would pass vacuously.
    const bare = recordingContext();
    const unsized = createTriageBoot();
    unsized.step(FRAME);
    unsized.render(bare);
    assert.equal(envelopeBodies(bare.ops).length, 0, "an unsized engine seeds nothing");
  });
});

test("the loop draws three stations on an ascending diagonal", () => {
  withRandom(constant(0.5), () => {
    const ctx = recordingContext();
    const engine = sized();
    engine.step(FRAME);
    engine.render(ctx);

    const rings = stationRings(ctx.ops);
    assert.equal(rings.length, 3, "one ring per classifier layer");
    // The design claim is the ascent — rules, then embeddings, then SetFit,
    // each further right and further up. Exact coordinates are not asserted:
    // moving them is a design decision, not a regression.
    assert.ok(rings[0].x < rings[1].x && rings[1].x < rings[2].x, "stations run left to right");
    assert.ok(rings[0].y > rings[1].y && rings[1].y > rings[2].y, "and bottom to top");
    for (const r of rings) {
      assert.ok(r.x > 0 && r.x < W && r.y > 0 && r.y < H, "every station is on screen");
    }
  });
});

test("an envelope travels to a station, classifies, and its verdict reaches a shelf", () => {
  // 0.1 loses every escalation roll (`Math.random() < 0.62` at the first
  // station), so this drives the shortest complete path: travel → dwell →
  // charge → shrink → a dot that flies to the tally.
  withRandom(constant(0.1), () => {
    const ctx = recordingContext();
    const engine = sized();
    const stations = (() => {
      const c = recordingContext();
      engine.step(FRAME);
      engine.render(c);
      return stationRings(c.ops);
    })();

    simulate(engine, ctx, 4);

    const arrived = envelopeBodies(ctx.ops).some((e) => dist(e, stations[0].x, stations[0].y) < 8);
    assert.ok(arrived, "an envelope converges on the first station");
    assert.ok(flyingVerdicts(ctx.ops).length > 0, "a verdict dot is released");
    assert.ok(shelvedVerdicts(ctx.ops).length > 0, "and it lands on a shelf");
  });
});

test("a confident first layer keeps envelopes off the upper layers; an unconfident one escalates", () => {
  const stationsOf = (engine) => {
    const c = recordingContext();
    engine.step(FRAME);
    engine.render(c);
    return stationRings(c.ops);
  };

  // 0.1 < 0.62: the rules layer answers, so nothing ever climbs to SetFit.
  withRandom(constant(0.1), () => {
    const engine = sized();
    const top = stationsOf(engine)[2];
    const ctx = recordingContext();
    simulate(engine, ctx, 6);
    const reached = envelopeBodies(ctx.ops).some((e) => dist(e, top.x, top.y) < 40);
    assert.equal(reached, false, "a confident rules verdict never escalates");
  });

  // 0.99 loses at layers 1 and 2 (0.62, 0.58) and wins at layer 3 (p = 1):
  // every envelope climbs the whole pipeline and SetFit answers.
  withRandom(constant(0.99), () => {
    const engine = sized();
    const top = stationsOf(engine)[2];
    const ctx = recordingContext();
    simulate(engine, ctx, 6);
    const reached = envelopeBodies(ctx.ops).some((e) => dist(e, top.x, top.y) < 8);
    assert.ok(reached, "an unconfident pipeline escalates to the last layer");
    const setfit = shelvedVerdicts(ctx.ops).some((d) => d.style === HUE.setfit);
    assert.ok(setfit, "and the last layer's verdict is shelved");
  });
});

test("amber verdicts are gated to the review shelf, and both shelves stay bounded", () => {
  // A seeded LCG rather than a constant: the amber gate is one roll inside a
  // path several rolls deep, so a single fixed value cannot reach it without
  // modelling the exact call order — which would be a test of the call order.
  // Seed 7 is pinned because it produces both kinds of verdict within the
  // simulated minute; any seed that does would serve.
  withRandom(lcg(7), () => {
    const ctx = recordingContext();
    simulate(sized(), ctx, 60, 6);

    const shelved = shelvedVerdicts(ctx.ops);
    assert.ok(shelved.length > 0, "verdicts accumulate on the shelves");

    // The two shelves are far apart vertically; the boundary just has to sit
    // between them, and each shelf's stack is at most 7 × 13px tall.
    const review = shelved.filter((d) => d.y > H * 0.4);
    const tally = shelved.filter((d) => d.y <= H * 0.4);
    assert.ok(review.length > 0, "some envelope was gated to review");
    assert.ok(tally.length > 0, "and others were tallied");

    assert.ok(
      review.every((d) => d.style === HUE.amber),
      "only amber (gated) verdicts reach the review shelf",
    );
    assert.ok(
      tally.every((d) => d.style !== HUE.amber),
      "and no amber verdict is tallied as answered",
    );

    // The bound is the point — a shelf that grows without limit walks off the
    // top of the screen and holds more state the longer the boot is held. The
    // recorded ops are split back into frames on the `clearRect` each render
    // begins with, so this counts what was on screen AT ONCE.
    let frame = [];
    const frames = [];
    for (const o of ctx.ops) {
      if (o.op === "clear") {
        if (frame.length) frames.push(frame);
        frame = [];
      } else if (o.op === "fill:arc" && o.tx === 0 && near(o.r, 3.4)) {
        frame.push(o);
      }
    }
    if (frame.length) frames.push(frame);
    for (const f of frames) {
      assert.ok(f.filter((d) => d.y <= H * 0.4).length <= 7, "the tally shelf holds at most 7");
      assert.ok(f.filter((d) => d.y > H * 0.4).length <= 3, "the review shelf holds at most 3");
    }
  });
});

/* -------------------------------------------------------------------------
 * Reduced motion.
 * ---------------------------------------------------------------------- */

test("reduced motion is a still poster: the scene never changes between frames", () => {
  const engine = sized();
  engine.setReduced(true);

  const first = recordingContext();
  engine.render(first);
  withRandom(constant(0.5), () => {
    for (let i = 0; i < 120; i++) engine.step(FRAME);
  });
  const later = recordingContext();
  engine.render(later);

  assert.ok(envelopeBodies(first.ops).length > 0, "the poster is not blank");
  assert.deepEqual(later.ops, first.ops, "two seconds of stepping changes nothing");
});

test("switching to reduced motion mid-loop clears the moving field", () => {
  withRandom(constant(0.5), () => {
    const engine = sized();
    const running = recordingContext();
    simulate(engine, running, 3);
    const moving = new Set(envelopeBodies(running.ops).map((e) => `${e.x}|${e.y}`));
    assert.ok(moving.size > 3, "the loop had a moving field to clear");

    engine.setReduced(true);
    const poster = recordingContext();
    engine.render(poster);
    const posterPositions = new Set(envelopeBodies(poster.ops).map((e) => `${e.x}|${e.y}`));
    assert.equal(posterPositions.size, 3, "the poster is one charged envelope per station");
  });
});

/* -------------------------------------------------------------------------
 * Resolve: the exit's timing contract.
 * ---------------------------------------------------------------------- */

test("exitProgress stays 0 for as long as the loop is holding", () => {
  withRandom(constant(0.5), () => {
    const engine = sized();
    const ctx = recordingContext();
    for (let i = 0; i < 600; i++) {
      engine.step(FRAME);
      assert.equal(engine.exitProgress, 0, "a holding pattern reports no progress");
      assert.equal(engine.done, false);
    }
    engine.render(ctx);
  });
});

test("the exit runs for 400ms, and 200ms under reduced motion", () => {
  withRandom(constant(0.5), () => {
    const full = sized();
    full.resolve(null);
    full.step(0.39);
    assert.equal(full.done, false, "not done at 390ms");
    assert.ok(full.exitProgress > 0.95 && full.exitProgress < 1);
    full.step(0.02);
    assert.equal(full.done, true, "done by 410ms");
    assert.equal(full.exitProgress, 1, "progress clamps at 1 rather than overshooting");

    const reduced = sized();
    reduced.setReduced(true);
    reduced.resolve(null);
    reduced.step(0.19);
    assert.equal(reduced.done, false, "not done at 190ms");
    reduced.step(0.02);
    assert.equal(reduced.done, true, "done by 210ms — half the exit, no flight");
  });
});

test("the cover's reveal cue arrives at the exit's midpoint", () => {
  // BootOverlay fades its opaque cover when exitProgress passes 0.5 — that is
  // the fly-home leg, when the mark has to land on the real header logo. Too
  // early and the shell is bare; too late and the mark lands on nothing.
  withRandom(constant(0.5), () => {
    const engine = sized();
    engine.resolve(null);
    engine.step(0.19);
    assert.ok(engine.exitProgress < 0.5, "the cover is still opaque before the midpoint");
    engine.step(0.02);
    assert.ok(engine.exitProgress >= 0.5, "and lifts once past it");
  });
});

test("a second resolve does not restart the exit, and stepping past done is inert", () => {
  withRandom(constant(0.5), () => {
    const engine = sized();
    engine.resolve(null);
    engine.step(0.2);
    engine.resolve({ x: 10, y: 10, size: 10 });
    engine.step(0.2);
    assert.equal(engine.done, true, "the exit ran once, for its own duration");

    engine.step(5);
    assert.equal(engine.done, true);
    assert.equal(engine.exitProgress, 1);

    const ctx = recordingContext();
    engine.render(ctx);
    assert.deepEqual(
      ctx.ops.filter((o) => o.op !== "clear"),
      [],
      "a finished boot paints nothing — the real shell is underneath",
    );
  });
});

test("the mark leaves from the centre of the screen and flies to the measured header tile", () => {
  const home = { x: 900, y: 40, size: 30 };
  withRandom(constant(0.5), () => {
    const engine = sized();
    simulate(engine, recordingContext(), 1);
    engine.resolve(home);

    engine.step(0.16); // 40% through the exit: the mark is composing, still centred
    const composing = recordingContext();
    engine.render(composing);
    const start = markTiles(composing.ops).at(-1);
    assert.ok(start, "the mark is drawn while the stations morph into it");
    assert.ok(near(start.x, W / 2, 2), "it composes at the centre of the screen");
    assert.ok(Math.abs(start.y - H * 0.47) < 2);

    engine.step(0.2); // 90% through: the flight is all but over
    const landing = recordingContext();
    engine.render(landing);
    const end = markTiles(landing.ops).at(-1);
    assert.ok(end, "the mark is still drawn on the last leg");
    assert.ok(dist(end, home.x, home.y) < 25, "it has all but reached the header tile");
    assert.ok(Math.abs(end.w - home.size) < 5, "and shrunk to the tile's size");
  });
});

test("with no measured header tile the mark flies to the top-left fallback", () => {
  withRandom(constant(0.5), () => {
    const engine = sized();
    simulate(engine, recordingContext(), 1);
    engine.resolve(null);
    engine.step(0.36);
    const ctx = recordingContext();
    engine.render(ctx);
    const end = markTiles(ctx.ops).at(-1);
    assert.ok(end, "a mark is still drawn without a measured home");
    assert.ok(end.x < W * 0.25 && end.y < H * 0.25, "it heads for the header's corner, not the centre");
  });
});
