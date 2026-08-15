/**
 * The Triage boot — Applied's trademark render (variant 01 of the boot
 * candidates, approved 2026-08-14). The classifier pipeline enacted at full
 * screen for the seconds after sign-in: envelopes stream through the three
 * layer stations (cyan rules · violet e5 · green SetFit), some gated amber to
 * a review shelf, verdict dots climbing the diagonal to a tally. On resolve
 * the stations morph into the logo's own nodes, the composed mark flies to
 * the header slot, and the overlay's cover fades so the REAL shell is
 * revealed underneath — the one deliberate departure from the standalone
 * prototype, which had to sketch a shell because it had none to reveal.
 *
 * Same dialect as `lib/ambient/field.ts`: envelopes as rounded rect + flap,
 * gray strokes warming to a verdict hue (two-pass stroke, glow only while
 * charged), a classify ripple, a filled verdict dot. Hues are read from the
 * CSS custom properties so light/dark re-ink for free. Canvas 2D, no
 * libraries; the prototype measured 0.09–0.46 ms/frame. Orchestration —
 * canvas sizing, the rAF loop, the ready signal, reduced-motion policy —
 * stays with `components/boot/BootOverlay`, exactly as the ambient field
 * splits engine from surface.
 */

type Colors = {
  rules: string;
  emb: string;
  setfit: string;
  amber: string;
  gray: string;
};

const FALLBACK: Colors = {
  rules: "#38bdf8",
  emb: "#a78bfa",
  setfit: "#34d399",
  amber: "#f59e0b",
  gray: "#d6d8db",
};

type EnvState = "travel" | "dwell" | "charge" | "shrink";

type EnvActor = {
  x: number;
  y: number;
  s: number;
  /** Station index the envelope is heading for / sitting at. */
  k: number;
  st: EnvState;
  t: number;
  charge: number;
  hue: string;
  rip: number; // -1 idle, else 0..1 ripple progress
  alpha: number;
  dead?: boolean;
};

type VerdictDot = { x: number; y: number; hue: string; t: number; toReview: boolean; dead?: boolean };
type TallyMark = { hue: string; a: number };
type Station = { x: number; y: number; hue: string };

/** Where the mark should land — the real header logo's tile, in CSS px. */
export type MarkHome = { x: number; y: number; size: number };

export interface TriageBoot {
  resize(w: number, h: number): void;
  setReduced(r: boolean): void;
  /** Begin the exit. `home` is the measured header-logo tile, or null to
   *  use a top-left fallback when the shell hasn't offered one. */
  resolve(home: MarkHome | null): void;
  readonly done: boolean;
  /** 0 while looping; exit progress 0..1 once resolved. The overlay fades
   *  its opaque cover when this passes the fly-home leg (≥ 0.5). */
  readonly exitProgress: number;
  step(dt: number): void;
  render(ctx: CanvasRenderingContext2D): void;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);
const easeInOut = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const rand = (a: number, b: number) => a + Math.random() * (b - a);

function readColors(): Colors {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb;
  return {
    rules: v("--viz-rules", FALLBACK.rules),
    emb: v("--viz-embeddings", FALLBACK.emb),
    setfit: v("--viz-setfit", FALLBACK.setfit),
    amber: v("--amber", FALLBACK.amber),
    gray: v("--foreground", FALLBACK.gray),
  };
}

function roundRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
}

/** The shared glyph: envelope warming gray → hue, exactly like the ambient
 *  field's resolve (two-pass stroke, glow only while charged). */
