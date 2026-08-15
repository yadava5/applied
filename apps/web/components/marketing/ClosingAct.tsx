"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { NEW_TAB } from "./chrome";
import { ACCESS, CLOSING, DECISION } from "./copy";

/**
 * The closing act — the page's last image, and its one emphasised ask.
 *
 * The page spends nine screens making a sentence; this band draws the
 * sentence and punctuates it. One envelope enters at the left and crosses
 * the full width — but it meets ONE cyan rail, the rules stage, the figure
 * that ships (`DECISION.rulesF1` — the digits live in copy.ts, and naming
 * the key rather than spelling them out keeps this comment true when the
 * attribution is the thing under discussion) — and then collapses into the
 * emerald verdict, which falls and
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
 *
 * READING ORDER — decided, not incidental (2026-08-15). The composed order
 * is thesis → ask → scene, so the ask sits ABOVE the visual climax. The
 * original brief asked for the reverse (dot lands, line holds, then the
 * ask), and it is honored in TIME — the ask rises at 1.3s, alongside the
 * dot's landing — but it cannot be honored in SPACE: the wordmark's
 * descenders bleed off the page's bottom edge, sliced by the footer's
 * hairline, so the scene must be the band's last element. Nothing can sit
 * below it without destroying that crop. And the spatial order earns its
 * keep: the page ends on the product's name punctuated by the verdict —
 * the more confident close than ending on a button — while the emerald
 * ask, one short glance back up, rhymes with the full stop. Do not "fix"
 * this by moving the ask below the scene.
 *
 * Type in the scene: mono marks the machine value and STOPS at its edge.
 * The F1 figures are mono (read out of the benchmark JSONs); the words
 * beside them — `what ships`, `benchmarked, not shipped` — are captions,
 * set in the product's caps-label voice (`.act__words`, the `.label-caps`
 * device restated for the key).
 *
 * THE KEY IS DOM TEXT, NOT SVG TEXT (2026-08-15). The rail tags used to live
 * inside the scene as `<text>` nodes, and a viewBox scales its contents
 * uniformly: at 375 the 1200-unit scene renders at 0.3125×, so a 10.5-unit
 * figure landed at 3.28px and a 9.75-unit caption at 3.05px. Measured, not
 * eyeballed — `getScreenCTM().a` × the user-unit size, because computed
 * fontSize on an svg node reports user units and reads as if nothing were
 * wrong. It is not a small-screen problem either: at 1024 the same tags
 * measure 8.96px and 8.32px, so the page's central comparison was under any
 * legible floor at every width a visitor actually uses.
 *
 * A font-size bump inside the svg only moves the problem, because the size
 * is a function of the viewport either way. So the words left the drawing:
 * `Key` is real DOM text, absolutely positioned at `lg`+ over the rails it
 * names (the same x the tags used, sitting on the rails' own top edge, in
 * the same colours) and restacked below `lg` into a legend above the scene,
 * where each row carries a mark cut like the rail it stands for. One set of
 * nodes, two arrangements — never a visible copy and a hidden twin.
 *
 * That also settles the accessibility of the claim. The svg is decorative
 * and says so, which was a lie while it held the only statement of the
 * comparison; now the geometry is genuinely all it holds, and the key is a
 * list a screen reader reaches like any other text.
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

/**
 * Where the key sits over the scene at `lg`+, as shares of the viewBox — the
 * x each tag used (369 and 569 of 1200) and the rails' own top edge (y=24 of
 * 370) as the row's bottom, so the words rest on the rails rather than
 * floating above them. Shares, not pixels: the svg is fluid, and these have
 * to track it.
 */
const KEY_LEFT = { rules: "30.75%", ghost: "47.417%" } as const;
const KEY_BOTTOM = "93.514%";

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
          the page's central comparison restaged as furniture. The dashes stay
          quiet (opacity in globals.css, per theme, measured to the 3:1
          non-text floor); what they MEAN is carried by the key, in text a
          visitor can read. */}
      <g className="act__ghosts" stroke="currentColor">
        <line x1="560" y1="24" x2="560" y2="104" strokeWidth="1.5" strokeDasharray="3 5" />
        <line x1="800" y1="24" x2="800" y2="104" strokeWidth="1.5" strokeDasharray="3 5" />
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

/**
 * The scene's key — the whole comparison, in two rows.
 *
 * At `lg`+ each row is absolutely placed on the rail it names, which is the
 * composition the scene was drawn for. Below that the rows have no room to
 * sit side by side (they collide under ~1024), so they stack into a legend
 * above the scene — above, because nothing may sit below it: the wordmark's
 * descenders bleed off the band's bottom edge and that crop is the ending.
 * The stacked rows earn a mark cut like the rail they stand for, solid or
 * dashed, since at that width the rails themselves are 25px ticks.
 */
function Key() {
  return (
    <ul
      className="act__key mx-auto mt-6 flex w-full max-w-6xl flex-col gap-2 px-6 text-[0.8125rem] lg:pointer-events-none lg:absolute lg:inset-0 lg:z-10 lg:mt-0 lg:block lg:max-w-none lg:px-0 lg:text-xs xl:text-[0.8125rem]">
      <li
        className="act__tag act__tag--rules flex items-center gap-2 lg:absolute lg:gap-1.5"
        style={{ left: KEY_LEFT.rules, bottom: KEY_BOTTOM }}
      >
        <span aria-hidden className="act__key-mark inline-block lg:hidden" />
        <span className="tabular font-mono">{DECISION.rulesF1}</span>
        <span aria-hidden>·</span>
        <span className="act__words">{CLOSING.railShips}</span>
      </li>
      <li
        className="act__tag act__tag--ghost flex items-center gap-2 lg:absolute lg:gap-1.5"
        style={{ left: KEY_LEFT.ghost, bottom: KEY_BOTTOM }}
      >
        <span aria-hidden className="act__key-mark act__key-mark--ghost inline-block lg:hidden" />
        <span className="tabular font-mono">{DECISION.cascadeF1}</span>
        <span aria-hidden>·</span>
        <span className="act__words">{CLOSING.railGhost}</span>
      </li>
    </ul>
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
      {/* pt is deliberately shallow: the section above already carries py-24,
          and this band answers it directly — a deep top pad here read as a
          dead gap in front of the page's closing image. */}
      <div className="mx-auto w-full max-w-6xl px-6 pt-8 sm:pt-10">
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

      {/* The key rides over this box at `lg`+, so it is the box the scene's
          own geometry defines: the button is the svg and nothing else, and
          the key's percentage placement lands on the rails it names. Below
          `lg` the key is in flow above the button and the box is both. */}
      <div className="relative">
        <Key />
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
      </div>
    </section>
  );
}
