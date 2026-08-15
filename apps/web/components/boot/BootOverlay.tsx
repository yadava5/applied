"use client";

import { useEffect, useRef, useState } from "react";

import {
  BOOT_BEGIN_EVENT,
  clearBootFlag,
  isBootPath,
  readBootFlag,
} from "@/lib/boot/flag";
import { createTriageBoot } from "@/lib/boot/triage";
import { warmSiblingRoutes } from "@/lib/boot/warm";

/**
 * The post-auth boot: the Triage render (`lib/boot/triage.ts`) played full
 * screen over the app's first paint after sign-in. Mounted once in the root
 * layout so it survives the login → dashboard client navigation; visibility
 * is carried by `data-boot` on <html> (raised pre-paint by BOOT_INIT_SCRIPT
 * for the OAuth document round-trip, or here for the same-tab path), which
 * CSS in globals.css turns into an opaque cover under this canvas.
 *
 * The loop is a holding pattern, not a meter — it makes no progress claims.
 * It releases on the app's REAL ready signal: the target route has committed
 * and no `loading.tsx` surface (`[aria-busy="true"][aria-label^="Loading"]`)
 * is still on screen. Floors and ceilings, so it neither flashes nor stalls:
 *
 *  - MIN_VISIBLE 1500 ms (700 reduced-motion): the origin render after
 *    sign-in is 700–1150 ms anyway (#203), so the floor adds at most a few
 *    hundred ms and guarantees one full classify→verdict pass is seen.
 *    Measured from navigation start on document loads (the cover has been
 *    up since first paint), from arm time on client navs.
 *  - MAX_HOLD 8 s: if the app never reports ready, the boot resolves anyway
 *    and the route's own quiet-form skeleton continues the story — never an
 *    unbounded spinner.
 *  - AUTH_ABORT 2.5 s: bounced back to /login (failed cookie race, revoked
 *    session), the overlay gets out of the way immediately.
 *
 * The exit is half the design: stations morph into the logo, the mark flies
 * to the measured header tile, and the cover fades to reveal the real shell
 * — then the whole element unmounts. A CSS-only failsafe in globals.css
 * retires the cover after 10 s even if this script dies.
 */

const MIN_VISIBLE_MS = 1500;
const MIN_VISIBLE_REDUCED_MS = 700;
const MAX_HOLD_MS = 8000;
const AUTH_ABORT_MS = 2500;

/** A route-level pending surface (loading.tsx) still holding the screen.
 *  Scoped by label so ApplicationRow's row-level `aria-busy` never counts. */
const PENDING_SELECTOR = '[aria-busy="true"][aria-label^="Loading"]';

const isAuthPath = (p: string) => p.startsWith("/login") || p.startsWith("/signup");

/** The real header logo's tile (Logo.tsx renders `.brand-logo`; the square
 *  mark occupies the left, height-sized cell of the lockup). */
function findMarkHome() {
  const el = document.querySelector<SVGSVGElement>(".brand-logo");
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return { x: r.left + r.height / 2, y: r.top + r.height / 2, size: r.height };
}

export function BootOverlay() {
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  /** null = dormant. `sinceNav` anchors MIN_VISIBLE to navigation start for
   *  document loads (the pre-paint cover already counted that time). */
  const [boot, setBoot] = useState<{ target: string; sinceNav: boolean } | null>(null);

  // Arm on mount (OAuth document arrival) and on the same-tab begin event
  // (email sign-in). Activating consumes the flag, so a plain reload of
  // /dashboard never replays the boot. The flag read is deferred off the
  // effect body into a macrotask (the BetaBanner idiom) — no synchronous
  // setState in an effect, no hydration mismatch; the pre-paint cover
  // (`data-boot`) keeps the screen correct in the meantime.
  useEffect(() => {
    const id = window.setTimeout(() => {
      const target = readBootFlag();
      if (target && isBootPath(window.location.pathname)) {
        clearBootFlag();
        setBoot((prev) => prev ?? { target, sinceNav: true });
      }
    }, 0);
    const onBegin = (e: Event) => {
      const target = (e as CustomEvent<string>).detail;
      if (typeof target === "string" && isBootPath(target)) {
        clearBootFlag();
        setBoot((prev) => prev ?? { target, sinceNav: false });
      }
    };
    window.addEventListener(BOOT_BEGIN_EVENT, onBegin);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener(BOOT_BEGIN_EVENT, onBegin);
    };
  }, []);

  useEffect(() => {
    if (!boot) return;
    const canvas = canvasRef.current;
    const root = rootRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !root || !ctx) {
      delete document.documentElement.dataset.boot;
      return;
    }
    document.documentElement.dataset.boot = "1";

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const engine = createTriageBoot();
    engine.setReduced(reduced);

    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.floor(window.innerWidth * dpr));
      canvas.height = Math.max(1, Math.floor(window.innerHeight * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      engine.resize(window.innerWidth, window.innerHeight);
    };
    fit();
    window.addEventListener("resize", fit);

    const minVisible = reduced ? MIN_VISIBLE_REDUCED_MS : MIN_VISIBLE_MS;
    // performance.now() on a fresh document ≈ time since navigation start,
    // which is when the pre-paint cover went up.
    const start = boot.sinceNav ? 0 : performance.now();
    let resolved = false;
    let revealed = false;
    let leftAuth = false;
    let raf = 0;
    let last = performance.now();

    const finish = () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", fit);
      delete document.documentElement.dataset.boot;
      root.removeAttribute("data-reveal");
      setBoot(null);
    };

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!resolved) {
        const elapsed = now - start;
        const path = window.location.pathname;
        if (isAuthPath(path)) {
          // Sign-in fell through after arming — get out of the way.
          if (leftAuth || elapsed >= AUTH_ABORT_MS) {
            finish();
            return;
          }
        } else if (isBootPath(path)) {
          leftAuth = true;
          const ready =
            elapsed >= minVisible && !document.querySelector(PENDING_SELECTOR);
          if (ready || elapsed >= MAX_HOLD_MS) {
            resolved = true;
            engine.resolve(findMarkHome());
            warmSiblingRoutes(path);
          }
        } else if (elapsed >= MAX_HOLD_MS) {
          finish();
          return;
        }
      } else if (!revealed && engine.exitProgress >= (reduced ? 0 : 0.5)) {
        // The fly-home leg: fade the opaque cover so the mark lands on the
        // real header logo (180 ms transition in globals.css).
        revealed = true;
        root.setAttribute("data-reveal", "1");
      }
      engine.step(dt);
      engine.render(ctx);
      if (engine.done) {
        finish();
        return;
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", fit);
      delete document.documentElement.dataset.boot;
    };
  }, [boot]);

  // Rendered on every page (hidden by CSS unless <html data-boot="1">) so the
  // pre-paint script has a cover to show before hydration. The canvas only
  // exists while a boot is actually running.
  return (
    <div
      ref={rootRef}
      className="boot-overlay"
      role="status"
      aria-label="Signing you in"
    >
      <div className="boot-overlay__cover" />
      {boot ? <canvas ref={canvasRef} className="boot-overlay__canvas" /> : null}
    </div>
  );
}
