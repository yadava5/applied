"use client";

import { useEffect, useRef } from "react";

import { createAmbientField, type AmbientFieldOptions } from "@/lib/ambient/field";

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
 *
 * The field itself lives in `lib/ambient/field` now — the shell's rail runs the
 * same engine at rail scale (`components/shell/AmbientRail`), so the two
 * surfaces cannot drift apart. This component keeps the landing's own
 * orchestration: full-viewport sizing and the live cursor.
 */

const LANDING_FIELD: AmbientFieldOptions = {
  areaPerEnv: 62000,
  minCount: 10,
  maxCount: 30,
  size: [16, 30],
  seedCool: [0, 6],
  refillCool: [2, 9],
  restCool: [4, 11],
  pointer: true,
};

export function AmbientField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const field = createAmbientField(canvas, LANDING_FIELD);
    if (!field) return;

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      field.resize(w, h, Math.min(window.devicePixelRatio || 1, 2));
    };

    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      field.step(dt);
      field.render();
      raf = requestAnimationFrame(loop);
    };

    const onMove = (ev: MouseEvent) => {
      field.setPointer(ev.clientX, ev.clientY, true);
    };
    const onLeave = () => {
      field.setPointer(-9999, -9999, false);
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
      field.settleStatic();
      window.addEventListener("resize", () => {
        resize();
        field.settleStatic();
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
