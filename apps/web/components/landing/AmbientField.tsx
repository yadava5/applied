"use client";

import { useEffect, useRef } from "react";

/**
 * App-native ambient background. Faint envelopes drift across the page and, now
 * and then, one "resolves" — its outline warming from neutral gray to one of the
 * four verdict hues (cyan rules · violet e5 · green SetFit · amber gate) with a
 * brief classify pulse and a small filled verdict dot. The whole field runs at
 * very low alpha on the near-black surface, so body copy stays fully legible; it
 * lives behind the z-10 content layer and never receives pointer events.
 *
 * Cursor-reactive: envelopes inside a soft radius drift gently away from the
 * pointer and brighten a touch. Hues are read from the CSS custom properties in
 * globals.css so the palette stays single-sourced.
 *
 * Reduced-motion (or a hidden tab) → one static frame, no rAF loop, no CPU. The
 * canvas is aria-hidden decoration.
 */

type Verdict = "rules" | "embeddings" | "setfit" | "amber";
const VERDICTS: Verdict[] = ["rules", "embeddings", "setfit", "amber"];
const FALLBACK: Record<Verdict, string> = {
  rules: "#38bdf8",
  embeddings: "#a78bfa",
  setfit: "#34d399",
  amber: "#f59e0b",
};

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

function rand(a: number, b: number) {
  return a + Math.random() * (b - a);
}

function readHue(el: HTMLElement, name: string, fb: string) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fb;
}

export function AmbientField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const root = document.documentElement;
    const colors: Record<Verdict, string> = {
      rules: readHue(root, "--viz-rules", FALLBACK.rules),
      embeddings: readHue(root, "--viz-embeddings", FALLBACK.embeddings),
      setfit: readHue(root, "--viz-setfit", FALLBACK.setfit),
      amber: readHue(root, "--amber", FALLBACK.amber),
    };
    const GRAY = "rgba(214, 216, 219, 1)"; // --foreground, alpha applied per-draw

    let w = 0;
    let h = 0;
    let dpr = 1;
    let envs: Env[] = [];
    const pointer = { x: -9999, y: -9999, active: false };

    const makeEnv = (seed = false): Env => ({
      x: rand(0, w || 1),
      y: rand(0, h || 1),
      vx: rand(-6, 6),
      vy: rand(-9, -3), // gentle upward drift
      s: rand(16, 30),
      hue: VERDICTS[(Math.random() * VERDICTS.length) | 0],
      charge: 0,
      phase: "idle",
      t: 0,
      cool: seed ? rand(0, 6) : rand(2, 9),
      ripple: -1,
    });

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Density scales with area, capped for perf.
      const target = Math.round(Math.min(30, Math.max(10, (w * h) / 62000)));
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
        ctx.strokeStyle = GRAY;
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

    const step = (e: Env, dt: number) => {
      e.x += e.vx * dt;
      e.y += e.vy * dt;
      // wrap
      const m = e.s;
      if (e.x < -m) e.x = w + m;
      if (e.x > w + m) e.x = -m;
      if (e.y < -m) e.y = h + m;
      if (e.y > h + m) e.y = -m;

      // pointer repel + brighten
      if (pointer.active) {
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
          e.cool = rand(4, 11);
        }
      }
      if (e.ripple >= 0) {
        e.ripple += dt / 0.9;
        if (e.ripple >= 1) e.ripple = -1;
      }
    };

    const render = () => {
      ctx.clearRect(0, 0, w, h);
      for (const e of envs) drawEnv(e);
    };

    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      for (const e of envs) step(e, dt);
      render();
      raf = requestAnimationFrame(loop);
    };

    const onMove = (ev: MouseEvent) => {
      pointer.x = ev.clientX;
      pointer.y = ev.clientY;
      pointer.active = true;
    };
    const onLeave = () => {
      pointer.active = false;
    };
    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else if (!reduce && raf === 0) {
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    };

    resize();

    if (reduce) {
      // Static frame: settle a few envelopes into resolved verdict states.
      for (let i = 0; i < envs.length; i++) {
        if (i % 4 === 0) {
          envs[i].charge = 0.85;
          envs[i].phase = "hold";
        }
      }
      render();
      window.addEventListener("resize", () => {
        resize();
        render();
      });
      return () => {
        // resize listener is anonymous; page unmount tears down anyway.
      };
    }

    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mouseleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 h-full w-full"
    />
  );
}
