"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

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
 * MECHANICS — PIN AND PLAY (2026-08-19, the owner's call, reversing the
 * scrub built earlier the same day). The ending has now failed in both
 * directions, and the history is the spec:
 *
 *   · fired-and-forgotten (an IO sentinel starting a fixed 2.05s timeline in
 *     an unpinned 596px band) outran its runway — fragments for a fast
 *     reader, already-finished for a slow one;
 *   · scrubbed (the playhead written from scroll progress across a pinned
 *     runway) made the ending an artifact the reader has to operate, and the
 *     owner rejected it: the close should PLAY, smooth and flowing, once it
 *     is in view — not advance in lockstep with a trackpad.
 *
 * The reconciliation keeps each fix's half: the band still PINS through a
 * runway (globals.css `.act--runway`), and once the scene is meaningfully on
 * screen (`PLAY_THRESHOLD`) the sequence plays itself to completion on its
 * own clock, slowed (`AUTO_RATE`) — while the pin holds the frame, so the
 * timeline cannot be outrun the way the first build's was. The geometry is
 * what makes the enter-only trigger safe THIS time, and it is worth stating
 * because that trigger is exactly what failed before: the band is the page's
 * last section, its stage releases the pin at the page's end, and only the
 * footer's ~85px lies beyond — so even a reader who flicks straight to max
 * scroll still has the whole scene on screen while it finishes. There is no
 * scroll position from which the play can escape the viewport.
 *
 * The clock drives the SAME frozen-animation machinery the scrub used:
 * `--act-t` is the sequence's own seconds, globals.css pauses every
 * animation and shifts its delay by it. NOT ONE KEYFRAME, DURATION OR DELAY
 * CHANGED — slowing happens in the mapping from real time to `--act-t`, so
 * the authored choreography is untouched and a future retempo is one
 * constant. Once played it stays composed (`forwards` on every fill): the
 * ending is watched once, like the sentence it draws, and scrolling back up
 * finds it finished rather than un-drawing — the reversal belonged to the
 * scrub and left with it.
 *
 * The scene is still a button; click / Enter / Space restarts the clock and
 * plays the same slowed sequence again — one tempo everywhere, rather than
 * an authored-speed replay beside a slowed first play. Reduced motion
 * renders the fully composed end state, and so does the server, so a visitor
 * without JS gets the finished image rather than the empty band the pre-play
 * CSS holds; for both, the runway never grows, so neither is stranded in a
 * screen and a half of scroll with nothing in it. Every stroke carries
 * `pathLength={1}` so drawing is dashoffset 1 → 0 with no runtime
 * getTotalLength(). The wordmark geometry is copied from
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
 * section's `act--play act--scrub` / `act--static` classes and positioned by
 * `--act-t`, so playing, holding and replaying are all the parent's clock
 * moving one custom property — nothing here ever needs to remount.
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

/**
 * The sequence's own length, in seconds — the last animation's delay (the
 * replay hint, 1.55s) plus its duration (0.5s). It is the only number the
 * clock needs: `--act-t` walks from 0 to this, and every keyframe, duration
 * and delay in globals.css stays exactly as authored.
 */
const ACT_SECONDS = 2.05;

/**
 * Authored seconds per real second — the whole of "a bit slower". At 0.55
 * the 2.05s sequence takes ~3.7 real seconds: the wordmark's drawing (0.30
 * to 0.90 authored) spends just over a second under the reader's eyes, and
 * the verdict's fall-and-seat tail keeps enough pace not to read as slow
 * motion. Chosen by watching renders at 0.4, 0.55 and 0.7, not by
 * arithmetic. Slowing lives HERE, in the map from real time to `--act-t` —
 * never in globals.css, whose durations are the authored choreography.
 */
const AUTO_RATE = 0.55;

/**
 * Share of the scene that must be on screen before the play begins. Low
 * enough that a reader who parks with the band half-entered still gets the
 * play (the scene is ~300px tall at 1024, so this is ~105px of it visible);
 * high enough that the sequence cannot burn its opening frames while the
 * scene is still a sliver under the fold.
 */
const PLAY_THRESHOLD = 0.35;

