"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { NEW_TAB } from "./chrome";
import { ACCESS, CLOSING, DECISION } from "./copy";

/**
 * The closing act — the page's last image, and its one emphasised ask.
 *
 * The page spends nine screens making a sentence; this band draws the
 * sentence and punctuates it. One envelope enters at the left and crosses
 * the full width — but it meets ONE cyan rail, the rules, `0.979 · what
 * ships` — and then collapses into the emerald verdict, which falls and
 * seats itself as the full stop after the drawn `applied` wordmark. The
 * email literally finishes the sentence: the thesis line beneath says the
 * inbox already holds the verdict, and the closing image is the mail
 * becoming the punctuation of the product's name.
 *
 * This replaces `SignatureEnding` FOR THIS FAMILY ONLY (the old landing
 * still mounts it): that scene pulsed three layers and an 0.85 gate — the
 * pipeline this page's own argument says lost the benchmark and does not
 * run in the hosted app.
 *
 * Mechanics, all house idiom: one IntersectionObserver sentinel fires the
 * ~1.5s sequence once, it plays out and HOLDS — nothing is scrubbed. The
 * scene is a button; click / Enter / Space remounts it (`key={run}`) and
 * replays. Reduced motion renders the fully composed end state. Every
 * stroke carries `pathLength={1}` so drawing is dashoffset 1 → 0 with no
 * runtime getTotalLength(). The wordmark geometry is copied from
 * `components/brand/Logo.tsx` (keep in sync) and scaled uniformly — never
 * stretched — with the stroke weight re-chosen for display size: optical
 * weight is a size decision, and the 24px lockup's stroke does not survive
 * a 10× scale-up unexamined.
 */

/* ---- scene geometry (viewBox 0 0 1200 370) ------------------------------ */
/** Wordmark scale-up: lockup units → scene units. */
const K = 10.4;
/** Puts the wordmark's left edge (lockup x=64) at scene x≈24. */
const TX = -641.8;
/** Puts the baseline (lockup y=30.5) at scene y=330; the 370-tall viewBox
 *  then crops the descenders at ~64% — they bleed off the page's bottom
 *  edge, sliced by the footer's hairline. */
const TY = 12.8;
/** Stroke weight at display size, in lockup units. The 24px lockup uses 3;
 *  at ~115px x-height that ratio reads heavy and toy-like, so the display
 *  cut is lighter. Chosen by rendering, not arithmetic. */
const STROKE = 2;
/** The verdict / full stop. cx = K·172 + TX — the corridor right of the
 *  `d` is clear of letterforms, so the drop crosses nothing. */
const DOT_X = 1147;
const DOT_R = 19.4;
/** Lane (y=64) → baseline seat (y=335.2). Mirrored in the CSS keyframes. */
const DOT_SEAT_Y = 335.2;

const at = (d: string): CSSProperties => ({ ["--d" as string]: d });

/**
 * Stateless on purpose: the whole choreography is CSS driven by the
 * section's `act--play` / `act--static` class, and the parent remounts this
 * per run (`key={run}`) so a replay restarts every animation cleanly.
 */
