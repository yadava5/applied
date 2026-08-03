"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A number that rolls up from zero the first time it scrolls into view. Used for
 * the load-bearing stats — 0.9791 macro-F1 (the rules stage), 288 tests,
 * 22.8 MB, 9 classes.
 *
 * The final, formatted value is what renders on the server and on first paint,
 * so no-JS, crawlers, and reduced-motion all read the true number with zero
 * layout shift. Only after mount, and only if motion is allowed, does it reset
 * to zero (deferred a frame so the swap never paints) and ease back up when it
 * first scrolls into view — which, for every use here, is below the fold.
 */

const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

export function CountUp({
  end,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 1400,
  className,
}: {
  end: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const format = (v: number) =>
    `${prefix}${v.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}${suffix}`;

  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(() => format(end));
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || typeof IntersectionObserver === "undefined") return;

    // Only the animate-on-scroll case is safe to reset to zero. If the element
    // already sits at or above the fold, keep the server-rendered final value:
    // resetting it to 0 and then relying on an IntersectionObserver callback
    // that (with the rootMargin below, or in a background tab) may never fire
    // is exactly what strands a visible number at 0. Roll up only what the
    // reader will actually scroll *down* into.
    const rect = el.getBoundingClientRect();
    const belowFold = rect.top >= window.innerHeight;
    if (!belowFold) return;

    let raf0 = 0;
    let rafN = 0;

    // Reset to zero in the next frame (never synchronously in the effect body),
    // while the element is still off-screen below — so the swap is never seen.
    raf0 = requestAnimationFrame(() => setDisplay(format(0)));

    const run = () => {
      if (started.current) return;
      started.current = true;
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min(1, (now - t0) / duration);
        setDisplay(format(end * easeOutExpo(p)));
        if (p < 1) rafN = requestAnimationFrame(tick);
        else setDisplay(format(end));
      };
      rafN = requestAnimationFrame(tick);
    };

    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            run();
            io.disconnect();
            break;
          }
        }
      },
      { threshold: 0, rootMargin: "0px 0px -12% 0px" },
    );
    io.observe(el);
    return () => {
      cancelAnimationFrame(raf0);
      cancelAnimationFrame(rafN);
      io.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [end, decimals, prefix, suffix, duration]);

  return (
    <span ref={ref} className={className}>
      {display}
    </span>
  );
}
