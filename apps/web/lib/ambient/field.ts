/**
 * The ambient mail field's ENGINE — the drifting envelopes the landing page
 * introduced (`components/landing/AmbientField`), extracted so the shell's
 * rail can run the same field at rail scale instead of keeping a second,
 * slowly-diverging copy. Everything visual lives here: the gentle upward
 * drift, the resolve cycle (an outline warming from neutral gray to one of
 * the four verdict hues — cyan rules · violet e5 · green SetFit · amber gate
 * — with a classify pulse and a small filled verdict dot), the ripple ring,
 * the pointer repel. What stays with each surface is ORCHESTRATION — canvas
 * sizing, the rAF loop, visibility/reduced-motion policy — because those
 * genuinely differ: full viewport with a live cursor on the landing, a
 * ~240px column that can be `display: none` below `md` on the rail.
 *
 * Hues are read from the CSS custom properties in globals.css so the palette
 * stays single-sourced. `refreshColors` re-reads them for a field that
 * outlives a theme flip (the rail under an Appearance change); the landing
 * page is pinned dark and never needs to.
 */

type Verdict = "rules" | "embeddings" | "setfit" | "amber";
const VERDICTS: Verdict[] = ["rules", "embeddings", "setfit", "amber"];
const FALLBACK: Record<Verdict, string> = {
  rules: "#38bdf8",
  embeddings: "#a78bfa",
  setfit: "#34d399",
  amber: "#f59e0b",
};
/** `--foreground`'s dark value — only reached if the var read fails. */
const FALLBACK_GRAY = "#d6d8db";

type Env = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  s: number;
  hue: Verdict;
  charge: number; // 0..1 resolve intensity
  phase: "idle" | "up" | "hold" | "down";
  t: number; // seconds left in current phase
  cool: number; // seconds until eligible to resolve again
  ripple: number; // -1 idle, else 0..1 progress
};

export interface AmbientFieldOptions {
  /** px² of canvas per envelope, clamped to [minCount, maxCount] — density
   *  scales with the surface's real area, so the rail never pays for the
   *  landing's full-viewport count. */
  areaPerEnv: number;
  minCount: number;
  maxCount: number;
  /** Envelope face width range, px. */
  size: [number, number];
  /** Seconds until a freshly SEEDED envelope's first resolve — staggered low
   *  so a new mount is alive quickly without firing all at once. */
  seedCool: [number, number];
  /** Same, for envelopes added by a later resize. */
  refillCool: [number, number];
  /** Seconds an envelope rests between resolves — the field's idle tempo. */
  restCool: [number, number];
  /** Cursor repel + brighten. Off for the rail: the canvas sits behind
   *  `pointer-events-none` chrome and a 240px column gives the effect no
   *  room to read as anything but jitter. */
  pointer: boolean;
}

export interface AmbientField {
  /** Adopt a new CSS-pixel size (the caller owns HOW it is measured). */
  resize(w: number, h: number, dpr: number): void;
  step(dt: number): void;
  render(): void;
  /** The reduced-motion frame: settle a few envelopes into resolved verdict
   *  states and paint once — the field's character with none of its CPU. */
  settleStatic(): void;
  /** A real event landed (mail filed, a stage moved): resolve up to `count`
   *  idle envelopes now, staggered so the surge reads as a flurry of
   *  classifications rather than a single flash. */
  pulse(count: number): void;
  setPointer(x: number, y: number, active: boolean): void;
  /** Re-read the verdict hues + gray from the CSS custom properties. */
  refreshColors(): void;
}

function rand(a: number, b: number) {
  return a + Math.random() * (b - a);
}

function readHue(el: HTMLElement, name: string, fb: string) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fb;
}