function envelope(
  ctx: CanvasRenderingContext2D,
  colors: Colors,
  x: number,
  y: number,
  s: number,
  o: { alpha: number; charge: number; hue: string; dot?: boolean; scale?: number },
) {
  const bw = s;
  const bh = s * 0.66;
  ctx.save();
  ctx.translate(x, y);
  if (o.scale !== undefined && o.scale !== 1) ctx.scale(o.scale, o.scale);
  ctx.lineWidth = 1.4;

  const body = () => {
    roundRectPath(ctx, -bw / 2, -bh / 2, bw, bh, 3);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-bw / 2, -bh / 2);
    ctx.lineTo(0, bh * 0.16);
    ctx.lineTo(bw / 2, -bh / 2);
    ctx.stroke();
  };
  // gray pass
  ctx.globalAlpha = o.alpha * (1 - o.charge * 0.85);
  ctx.strokeStyle = colors.gray;
  body();
  // hue pass
  if (o.charge > 0.02) {
    ctx.globalAlpha = o.alpha * o.charge;
    ctx.strokeStyle = o.hue;
    ctx.shadowColor = o.hue;
    ctx.shadowBlur = 14 * o.charge;
    body();
    ctx.shadowBlur = 0;
  }
  // verdict dot
  if (o.dot && o.charge > 0.2) {
    ctx.globalAlpha = Math.min(1, o.alpha * o.charge * 1.6);
    ctx.fillStyle = o.hue;
    ctx.beginPath();
    ctx.arc(0, bh * 0.02, 2 + o.charge * 1.6, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function ripple(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  hue: string,
  a: number,
) {
  ctx.save();
  ctx.globalAlpha = a;
  ctx.strokeStyle = hue;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

/** The mark tile's three nodes (Logo.tsx geometry, 48-unit viewbox), centred. */
function markNodes(size: number) {
  const k = size / 48;
  return [
    { x: (13.5 - 24) * k, y: (33.5 - 24) * k, r: 3 * k, kind: "ring" as const },
    { x: (24 - 24) * k, y: (24 - 24) * k, r: 3 * k, kind: "ring" as const },
    { x: (34.5 - 24) * k, y: (14.5 - 24) * k, r: 4.1 * k, kind: "dot" as const },
  ];
}

/** The pipeline tile itself — dark badge in both themes, like `Logo.tsx`. */
function drawMark(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
  alpha: number,
) {
  if (alpha <= 0) return;
  const k = size / 48;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalAlpha = alpha;
  roundRectPath(ctx, -size / 2, -size / 2, size, size, 12 * k);
  ctx.fillStyle = "#0A0A0B";
  ctx.fill();
  ctx.strokeStyle = "rgba(128,128,128,0.4)";
  ctx.lineWidth = Math.max(1, 1.5 * k);
  ctx.stroke();
  // the two connector dashes
  ctx.strokeStyle = "rgba(247,248,248,0.65)";
  ctx.lineWidth = 2 * k;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo((17.2 - 24) * k, (30.2 - 24) * k);
  ctx.lineTo((20.3 - 24) * k, (27.4 - 24) * k);
  ctx.moveTo((27.7 - 24) * k, (20.7 - 24) * k);
  ctx.lineTo((30.6 - 24) * k, (18.1 - 24) * k);
  ctx.stroke();
  // nodes: two cyan process rings ascending to the emerald verdict
  ctx.lineWidth = 2.4 * k;
  for (const n of markNodes(size)) {
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    if (n.kind === "ring") {
      ctx.strokeStyle = FALLBACK.rules;
      ctx.stroke();
    } else {
      ctx.fillStyle = FALLBACK.setfit;
      ctx.fill();
    }
  }
  ctx.restore();
}

export function createTriageBoot(): TriageBoot {
  const C = readColors();
  let w = 0;
  let h = 0;
  let envs: EnvActor[] = [];
  let dots: VerdictDot[] = [];
  let tally: TallyMark[] = [];
  const review: TallyMark[] = [];
  let spawnT = 0.2;
  let clock = 0;
  let seeded = false;
  let mode: "loop" | "exit" | "done" = "loop";
  let exitT = 0;
  let reduced = false;
  let home: MarkHome = { x: 44, y: 26, size: 26 };

  const stations = (): Station[] => [
    { x: w * 0.31, y: h * 0.72, hue: C.rules },
    { x: w * 0.5, y: h * 0.49, hue: C.emb },
    { x: w * 0.69, y: h * 0.26, hue: C.setfit },
  ];

  function spawn() {
    envs.push({
      x: -30,
      y: h * 0.72 + rand(-h * 0.16, h * 0.14),
      s: rand(26, 36),
      k: 0,
      st: "travel",
      t: 0,
      charge: 0,
      hue: C.rules,
      rip: -1,
      alpha: 0.65,
    });
  }

  /** A real wait can be short — the field must be mid-flight at t=0. */
  function seed() {
    const S = stations();
    envs.push(
      { x: w * 0.14, y: h * 0.7, s: 30, k: 0, st: "travel", t: 0, charge: 0, hue: C.rules, rip: -1, alpha: 0.65 },
      { x: S[0].x, y: S[0].y, s: 27, k: 0, st: "dwell", t: 0.18, charge: 0, hue: C.rules, rip: -1, alpha: 0.65 },
      { x: S[1].x, y: S[1].y, s: 32, k: 1, st: "charge", t: 0.28, charge: 0.5, hue: C.emb, rip: 0.3, alpha: 0.65 },
    );
  }

  function step(dt: number) {
    if (mode === "done") return;
    if (mode === "exit") {
      exitT += dt / (reduced ? 0.2 : 0.4);
      if (exitT >= 1) {
        exitT = 1;
        mode = "done";
      }
      return;
    }
    if (reduced) return;
    if (!seeded && w > 0) {
      seed();
      seeded = true;
    }
    clock += dt;
    spawnT -= dt;
    if (spawnT <= 0 && envs.length < 6) {
      spawn();
      spawnT = rand(0.9, 1.5);
    }
    const S = stations();
    for (const e of envs) {
      if (e.st === "travel") {
        const tgt = S[e.k];
        const dx = tgt.x - e.x;
        const dy = tgt.y - e.y;
        const d = Math.hypot(dx, dy);
        const sp = Math.max(60, d * 1.6);
        if (d < 4) {
          e.st = "dwell";
          e.t = rand(0.3, 0.45);
        } else {
          e.x += (dx / d) * sp * dt;
          e.y += (dy / d) * sp * dt;
        }
      } else if (e.st === "dwell") {
        e.t -= dt;
        if (e.t <= 0) {
          // Per-station odds of a verdict here vs escalating a layer up; the
          // last layer always answers, sometimes amber (gated to review).
          const p = [0.62, 0.58, 1][e.k];
          if (Math.random() < p) {
            e.st = "charge";
            e.t = 0.4;
            e.rip = 0;
            e.hue = e.k === 2 && Math.random() < 0.22 ? C.amber : S[e.k].hue;
          } else {
            e.k++;
            e.st = "travel";
          }
        }
      } else if (e.st === "charge") {
        e.charge = Math.min(1, e.charge + dt / 0.35);
        e.t -= dt;
        if (e.t <= 0) {
          e.st = "shrink";
          e.t = 0.28;
        }
      } else if (e.st === "shrink") {
        e.t -= dt;
        if (e.t <= 0) {
          e.dead = true;
          dots.push({ x: e.x, y: e.y, hue: e.hue, t: 0, toReview: e.hue === C.amber });
        }
      }
      if (e.rip >= 0) {
        e.rip += dt / 0.8;
        if (e.rip >= 1) e.rip = -1;
      }
    }
    envs = envs.filter((e) => !e.dead);
    for (const d of dots) {
      d.t += dt / 0.6;
      if (d.t >= 1) {
        d.dead = true;
        const bin = d.toReview ? review : tally;
        bin.push({ hue: d.hue, a: 0 });
        if (bin.length > (d.toReview ? 3 : 7)) bin.shift();
      }
    }
    dots = dots.filter((d) => !d.dead);
    for (const t of tally) t.a = Math.min(1, t.a + dt * 4);
    for (const t of review) t.a = Math.min(1, t.a + dt * 4);
  }

  function drawScene(ctx: CanvasRenderingContext2D, gAlpha: number) {
    const S = stations();
    const dark = document.documentElement.dataset.theme !== "light";
    ctx.save();
    ctx.globalAlpha = gAlpha;
    // connecting dashes (middle run of each leg, like the logo's)
    ctx.strokeStyle = dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.22)";
    ctx.lineWidth = 1.4;
    ctx.lineCap = "round";
    for (let i = 0; i < 2; i++) {
      const a = S[i];
      const b = S[i + 1];
      ctx.beginPath();
      ctx.moveTo(lerp(a.x, b.x, 0.34), lerp(a.y, b.y, 0.34));
      ctx.lineTo(lerp(a.x, b.x, 0.62), lerp(a.y, b.y, 0.62));
      ctx.stroke();
    }
    // stations breathe
    S.forEach((s, i) => {
      const br = 0.5 + 0.18 * Math.sin(clock * 1.8 + i * 2.1);
      ctx.globalAlpha = gAlpha * br;
      ctx.strokeStyle = s.hue;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(s.x, s.y, 9, 0, Math.PI * 2);
      ctx.stroke();
    });
    // envelopes
    for (const e of envs) {
      const sc = e.st === "shrink" ? Math.max(0.05, e.t / 0.28) : 1;
      envelope(ctx, C, e.x, e.y, e.s, {
        alpha: gAlpha * e.alpha,
        charge: e.charge,
        hue: e.hue,
        dot: true,
        scale: sc,
      });
      if (e.rip >= 0)
        ripple(ctx, e.x, e.y, 14 + e.rip * 34, e.hue, gAlpha * 0.35 * (1 - e.rip));
    }
    // traveling verdict dots (arc up the diagonal to their shelf)
    const exitP = { x: w * 0.8, y: h * 0.3 };
    const revP = { x: w * 0.8, y: h * 0.56 };
    for (const d of dots) {
      const tgt0 = d.toReview ? revP : exitP;
      const count = (d.toReview ? review : tally).length;
      const t = easeInOut(clamp01(d.t));
      const mx = lerp(d.x, tgt0.x, t);
      const my = lerp(d.y, tgt0.y - count * 13, t) - Math.sin(t * Math.PI) * 26;
      ctx.globalAlpha = gAlpha * 0.9;
      ctx.fillStyle = d.hue;
      ctx.beginPath();
      ctx.arc(mx, my, 3.2, 0, Math.PI * 2);
      ctx.fill();
    }
    // tally shelves
    const shelf = (bx: number, by: number, items: TallyMark[]) => {
      ctx.globalAlpha = gAlpha * 0.3;
      ctx.strokeStyle = C.gray;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(bx - 12, by + 12);
      ctx.lineTo(bx + 12, by + 12);
      ctx.stroke();
      items.forEach((it, i) => {
        ctx.globalAlpha = gAlpha * 0.85 * it.a;
        ctx.fillStyle = it.hue;
        ctx.beginPath();
        ctx.arc(bx, by - i * 13, 3.4, 0, Math.PI * 2);
        ctx.fill();
      });
    };
    shelf(exitP.x, exitP.y, tally);
    shelf(revP.x, revP.y, review);
    ctx.restore();
  }

  /** Reduced motion: one still frame with the field's character — an
   *  envelope charged at each station and a small settled tally. */
  function drawPoster(ctx: CanvasRenderingContext2D, gAlpha: number) {
    const S = stations();
    clock = 1.2;
    envs = S.map((s, i) => ({
      x: s.x - 46,
      y: s.y + 10,
      s: 30,
      k: i,
      st: "charge" as const,
      t: 0,
      charge: 0.9,
      hue: s.hue,
      rip: -1,
      alpha: 0.65,
    }));
    dots = [];
    if (!tally.length)
      tally = [
        { hue: C.rules, a: 1 },
        { hue: C.setfit, a: 1 },
        { hue: C.emb, a: 1 },
      ];
    drawScene(ctx, gAlpha);
  }

  function drawExit(ctx: CanvasRenderingContext2D) {
    const t = exitT;
    if (reduced) {
      // A plain crossfade: the poster thins out while the overlay's cover
      // (faded by the orchestrator) reveals the real shell. No flight.
      if (t < 1) drawPoster(ctx, 1 - t);
      return;
    }
    const S = stations();
    const p1 = clamp01(t / 0.5); // actors fade, stations morph into the mark
    const p2 = clamp01((t - 0.5) / 0.5); // mark flies home, cover fades
    if (p1 < 1) drawScene(ctx, 1 - p1);
    const cx0 = w * 0.5;
    const cy0 = h * 0.47;
    const size0 = 64;
    const cx = lerp(cx0, home.x, easeInOut(p2));
    const cy = lerp(cy0, home.y, easeInOut(p2));
    const size = lerp(size0, home.size, easeInOut(p2));
    if (p1 < 1) {
      // tween the three stations toward the composed mark's nodes
      const nodes = markNodes(size0);
      const e = easeInOut(p1);
      S.forEach((s, i) => {
        const nx = cx0 + nodes[i].x;
        const ny = cy0 + nodes[i].y;
        const x = lerp(s.x, nx, e);
        const y = lerp(s.y, ny, e);
        ctx.save();
        ctx.globalAlpha = 0.4 + 0.6 * e;
        if (nodes[i].kind === "ring") {
          ctx.strokeStyle = C.rules;
          ctx.lineWidth = lerp(2, 3.2, e);
          ctx.beginPath();
          ctx.arc(x, y, lerp(9, nodes[i].r, e), 0, Math.PI * 2);
          ctx.stroke();
        } else {
          ctx.fillStyle = C.setfit;
          ctx.beginPath();
          ctx.arc(x, y, lerp(9, nodes[i].r, e), 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      });
      drawMark(ctx, cx0, cy0, size0, easeInOut(p1) * 0.9 * (1 - p2));
    }
    if (p2 > 0) {
      // The last leg hands off to the real logo underneath: the flying mark
      // fades out exactly where the header's own tile already sits.
      const landA = 1 - clamp01((p2 - 0.78) / 0.22);
      drawMark(ctx, cx, cy, size, landA);
    }
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
    },
    setReduced(r) {
      reduced = r;
      if (r && mode === "loop") {
        envs = [];
        dots = [];
        seeded = false;
      }
    },
    resolve(markHome) {
      if (mode !== "loop") return;
      if (markHome) home = markHome;
      mode = "exit";
      exitT = 0;
    },
    get done() {
      return mode === "done";
    },
    get exitProgress() {
      return mode === "loop" ? 0 : exitT;
    },
    step,
    render(ctx) {
      ctx.clearRect(0, 0, w, h);
      if (mode === "loop") {
        if (reduced) drawPoster(ctx, 1);
        else drawScene(ctx, 1);
      } else if (mode === "exit") {
        drawExit(ctx);
      }
      // "done" renders nothing: the mark has landed on the real logo and the
      // orchestrator is about to drop the overlay entirely.
    },
  };
}