function Scene() {
  return (
    <svg
      viewBox="0 0 1200 370"
      className="block h-auto w-full"
      aria-hidden="true"
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* lane guide — the whole journey, edge to seat */}
      <line
        className="act__guide"
        x1="24"
        y1="64"
        x2={DOT_X}
        y2="64"
        stroke="var(--line)"
        strokeWidth="1"
        strokeDasharray="2 6"
      />

      {/* the neural layers, as ghosts: present, benchmarked, not shipped.
          Dashed, achromatic, and the envelope crosses them without an event —
          the page's central comparison restaged as furniture. */}
      <g className="act__ghosts" stroke="currentColor">
        <line x1="560" y1="24" x2="560" y2="104" strokeWidth="1.5" strokeDasharray="3 5" />
        <line x1="800" y1="24" x2="800" y2="104" strokeWidth="1.5" strokeDasharray="3 5" />
        <text x="569" y="21" fontSize="10.5" fill="currentColor" stroke="none" className="font-mono">
          {DECISION.cascadeF1} · benchmarked, not shipped
        </text>
      </g>

      {/* the one rail — the rules, the layer that ships */}
      <g className="act__rules">
        <line
          className="act__draw act__rail"
          style={at("0.02s")}
          x1="360"
          y1="24"
          x2="360"
          y2="104"
          pathLength={1}
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <text x="369" y="21" fontSize="10.5" fill="currentColor" className="act__tag font-mono">
          {DECISION.rulesF1} · what ships
        </text>
      </g>

      {/* the wordmark, drawn in the brand's own stroke paths (Logo.tsx) */}
      <g className="act__word" transform={`translate(${TX} ${TY}) scale(${K})`}>
        <g
          fill="none"
          stroke="currentColor"
          strokeWidth={STROKE}
          strokeLinecap="butt"
          strokeLinejoin="miter"
          transform="translate(0,10.5)"
        >
          <g className="act__draw" style={at("0.04s")} transform="translate(64,0)">
            <path pathLength={1} d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5" />
            <path pathLength={1} d="M10.85,7 L10.85,20" />
          </g>
          <g className="act__draw" style={at("0.12s")} transform="translate(79,0)">
            <path pathLength={1} d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5" />
            <path pathLength={1} d="M0.15,7 L0.15,26" />
          </g>
          <g className="act__draw" style={at("0.2s")} transform="translate(94,0)">
            <path pathLength={1} d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5" />
            <path pathLength={1} d="M0.15,7 L0.15,26" />
          </g>
          <g className="act__draw" style={at("0.28s")} transform="translate(111.8,0)">
            <path pathLength={1} d="M1.8,0 L1.8,16.4 A3.6,3.6 0 0 0 5.4,20" />
          </g>
          <g className="act__draw" style={at("0.34s")} transform="translate(127.9,0)">
            <path pathLength={1} d="M1.6,7 L1.6,20" />
          </g>
          {/* the i-dot is a fill — dashoffset cannot draw it, so it pops */}
          <circle
            className="act__pop"
            style={at("0.42s")}
            cx="129.5"
            cy="2.7"
            r="1.4"
            fill="currentColor"
            stroke="none"
          />
          <g className="act__draw" style={at("0.42s")} transform="translate(139,0)">
            <path pathLength={1} d="M0.28,12.1 L10.72,12.1 A5.35,6.5 0 1 0 8.57,18.82" />
          </g>
          <g className="act__draw" style={at("0.5s")} transform="translate(154,0)">
            <path pathLength={1} d="M10.85,13.5 A5.35,6.5 0 1 0 0.15,13.5 A5.35,6.5 0 1 0 10.85,13.5" />
            <path pathLength={1} d="M10.85,0 L10.85,20" />
          </g>
        </g>
      </g>

      {/* the verdict — what the envelope becomes; falls and seats itself as
          the sentence's full stop. A fill, so it enters by opacity + scale. */}
      <circle className="act__dot" cx={DOT_X} cy="64" r={DOT_R} fill="var(--viz-setfit)" />
      <circle
        className="act__ripple"
        cx={DOT_X}
        cy={DOT_SEAT_Y}
        r="24"
        fill="none"
        stroke="var(--viz-setfit)"
        strokeWidth="2"
      />

      {/* the protagonist */}
      <g transform="translate(0 64)">
        <g className="act__travel">
          <g className="act__envelope" style={{ color: "var(--text-muted)" }}>
            <rect
              x="-24"
              y="-15"
              width="48"
              height="30"
              rx="3.5"
              fill="var(--surface)"
              stroke="currentColor"
              strokeWidth="1.4"
            />
            <path d="M-24 -13 L0 3 L24 -13" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </g>
        </g>
      </g>
    </svg>
  );
}

export function ClosingAct() {
  const ref = useRef<HTMLElement>(null);
  const [run, setRun] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const el = ref.current;
    const isReduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Deferred a frame so it's never a synchronous effect setState.
    const raf = requestAnimationFrame(() => setReduced(isReduced));
    if (isReduced || !el) return () => cancelAnimationFrame(raf);
    if (typeof IntersectionObserver === "undefined") {
      // No observer, no sentinel — play on load rather than hold a blank band.
      const fallback = requestAnimationFrame(() => setRun((r) => (r === 0 ? 1 : r)));
      return () => {
        cancelAnimationFrame(raf);
        cancelAnimationFrame(fallback);
      };
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

  const state = reduced ? "act--static" : run > 0 ? "act--play" : "";

  return (
    <section ref={ref} className={`act act-band relative border-t border-line-soft ${state}`}>
      {/* the ask — rises once the full stop lands, then holds. Outside the
          keyed scene so a replay never yanks a link out from under a click. */}
      <div className="mx-auto w-full max-w-6xl px-6 pt-16 sm:pt-20">
        <div className="act__ask">
          <p className="text-base font-medium text-strong sm:text-lg">{CLOSING.thesis}</p>
          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
            <a
              href={`mailto:${ACCESS.contact}`}
              className="act-cta inline-flex min-h-11 items-center rounded-lg px-6 py-2.5 font-medium"
            >
              {CLOSING.seatCta} <span aria-hidden className="ml-2">→</span>
            </a>
            <a
              href="/import"
              {...NEW_TAB}
              className="text-sm text-muted underline-offset-4 transition-colors hover:text-strong hover:underline"
            >
              {CLOSING.importAside}
            </a>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setRun((r) => r + 1)}
        className="act__scene relative block w-full cursor-pointer border-0 bg-transparent p-0"
        aria-label="Replay the closing sequence: one email crosses the rules layer — the one that ships — and lands as the emerald full stop after the applied wordmark."
      >
        <span aria-hidden className="act__hint absolute right-6 top-1 text-[0.8125rem] text-dim sm:right-10">
          {CLOSING.replay}
        </span>
        {/* keyed so a replay cleanly restarts every CSS animation in the scene */}
        <Scene key={run} />
      </button>
    </section>
  );
}
