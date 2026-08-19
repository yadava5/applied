"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { NEW_TAB } from "./chrome";
import { trackProgress } from "./scrub";
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
 * MECHANICS — rebuilt 2026-08-19, and this is the part that changed. The
 * sequence used to be fired once by an IntersectionObserver at threshold 0.3
 * and then ran on its own clock for 2.05s. Measured on the deployed preview
 * at the page's bottom: ~700px of black with five unreadable white fragments
 * in it, composing into the finished frame four seconds later. Scroll past
 * slowly and it had already finished; scroll past quickly and it was
 * fragments. The wordmark never assembled for anyone, which is the page's
 * whole payoff shot.
 *
 * It is bound to the scroll now, exactly as the window act is: `--act-t` is
 * the sequence's own clock in seconds, written from the band's scroll progress across
 * the band's entrance, and globals.css freezes every animation and shifts its
 * delay by it. NOT ONE KEYFRAME, DURATION OR DELAY CHANGED — the composed
 * frame is the approved one, and so is every frame on the way to it; what
 * changed is who owns the playhead. Scrolling back up un-draws it.
 *
 * The scene is still a button; click / Enter / Space remounts it (`key={run}`)
 * and plays the authored 2.05s sequence at its authored tempo, after which
 * the scrub stands down for the visit — the reader has taken the wheel, the
 * same rule the window act's camera follows. Reduced motion renders the fully
 * composed end state, and so does the server, so a visitor without JS gets
 * the finished image rather than the empty band the pre-play CSS holds. Every
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

/**
 * The sequence's own length, in seconds — the last animation's delay (the
 * replay hint, 1.55s) plus its duration (0.5s). It is the only number the
 * scrub needs: `--act-t` walks from 0 to this, and every keyframe, duration
 * and delay in globals.css stays exactly as authored.
 */
const ACT_SECONDS = 2.05;

/**
 * The playhead's map, and it is now derived from the sequence rather than
 * guessed at: `ACT_BEATS` are the seconds at which globals.css finishes one
 * kind of thing and starts another, and `ACT_STOPS` is the share of the
 * runway each of those spans is given.
 *
 *   0.00 → 0.32s   the scene arrives: the lane, the two ghost rails, the
 *                  cyan rail, the key. The boundary is the rail's own
 *                  completed draw — its 0.02s start plus its 0.3s duration —
 *                  the moment the comparison stands. This span wants very
 *                  little scroll, but it cannot have none, or the pinned
 *                  frame opens on a black screen.
 *   0.32 → 0.90s   the wordmark draws. Eight staggered strokes, the last
 *                  starting at 0.5s and taking 0.4s, and the envelope
 *                  crossing the full width underneath them. THIS IS THE
 *                  SHOT, and it gets the majority of the runway.
 *   0.90 → 2.05s   the verdict falls and seats, the ripple, the ask, the
 *                  replay hint. Single gestures; they read at speed.
 *
 * EVERY BEAT IS DERIVED, NOT TRANSCRIBED (2026-08-19; the middle beat moved
 * 0.3 → 0.32 to make that literally true — 20ms of playhead map, invisible
 * at any scroll position). Beat 1 is the rail's `--d` plus its draw duration;
 * beat 2 is the last stroke's `--d` plus the shared draw duration (0.5 + 0.4);
 * `ACT_SECONDS` is the replay hint's delay plus its duration (1.55 + 0.5).
 * `tests/unit/closing-act-tempo.test.mjs` recomputes all three from
 * globals.css and this file's `at(...)` delays and fails on any drift, either
 * direction — retiming the CSS without moving these constants no longer
 * silently unmaps the playhead.
 *
 * WHY THIS REPLACED `t = total · p²`. The square curve was written to buy the
 * drawing more runway than a linear scrub gave it, and it did — but it buys
 * that at the START of the range, which is where the scene's own entrance
 * lives. Measured on the pinned band at 1024×768: it put t = 0.15s (the first
 * frame with anything legible in it) 537px into the runway, so the pin
 * engaged on a full viewport of black and stayed that way for two thirds of a
 * screen. That is the defect the whole rebuild exists to remove, reintroduced
 * at a different scroll position. A piecewise map spends the runway on the
 * events instead of on the clock: the scene is up by 150px and the drawing
 * owns 870 of the 1500.
 *
 * Nothing about the sequence changes — this is how fast the playhead moves,
 * which is the one thing a scrub is allowed to own. If a delay or duration in
 * globals.css moves, the boundaries here move with it.
 */
const ACT_BEATS = [0, 0.32, 0.9] as const;
const ACT_STOPS = [0, 0.1, 0.68] as const;