export function createAmbientField(
  canvas: HTMLCanvasElement,
  opts: AmbientFieldOptions,
): AmbientField | null {
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const root = document.documentElement;
  let colors: Record<Verdict, string>;
  let gray: string;
  const refreshColors = () => {
    colors = {
      rules: readHue(root, "--viz-rules", FALLBACK.rules),
      embeddings: readHue(root, "--viz-embeddings", FALLBACK.embeddings),
      setfit: readHue(root, "--viz-setfit", FALLBACK.setfit),
      amber: readHue(root, "--amber", FALLBACK.amber),
    };
    gray = readHue(root, "--foreground", FALLBACK_GRAY);
  };
  refreshColors();

  let w = 0;
  let h = 0;
  let envs: Env[] = [];
  const pointer = { x: -9999, y: -9999, active: false };

  const makeEnv = (seed = false): Env => ({
    x: rand(0, w || 1),
    y: rand(0, h || 1),
    vx: rand(-6, 6),
    vy: rand(-9, -3), // gentle upward drift
    s: rand(opts.size[0], opts.size[1]),
    hue: VERDICTS[(Math.random() * VERDICTS.length) | 0],
    charge: 0,
    phase: "idle",
    t: 0,
    cool: seed ? rand(opts.seedCool[0], opts.seedCool[1]) : rand(opts.refillCool[0], opts.refillCool[1]),
    ripple: -1,
  });

  const resize = (nextW: number, nextH: number, dpr: number) => {
    w = nextW;
    h = nextH;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Density scales with area, capped for perf.
    const target = Math.round(
      Math.min(opts.maxCount, Math.max(opts.minCount, (w * h) / opts.areaPerEnv)),
    );
    if (envs.length === 0) {
      envs = Array.from({ length: target }, () => makeEnv(true));
    } else if (target > envs.length) {
      while (envs.length < target) envs.push(makeEnv());
    } else if (target < envs.length) {
      envs.length = target;
    }
  };

  const roundRect = (x: number, y: number, rw: number, rh: number, r: number) => {
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(x, y, rw, rh, r);
    } else {
      ctx.beginPath();
      ctx.rect(x, y, rw, rh);
    }
  };

  const drawEnv = (e: Env) => {
    const bw = e.s;
    const bh = e.s * 0.66;
    const hue = colors[e.hue];
    const baseAlpha = 0.07;
    const alpha = baseAlpha + e.charge * 0.16;
    ctx.save();
    ctx.translate(e.x, e.y);
    ctx.globalAlpha = alpha;
    // stroke lerps gray → hue with charge; cheap two-pass instead of true lerp.
    ctx.lineWidth = 1;
    if (e.charge > 0.02) {
      ctx.shadowColor = hue;
      ctx.shadowBlur = 12 * e.charge;
      ctx.strokeStyle = hue;
    } else {
      ctx.strokeStyle = gray;
    }
    roundRect(-bw / 2, -bh / 2, bw, bh, 2.5);
    ctx.stroke();
    // flap
    ctx.beginPath();
    ctx.moveTo(-bw / 2, -bh / 2);
    ctx.lineTo(0, bh * 0.16);
    ctx.lineTo(bw / 2, -bh / 2);
    ctx.stroke();
    // verdict dot once resolved
    if (e.charge > 0.15) {
      ctx.globalAlpha = alpha * 1.5;
      ctx.fillStyle = hue;
      ctx.beginPath();
      ctx.arc(0, 0, 1.6 + e.charge * 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
    // ripple ring on classify
    if (e.ripple >= 0) {
      ctx.save();
      ctx.translate(e.x, e.y);
      ctx.globalAlpha = 0.14 * (1 - e.ripple);
      ctx.strokeStyle = hue;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(0, 0, e.s * 0.6 + e.ripple * e.s * 1.6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  };

  const stepEnv = (e: Env, dt: number) => {
    e.x += e.vx * dt;
    e.y += e.vy * dt;
    // wrap
    const m = e.s;
    if (e.x < -m) e.x = w + m;
    if (e.x > w + m) e.x = -m;
    if (e.y < -m) e.y = h + m;
    if (e.y > h + m) e.y = -m;

    // pointer repel + brighten
    if (opts.pointer && pointer.active) {
      const dx = e.x - pointer.x;
      const dy = e.y - pointer.y;
      const d2 = dx * dx + dy * dy;
      const R = 150;
      if (d2 < R * R && d2 > 0.01) {
        const d = Math.sqrt(d2);
        const f = (1 - d / R) * 22;
        e.x += (dx / d) * f * dt;
        e.y += (dy / d) * f * dt;
      }
    }

    // resolve cycle
    if (e.phase === "idle") {
      e.cool -= dt;
      if (e.cool <= 0) {
        e.phase = "up";
        e.t = 0.7;
        e.ripple = 0;
        e.hue = VERDICTS[(Math.random() * VERDICTS.length) | 0];
      }
    } else if (e.phase === "up") {
      e.charge = Math.min(1, e.charge + dt / 0.7);
      e.t -= dt;
      if (e.t <= 0) {
        e.phase = "hold";
        e.t = rand(0.8, 1.6);
      }
    } else if (e.phase === "hold") {
      e.t -= dt;
      if (e.t <= 0) {
        e.phase = "down";
        e.t = 1.3;
      }
    } else if (e.phase === "down") {
      e.charge = Math.max(0, e.charge - dt / 1.3);
      e.t -= dt;
      if (e.t <= 0 || e.charge <= 0) {
        e.charge = 0;
        e.phase = "idle";
        e.cool = rand(opts.restCool[0], opts.restCool[1]);
      }
    }
    if (e.ripple >= 0) {
      e.ripple += dt / 0.9;
      if (e.ripple >= 1) e.ripple = -1;
    }
  };

  return {
    resize,
    step(dt) {
      for (const e of envs) stepEnv(e, dt);
    },
    render() {
      ctx.clearRect(0, 0, w, h);
      for (const e of envs) drawEnv(e);
    },
    settleStatic() {
      for (let i = 0; i < envs.length; i++) {
        if (i % 4 === 0) {
          envs[i].charge = 0.85;
          envs[i].phase = "hold";
        }
      }
      this.render();
    },
    pulse(count) {
      let fired = 0;
      for (const e of envs) {
        if (fired >= count) break;
        if (e.phase !== "idle") continue;
        // Never LENGTHEN a fuse that was about to fire anyway.
        e.cool = Math.min(e.cool, 0.1 + fired * 0.35);
        fired++;
      }
    },
    setPointer(x, y, active) {
      pointer.x = x;
      pointer.y = y;
      pointer.active = active;
    },
    refreshColors,
  };
}
