"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

/**
 * The landing's only bespoke client component: one IntersectionObserver that
 * flips `data-visible="true"` on its wrapper the first time it scrolls into
 * view. All the actual motion lives in CSS (see app/globals.css) so the shipped
 * JS is a few lines. Reduced-motion and no-JS both resolve to the final,
 * fully-visible state — the animation is pure enhancement, never a gate on
 * content.
 *
 * `stagger` switches the wrapper to `.reveal-stagger`, which animates its direct
 * children in sequence (each child supplies its own `--i` index for the delay).
 */
export function Reveal({
  children,
  className = "",
  stagger = false,
  style,
}: {
  children: ReactNode;
  className?: string;
  stagger?: boolean;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // No observer (very old browser) → reveal on the next tick, never gate
    // content behind the animation. Deferred so it isn't a synchronous
    // setState in the effect body.
    if (typeof IntersectionObserver === "undefined") {
      const id = setTimeout(() => setVisible(true), 0);
      return () => clearTimeout(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            io.disconnect();
            break;
          }
        }
      },
      // threshold 0 = fire as soon as any part enters, so a fast scroll never
      // skips a block; the negative bottom margin holds the reveal until the
      // element is a little way up from the fold.
      { threshold: 0, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      data-visible={visible ? "true" : undefined}
      className={`${stagger ? "reveal-stagger" : "reveal"} ${className}`.trim()}
      style={style}
    >
      {children}
    </div>
  );
}