/**
 * The band's own traversal, which for a pinned section IS the pinned runway:
 * 0 when its top reaches the viewport's top (the pin engages), 1 when its
 * bottom reaches the viewport's bottom (the pin releases). The same window
 * the act uses, and for the same reason.
 *
 * THE RUNWAY IS THE FIX, and the arithmetic is exact rather than approximate.
 * `trackProgress` divides by `height − to·vh + from·vh`, which with this
 * window is `height − vh`; the band's height is `calc(100vh + --closing-runway)`
 * (globals.css), so the divisor is the runway EXACTLY, at every viewport
 * height, with no residue to argue about.
 *
 * What it buys, measured against what shipped. The band used to be 596px tall
 * and unpinned, scrubbed over `{ from: 1, to: 1 }` — 596px of scroll for a
 * 2.050s sequence, which is 0.4s at a 1500px/s flick, against the window
 * act's 3572px for a comparable timeline. That ratio is why the ending was
 * still "too fast to see" after it was bound to the scroll: binding was
 * necessary and not sufficient, because the runway was six times too short.
 * At the `lg` runway the same sequence spends 1500px, and the wordmark's
 * drawing — the payoff shot, 0.30s to 0.90s of the 2.05s — spends 870 of them
 * (see `ACT_STOPS`). It was 258px.
 *
 * Upper bound reachable, which is the property that actually has to hold: the
 * band is followed by the footer, so its bottom clears the viewport's bottom
 * with the footer's own height to spare and the progress CLAMPS at 1 rather
 * than asymptoting to it. `landing-b.spec.ts` reads the playhead at max scroll
 * and expects 2.05.
 */
const CLOSING_WINDOW = { from: 0, to: 1 };

/** Walk `ACT_STOPS` → `ACT_BEATS`, linearly inside each span. */
function position(el: HTMLElement | null, progress: number) {
  if (!el) return;
  const p = Math.min(1, Math.max(0, progress));
  let t = ACT_SECONDS;
  for (let i = 1; i <= ACT_STOPS.length; i += 1) {
    const from = ACT_STOPS[i - 1];
    const to = ACT_STOPS[i] ?? 1;
    if (p > to) continue;
    const beatFrom = ACT_BEATS[i - 1];
    const beatTo = ACT_BEATS[i] ?? ACT_SECONDS;
    t = beatFrom + ((p - from) / (to - from)) * (beatTo - beatFrom);
    break;
  }
  el.style.setProperty("--act-t", `${t.toFixed(3)}s`);
}

export function ClosingAct() {
  const ref = useRef<HTMLElement>(null);
  const [run, setRun] = useState(0);
  /**
   * `static` — the composed end state. The SSR default, so a visitor without
   * JS (or before hydration) gets the finished frame rather than the empty
   * band the pre-play CSS renders; also where reduced motion stays.
   * `scrub`  — the same play, frozen, positioned by `--act-t` from the
   *            reader's own descent.
   * `play`   — the authored 2.05s sequence, running. Only a click gets here.
   */
  const [mode, setMode] = useState<"static" | "scrub" | "play">("static");

  /**
   * Whether the band has grown its runway. Set ONCE, alongside the decision to
   * scrub, and never cleared — the height is what the pin and the scrub
   * arithmetic are both defined against, and a replay click (`mode: "play"`)
   * must not collapse 1500px of section out from under a reader who is looking
   * straight at it.
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

  /** False the moment the reader takes the wheel: a click plays the authored
   *  sequence at its authored tempo and the scrub stands down for the visit. */
  const scrubbing = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return; // composed, and it stays composed
    }
    // Only take a composed band apart if the reader has not seen it. Scrubbing
    // one that is already on screen at load would yank a finished image back
    // to nothing under their eyes, which no amount of scroll binding excuses.
    // Deferred a frame so the effect body never sets state synchronously.
    let stop: (() => void) | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      scrubbing.current = true;
      setRunway(true);
      setMode("scrub");
      stop = trackProgress(el, CLOSING_WINDOW, (progress) => {
        if (scrubbing.current) position(el, progress);
      });
    });
    return () => {
      cancelAnimationFrame(raf);
      stop?.();
    };
  }, []);

  /** The reader takes the wheel. A click plays the authored sequence at its
   *  authored tempo and leaves it composed — the scrub stands down for the
   *  rest of the visit, the same rule the window act's camera follows once a
   *  visitor opens a card themselves. */
  const replay = () => {
    scrubbing.current = false;
    ref.current?.style.removeProperty("--act-t");
    setMode("play");
    setRun((r) => r + 1);
  };

  const state =
    mode === "static" ? "act--static" : mode === "scrub" ? "act--play act--scrub" : "act--play";

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
          at 1024×768, measured on the built page, ~630px of surplus — and
          with everything bottom-stacked that surplus pooled ABOVE the ask as
          one unbroken void, while the key sat wedged directly under the CTA
          and read as debris. Auto margins on a flex item absorb free space
          before justify-content does, so they split the surplus around the
          ask instead: held space, the thesis, held space, the scene — a title
          card over the closing image, at every viewport height. It also buys
          the key its air: the gap between the CTA and the rails it annotates
          is now the lower half of that surplus, not ~20px.
          In the static band (no JS, reduced motion, pre-hydration) the stage
          is a plain block at content height, vertical auto margins resolve to
          zero, and the shallow pt is the composed image's own spacing — the
          section above already carries py-24. */}
      <div className="my-auto mx-auto w-full max-w-6xl px-6 pt-8 sm:pt-10">
        <div className="act__ask">
          {/* steps up at `lg` because that is where the frame gets a 1500px
              runway and the thesis becomes a held title card in open space —
              18px medium reads as a caption at that scale, not a closing
              line. Below `lg` the band is denser and the smaller cut holds. */}
          <p className="text-base font-medium text-strong sm:text-lg lg:text-2xl">{CLOSING.thesis}</p>
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
          onClick={replay}
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
      </div>
    </section>
  );
}
