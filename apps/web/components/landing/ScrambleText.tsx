"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

/**
 * A headline that decodes into place the first time it scrolls into view.
 *
 * Two modes, both wrap-safe and jitter-free: every character sits in its own
 * inline-block cell holding the *real* glyph's width, and words stay separated
 * by real spaces (the only line-break opportunities), so wrapping is identical
 * to plain text on every frame — critical at 375px.
 *
 *   · "decode"   — each character resolves from blurred/transparent to sharp,
 *                  left → right. Used on a proportional headline.
 *   · "scramble" — each character cycles a few random glyphs before locking to
 *                  its target. Meant for the monospace wordmark, where every
 *                  cell is exactly 1ch so random glyphs never shift width.
 *
 * Accessibility: the real string is exposed once via an sr-only node; the
 * animated cells are aria-hidden. On the server and under reduced-motion the
 * cells render fully resolved, so no-JS and motion-sensitive users get the
 * final text with no animation.
 */

const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&/<>*+=";

type Mode = "decode" | "scramble";

export function ScrambleText({
  text,
  mode = "decode",
  className,
  perCharMs = 34,
  active,
}: {
  text: string;
  mode?: Mode;
  className?: string;
  perCharMs?: number;
  /**
   * When omitted, the decode fires on scroll-in via IntersectionObserver. When
   * provided, the parent drives it: the animation runs as `active` flips true
   * (used by the signature ending to sync the wordmark to the envelope landing).
   */
  active?: boolean;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  // words[i] = array of chars; re-joined with real spaces between words.
  const words = useMemo(() => text.split(" ").map((w) => [...w]), [text]);
  // running start index (of non-space chars) for each word, so the render can
  // derive a stable global index per char without a mutable counter.
  const offsets = useMemo(() => {
    const out: number[] = [];
    let n = 0;
    for (const w of words) {
      out.push(n);
      n += w.length;
    }
    return out;
  }, [words]);
  const total = useMemo(() => words.reduce((n, w) => n + w.length, 0), [words]);

  const [progress, setProgress] = useState(total); // fully resolved on SSR
  const [glyphs, setGlyphs] = useState<string[]>([]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Resolved is the initial state, so reduced-motion / no-IO need no update.
    if (reduce || typeof IntersectionObserver === "undefined") return;

    let raf = 0;
    let started = false;

    const start = () => {
      if (started) return;
      started = true;
      const t0 = performance.now();
      const tick = (now: number) => {
        const revealed = Math.min(total, Math.floor((now - t0) / perCharMs));
        if (mode === "scramble") {
          setGlyphs(
            Array.from({ length: total }, () => GLYPHS[(Math.random() * GLYPHS.length) | 0]),
          );
        }
        setProgress(revealed);
        if (revealed < total) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    // Reset to unresolved in the next frame (never a synchronous effect
    // setState), then either play now (controlled) or on scroll-in.
    let io: IntersectionObserver | null = null;
    const kick = requestAnimationFrame(() => {
      setProgress(0);
      if (active !== undefined) {
        if (active) start();
        return;
      }
      io = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (e.isIntersecting) {
              start();
              io?.disconnect();
              break;
            }
          }
        },
        { threshold: 0, rootMargin: "0px 0px -10% 0px" },
      );
      io.observe(el);
    });

    return () => {
      cancelAnimationFrame(kick);
      cancelAnimationFrame(raf);
      io?.disconnect();
    };
  }, [text, mode, perCharMs, total, active]);

  return (
    <span ref={ref} className={className} style={{ position: "relative" }}>
      <span className="sr-only">{text}</span>
      <span aria-hidden style={{ whiteSpace: "normal" }}>
        {words.map((chars, wi) => (
          <span key={wi}>
            {wi > 0 ? " " : null}
            {chars.map((ch, ci) => {
              const idx = offsets[wi] + ci;
              const resolved = idx < progress;
              const showScramble = mode === "scramble" && !resolved;
              const glyph = showScramble ? glyphs[idx] ?? ch : ch;
              const style: CSSProperties = {
                display: "inline-block",
                whiteSpace: "pre",
              };
              if (mode === "decode") {
                if (resolved) {
                  style.transition =
                    "opacity 260ms ease, filter 260ms ease, transform 260ms ease";
                } else {
                  style.opacity = 0.15;
                  style.filter = "blur(6px)";
                  style.transform = "translateY(0.06em)";
                }
              }
              if (showScramble) style.color = "var(--text-muted)";
              return (
                <span key={ci} style={style}>
                  {glyph}
                </span>
              );
            })}
          </span>
        ))}
      </span>
    </span>
  );
}
