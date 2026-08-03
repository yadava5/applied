"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The signature ending — Applied's own, no borrowed motif — now a full-bleed
 * band anchored at the very bottom of the landing.
 *
 * The pipeline runs horizontally, edge to edge: one envelope crosses the whole
 * width, pulsing each classifier layer in its hue as it passes (cyan rules →
 * violet e5 → green SetFit), clears the amber 0.85 gate, and collapses into a
 * single green verdict glyph at the right edge. Beneath it, a giant `applied`
 * wordmark — stretched across the full width — scramble-decodes as the verdict
 * lands: the page's last image is the inbox resolving into a word.
 *
 * The whole band is a button: click (or Enter/Space) replays the gesture.
 * It plays once when scrolled into view. Reduced-motion renders the resolved
 * end state directly — verdict formed, wordmark decoded, no envelope.
 */

const WORD = "applied";
/** Deterministic pre-decode garble — stable across SSR + first client render. */
const GARBLE = "4pp1_3d";
const GLYPHS = "abcdefghjkmnpqrstuvwxyz0123456789<>·_/";

function ScrambleWordmark({ resolved }: { resolved: boolean }) {
  const [display, setDisplay] = useState(GARBLE);

  useEffect(() => {
    // `resolved` only ever flips false → true within a mount (the Scene is
    // remounted per run, resetting `display` to the garble), so no reset here.
    if (!resolved) return;
    let settled = 0;
    let tick = 0;
    const id = setInterval(() => {
      tick += 1;
      if (tick % 2 === 0) settled += 1;
      if (settled >= WORD.length) {
        setDisplay(WORD);
        clearInterval(id);
        return;
      }
      setDisplay(
        WORD.slice(0, settled) +
          Array.from({ length: WORD.length - settled }, () =>
            GLYPHS.charAt(Math.floor(Math.random() * GLYPHS.length)),
          ).join(""),
      );
    }, 55);
    return () => clearInterval(id);
  }, [resolved]);

  return (
    <text
      className="sig__wordmark font-mono"
      x="600"
      // Baseline rides the band's bottom edge so the descenders bleed off the
      // page — the deliberate AutoML-wordmark clip, in Applied's mono voice.
      y="276"
      textAnchor="middle"
      fontSize="200"
      fontWeight="600"
      textLength="1156"
      lengthAdjust="spacingAndGlyphs"
      fill="currentColor"
      data-resolved={resolved || undefined}
    >
      {display}
    </text>
  );
}

function Scene({ run, reduced }: { run: number; reduced: boolean }) {
  // Keyed by `run` in the parent, so each play remounts it and `landed` resets.
  const [landed, setLanded] = useState(false);

  useEffect(() => {
    if (reduced || run === 0) return;
    const id = setTimeout(() => setLanded(true), 3200);
    return () => clearTimeout(id);
  }, [run, reduced]);

  const cls = reduced ? "sig sig--static" : run > 0 ? "sig sig--play" : "sig";

  return (
    <div className={cls}>
      <svg
        viewBox="0 0 1200 280"
        className="sig__svg block w-full"
        role="img"
        aria-label="An email crosses the three classifier layers left to right, clears the 0.85 gate, and resolves into a single verdict as the applied wordmark decodes."
      >
        {/* the giant wordmark — full width, decodes when the verdict lands */}
        <g style={{ color: "var(--text-dim)" }}>
          <ScrambleWordmark resolved={reduced || landed} />
        </g>

        {/* lane guide — edge to edge */}
        <line
          x1="20"
          y1="64"
          x2="1180"
          y2="64"
          stroke="var(--line-soft)"
          strokeWidth="1"
          strokeDasharray="2 6"
        />

        {/* layer crossings */}
        {[
          { x: 320, color: "var(--viz-rules)", n: "1", label: "rules", d: "0.9s" },
          { x: 560, color: "var(--viz-embeddings)", n: "2", label: "e5", d: "1.55s" },
          { x: 800, color: "var(--viz-setfit)", n: "3", label: "SetFit", d: "2.2s" },
        ].map((b) => (
          <g key={b.label} className="sig__band" style={{ color: b.color, ["--d" as string]: b.d }}>
            <line x1={b.x} y1="24" x2={b.x} y2="104" stroke="currentColor" strokeWidth="1.5" />
            <text x={b.x + 9} y="21" fontSize="10.5" fill="currentColor" className="font-mono">
              {b.n} · {b.label}
            </text>
          </g>
        ))}

        {/* gate */}
        <g className="sig__band sig__gate" style={{ color: "var(--amber)", ["--d" as string]: "2.75s" }}>
          <line
            x1="980"
            y1="24"
            x2="980"
            y2="104"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="5 4"
          />
          <text x="989" y="21" fontSize="10.5" fill="currentColor" className="font-mono">
            0.85 · gate
          </text>
        </g>

        {/* verdict node — the right edge of the lane */}
        <g style={{ color: "var(--viz-setfit)" }}>
          <circle className="sig__glow" cx="1105" cy="64" r="27" fill="currentColor" />
          <circle className="sig__ripple" cx="1105" cy="64" r="19" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <circle className="sig__ring" cx="1105" cy="64" r="19" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <path
            className="sig__check"
            d="M1097 64 L1103 70.5 L1115 56"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        {/* the crossing envelope */}
        <g transform="translate(40 64)">
          <g className="sig__envelope" style={{ color: "var(--text-muted)" }}>
            <rect x="-24" y="-15" width="48" height="30" rx="3.5" fill="var(--surface)" stroke="currentColor" strokeWidth="1.4" />
            <path d="M-24 -13 L0 3 L24 -13" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </g>
        </g>
      </svg>
    </div>
  );
}

export function SignatureEnding() {
  const ref = useRef<HTMLButtonElement>(null);
  const [run, setRun] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const el = ref.current;
    const isReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Deferred a frame so it's never a synchronous effect setState.
    const raf = requestAnimationFrame(() => setReduced(isReduced));
    if (isReduced || !el || typeof IntersectionObserver === "undefined") {
      return () => cancelAnimationFrame(raf);
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setRun((r) => (r === 0 ? 1 : r));
            io.disconnect();
            break;
          }
        }
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, []);

  return (
    <button
      ref={ref}
      type="button"
      onClick={() => setRun((r) => r + 1)}
      className="sig-band block w-full cursor-pointer border-0 bg-transparent p-0 text-left"
      aria-label="Replay the signature ending: one email crosses three layers and one gate and resolves into one verdict."
    >
      <span className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-6 pt-8 pb-4 font-mono text-[11px] text-dim sm:px-10">
        <span className="uppercase tracking-widest">07 · one gesture</span>
        <span>one email · three layers · one gate · one verdict · ↺ click to replay</span>
      </span>
      {/* keyed so a replay cleanly restarts every CSS animation in the scene */}
      <Scene key={run} run={run} reduced={reduced} />
    </button>
  );
}