export function ClosingAct() {
  const ref = useRef<HTMLElement>(null);
  /** The scene's box — what the play trigger watches. The BAND is a screen
   *  and a half of runway once grown, so its own intersection ratio says
   *  nothing about whether the drawing is on screen. */
  const sceneBoxRef = useRef<HTMLDivElement>(null);
  /**
   * `static` — the composed end state. The SSR default, so a visitor without
   * JS (or before hydration) gets the finished frame rather than the empty
   * band the pre-play CSS renders; also where reduced motion stays.
   * `auto`   — the play, frozen by the scrub machinery and positioned by
   *            `--act-t` from the component's own slowed clock: 0 while the
   *            reader approaches, then 0 → ACT_SECONDS once the scene is in
   *            view, then held at the end.
   */
  const [mode, setMode] = useState<"static" | "auto">("static");

  /**
   * Whether the band has grown its runway. Set ONCE, alongside the decision
   * to play, and never cleared — the height is what the pin is defined
   * against, and a replay click must not collapse 1500px of section out from
   * under a reader who is looking straight at it.
   *
   * It is a client-only growth, and deliberately so: the server ships the band
   * at content height, so a visitor with no JS, or with reduced motion, gets
   * the composed image in a band the size of its own contents rather than a
   * screen and a half of empty runway they can never spend. The growth is
   * invisible when it happens — the effect only takes this branch if the whole
   * band is still below the fold — and nothing above it moves, so it costs no
   * layout shift a visitor could see.
   */
  const [runway, setRunway] = useState(false);

  /** The clock's pending frame, so a replay restarts it cleanly and unmount
   *  cancels it. */
  const frame = useRef(0);

  /** Walk `--act-t` from 0 to ACT_SECONDS at AUTO_RATE, then stop. The
   *  `forwards` fills hold the composed frame; nothing here needs to. */
  const playFrom = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    cancelAnimationFrame(frame.current);
    const t0 = performance.now();
    const tick = (now: number) => {
      const t = Math.min(ACT_SECONDS, ((now - t0) / 1000) * AUTO_RATE);
      el.style.setProperty("--act-t", `${t.toFixed(3)}s`);
      if (t < ACT_SECONDS) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    const el = ref.current;
    const scene = sceneBoxRef.current;
    if (!el || !scene) return;
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return; // composed, and it stays composed
    }
    // Only take a composed band apart if the reader has not seen it. Winding
    // one that is already on screen at load back to nothing would yank a
    // finished image away under their eyes, which no trigger excuses.
    // Deferred a frame so the effect body never sets state synchronously.
    let io: IntersectionObserver | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      setRunway(true);
      setMode("auto");
      el.style.setProperty("--act-t", "0s");
      if (typeof IntersectionObserver === "undefined") {
        playFrom();
        return;
      }
      // Enter-only BY DESIGN, and safe only because of where the band sits —
      // the docblock's geometry argument. It fires once: the play is watched
      // once and then holds, so there is nothing for a leave branch to do.
      io = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.intersectionRatio >= PLAY_THRESHOLD)) return;
          io?.disconnect();
          playFrom();
        },
        { threshold: PLAY_THRESHOLD },
      );
      io.observe(scene);
    });
    return () => {
      cancelAnimationFrame(raf);
      cancelAnimationFrame(frame.current);
      io?.disconnect();
    };
  }, [playFrom]);

  /** A click plays the same slowed sequence from the top — one tempo
   *  everywhere, restarted by rewinding the clock rather than remounting the
   *  scene (the animations are paused and positioned, so the playhead is the
   *  only thing that has to move). */
  const replay = () => {
    setMode("auto");
    playFrom();
  };

  const state = mode === "static" ? "act--static" : "act--play act--scrub";

  return (
    <section
      ref={ref}
      className={`act act-band relative border-t border-line-soft ${runway ? "act--runway" : ""} ${state}`}
    >
      {/* The stage: the frame the reader watches while the runway above and
          below it scrolls past. It pins (globals.css) only once the band has a
          runway to pin through, and its contents are BOTTOM-aligned, because
          the ending's whole crop is the wordmark's descenders being sliced by
          the band's own bottom edge — that edge has to be the viewport's while
          the scene is on screen, and the footer's hairline the moment the pin
          lets go. */}
      <div className="act__stage">
      {/* the ask — rises once the full stop lands, then holds. Outside the
          keyed scene so a replay never yanks a link out from under a click. */}
      {/* `my-auto` is the pinned frame's composition, not a convenience. The
          stage is a full viewport and the ask + scene fill only part of it —
          at 1024×768, measured on the built page, 316px of surplus — and
          with everything bottom-stacked that surplus pooled ABOVE the ask as
          one unbroken void, while the key sat wedged directly under the CTA
          and read as debris. Auto margins on a flex item absorb free space
          before justify-content does, so they split the surplus around the
          ask instead: held space, the thesis, held space, the scene — a title
          card over the closing image, at every viewport height. It also buys
          the key its air: the gap between the CTA and the rails it annotates
          is now the lower half of that surplus — 158px, not ~20px. (Read
          the surplus off the resolved margins, which is what auto margins in
          a flex column mean: 2 × 158.1 = 316.3. An earlier draft said ~630,
          which is that figure double-counted.)
          In the static band (no JS, reduced motion, pre-hydration) the stage
          is a plain block at content height, vertical auto margins resolve to
          zero, and the shallow pt is the composed image's own spacing — the
          section above already carries py-24. */}
      {/* 85rem: the landing's one gutter (`app/page.tsx`) — the ask lines up
          with the hero it answers. */}
      <div className="my-auto mx-auto w-full max-w-[85rem] px-6 pt-8 sm:pt-10">
        <div className="act__ask">
          {/* steps up at `lg` because that is where the frame gets a 1500px
              runway and the thesis becomes a held title card in open space —
              18px medium reads as a caption at that scale, not a closing
              line. Below `lg` the band is denser and the smaller cut holds. */}
          <p className="text-base font-medium text-strong sm:text-lg lg:text-2xl">{CLOSING.thesis}</p>
          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
            <a
              href={ACCESS.seatHref}
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
      <div ref={sceneBoxRef} className="relative">
        <Key />
        <button
          type="button"
          onClick={replay}
          className="act__scene relative block w-full cursor-pointer border-0 bg-transparent p-0"
          aria-label="Replay the closing sequence: one email crosses the rules layer — the one that ships — and lands as the emerald full stop after the applied wordmark."
        >
          <span aria-hidden className="act__hint absolute right-6 top-1 text-[0.8125rem] text-dim sm:right-10">
            {CLOSING.replay}
          </span>
          <Scene />
        </button>
      </div>
      </div>
    </section>
  );
}
