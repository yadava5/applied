"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";

import { createAmbientField, type AmbientFieldOptions } from "@/lib/ambient/field";
import {
  onAmbientOverride,
  onAmbientPulse,
  readAmbientOverride,
  serverAmbientOverride,
} from "@/lib/shell/ambient-bus";
import { THEME_CHANGE_EVENT } from "@/lib/theme";

/**
 * The rail's ambient mail — the landing page's drifting-envelope field
 * (`lib/ambient/field`, one shared engine) at rail scale, mounted as a
 * BACKGROUND of the sidebar's middle run. The run is honestly empty on three
 * of the four tabs (and half-empty under the board's stage lens), and it must
 * stay empty of DATA — see Sidebar's #122 note — so what fills it is texture
 * with meaning, not another instrument.
 *
 * Geometry contract, non-negotiable: absolutely positioned (`-z-10`, behind
 * the run's in-flow content and the portaled stage lens), pointer-events-none,
 * ZERO layout height. It cannot re-create #122's overflow because it does not
 * participate in flow at all, and it cannot catch a click meant for a filter.
 *
 * It is a status surface, not only decoration: `lib/shell/ambient-bus`
 * publishes when something real lands — a sync that filed or removed rows, a
 * stage change — and the field answers with a flurry of resolves (envelopes
 * warming to verdict hues). Idle, it drifts at half the landing's tempo so
 * the surge stays legible as news.
 *
 * It costs nothing when it cannot be seen: reduced motion → one static
 * frame, no rAF; hidden tab → loop parked; below `md` the sidebar is
 * `display: none`, the observed size collapses to 0 and the loop parks the
 * same way (no rAF runs on mobile, where this component's canvas never
 * paints). The Settings toggle (Appearance → "Ambient mail") unmounts it
 * entirely: `enabled` carries the saved preference server-side, and the bus
 * override makes a fresh click instant before `router.refresh()` confirms it.
 */

const RAIL_FIELD: AmbientFieldOptions = {
  // ~240×600 of rail ≈ 6 envelopes — sized to the column, not the viewport.
  areaPerEnv: 24000,
  minCount: 4,
  maxCount: 9,
  size: [12, 22],
  seedCool: [1, 8],
  refillCool: [4, 12],
  // Half the landing's tempo: chrome should murmur, and a calm idle is what
  // lets a bus pulse read as an event instead of more weather.
  restCool: [8, 20],
  pointer: false,
};

export function AmbientRail({ enabled }: { enabled: boolean }) {
  // The session override (a toggle click that has saved but not yet
  // refreshed) wins over the server prop in BOTH directions; `null` before
  // any click, and on every server pass, so hydration cannot disagree.
  const override = useSyncExternalStore(
    onAmbientOverride,
    readAmbientOverride,
    serverAmbientOverride,
  );
  if (!(override ?? enabled)) return null;
  return <RailCanvas />;
}

function RailCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const field = createAmbientField(canvas, RAIL_FIELD);
    if (!field) return;

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let last = 0;
    let sized = false;
    let revealed = false;

    // The rail repaints at 30fps, not the display's rate. Measured on the
    // prod build (headless Chromium, /demo/shell at 1024): vsync-rate
    // repainting cost ~62ms of main-thread time per second — almost all of
    // it paint, the JS step is ~0.07ms — for a drift of ≤9px/s that a half
    // rate renders identically. The landing keeps its own full-rate loop:
    // it is cursor-reactive, this field deliberately is not.
    const FRAME_MS = 1000 / 30;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (now - last < FRAME_MS) return;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      field.step(dt);
      field.render();
    };
    // One gate for every "may the loop run" condition; callers just report
    // their own condition changing.
    const start = () => {
      if (reduce || raf !== 0 || !sized || document.hidden) return;
      last = performance.now();
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };
    // Default-on must not pop into a settled page: the canvas mounts at
    // opacity 0 and eases in only once it has painted a real frame.
    const reveal = () => {
      if (revealed) return;
      revealed = true;
      requestAnimationFrame(() => {
        canvas.style.opacity = "1";
      });
    };

    // The canvas is `absolute inset-0`, so its own border box IS the middle
    // run's box — observing it tracks the run through window resizes AND
    // through `md`'s display:none (which reports 0×0 and parks the loop).
    const observer = new ResizeObserver(() => {
      const { width, height } = canvas.getBoundingClientRect();
      if (width < 8 || height < 8) {
        sized = false;
        stop();
        return;
      }
      // dpr capped at 1.5, not the landing's 2: raster cost scales with
      // buffer pixels, and a 7%-alpha hairline field reads identically at
      // 1.5 on a retina display while paying 44% fewer of them.
      field.resize(width, height, Math.min(window.devicePixelRatio || 1, 1.5));
      sized = true;
      if (reduce) {
        field.settleStatic();
      } else {
        field.render();
        start();
      }
      reveal();
    });
    observer.observe(canvas);

    // A real event (ambient-bus): flurry. Under reduced motion the field is a
    // still image and stays one — the pulse is an enhancement, never a signal
    // someone must see move. A pulse while the tab is hidden only shortens
    // fuses; they fire when the loop resumes.
    const offPulse = onAmbientPulse((count) => {
      if (!reduce) field.pulse(count);
    });
    const onVisibility = () => {
      if (document.hidden) stop();
      else start();
    };
    // The rail outlives an Appearance flip; re-read the hues so a light-theme
    // field is not drawn in the dark theme's inks.
    const onTheme = () => {
      field.refreshColors();
      if (reduce && sized) field.settleStatic();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener(THEME_CHANGE_EVENT, onTheme);

    return () => {
      stop();
      observer.disconnect();
      offPulse();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener(THEME_CHANGE_EVENT, onTheme);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 h-full w-full opacity-0 transition-opacity duration-700"
    />
  );
}
