"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, HELD, HELD_TAKE, KEPT, PRIVACY, REVIEW, ROW } from "./copy";
import { CLIPS } from "./footage";
import { HeldExhibit } from "./HeldExhibit";
import { ProductClip } from "./ProductClip";
import { RailTake, type RailBeat } from "./RailTake";
import { latch, trackProgress } from "./scrub";
import { VerdictEmail, type VerdictStage } from "./VerdictEmail";
import { VerdictTally } from "./VerdictTally";

/**
 * The descent: one claim per screen, with an exhibit riding alongside on a
 * pinned rail. The SAME copy the other variants render as sections —
 * imported from `copy.ts`, restaged, never rewritten — plus the claims only
 * this staging can make, because they are demonstrated rather than asserted.
 *
 * THE SECTION IS THE PAGE'S SPINE, AND THE SPINE ALTERNATES. Five rails now
 * (the owner's call, 2026-08-20: "five or six boxes aside from the oner",
 * sides alternating), between the two full-frame bookends:
 *
 *   window act (full frame: the workday oner, 01a) →
 *   verdict    (RIGHT rail: the email as a TAKE — raw → split → dissolve →
 *               the kept record, the owner's 02b pick) →
 *   rules      (LEFT rail: the rules recording, promoted from an in-flow
 *               figure to its own beat — and the page's one BIG box) →
 *   review     (RIGHT rail: the held mail settling into the review queue as
 *               a TAKE — the owner's 08c pick) →
 *   row        (LEFT rail: the tracked "ride the letter" recording, 03c-i —
 *               the hero's "Applied moves the row for you", on camera) →
 *   retention  (RIGHT rail: the sync recording; the kept record enacts its
 *               collapse in the flow) →
 *   access (no rail) → closing act (full frame).
 *
 * THE RAILS RUN AS TAKES, NOT AS SCRUBS — and that supersedes, by the
 * owner's explicit and repeated direction, the principle an earlier build
 * enforced here ("every rail state is a function of scroll position and
 * reverses by construction"). He chose 02b and 08c off the motion lab WHERE
 * THEY RAN AS TAKES — narrated, autoplaying, pausable — and the rebuild
 * that turned them into reversible scroll states discarded the thing he
 * picked, twice. The precedent is his own and already on this page: both
 * bookends pin and PLAY. The rails now do the same (`RailTake`), and scroll
 * holds exactly the jobs a band can honestly hold over a clock it does not
 * drive: the take starts at the pin, freezes when the rail leaves the
 * viewport (nothing finishes unwatched), compresses under a governor when
 * the visitor outpaces it so the beats land while the rail still holds, and
 * composes its ending if even that is outrun — never a scrub. The flow exhibits
 * (the benchmark draw, the kept record's collapse) remain scroll-driven:
 * they sit IN the reading column, where the reader's own descent is the
 * honest clock.
 *
 * Which exhibit rides which rail is decided by what it DOES: the two
 * artifacts that act out a story ride the take rails; the recordings — which
 * loop, and carry their own transport (`ProductClip`) — ride the constant
 * rails. Below `lg` stickiness would fight the reading flow, so each screen
 * carries an inline snapshot of its artifact at a legible state — a layout
 * decision, not a fallback.
 *
 * SIZING (the owner's second edit, 2026-08-20 — "we have that much of space,
 * use it"): THE WHOLE SPREAD IS FLUID between the two widths he works at.
 * The first sizing round fixed one box at 36rem and left 350px of dead
 * margin at 1512 (`max-w-6xl` capped the grid at 1152 and simply stopped);
 * this round scales the composition instead of one number in it. Three vars
 * on the section, all linear in vw from the SAME 1024 geometry the fold and
 * pin gates were measured against, so 1024 renders byte-identical to the
 * gated build and every wider window gets the same composition, larger:
 *
 *   --rail      30rem at 1024 → 40rem at 1512+ (the four standard rails).
 *               40rem is the honest ceiling for the clip rails: the encodes
 *               are 1152 physical px wide, so 640 CSS px on a 2x screen is a
 *               1.11x upscale — the width `ProductClip` already argued sharp
 *               for the in-flow figure — and past it the recording starts
 *               being pixels the camera never captured.
 *   --rail-big  36rem at 1024 → 44rem at 1512+, AND capped against the
 *               viewport's height: the rules exhibit pins at 5rem with py-6,
 *               so its foot — the transport, which WCAG 2.2.2 says must stay
 *               reachable — clears a fold H only while the exhibit is under
 *               H − 8rem. Inverted through the exhibit formula below (chrome
 *               139.3px at xl, an 8px margin kept), that is width ≤
 *               (100dvh − 17.25rem) × 1152/630; at 600 tall it holds the box
 *               to ~592px (still past the old 576, foot 9.7px clear —
 *               measured), and above ~660 tall the vw term is the binding
 *               one. 44rem (704 CSS, 1.22x on a 2x screen) is this clip's
 *               ceiling rather than 40rem because it is the page's one BIG
 *               box and the one whose 11–14px recorded product type the
 *               owner twice called illegible; the extra scale buys
 *               legibility everywhere and costs sharpness only on 2x
 *               screens, mildly, in motion — a 1x screen still downscales.
 *   --measure   26rem at 1024 → 30rem at 1512+, with the body size running
 *               0.9375rem → 1.0625rem on the same ramp (`Claim`). The prose
 *               grows ~13% while the exhibits grow ~33%: the owner's
 *               hierarchy — the exhibits are the page; the prose annotates —
 *               gets STRONGER with width, not renegotiated.
 *
 * The ramps are (w − 1024)/(1512 − 1024) restated as vw + a px intercept,
 * clamped at both ends: below 1024 the grid is single-column anyway, and
 * past 1512 the composition holds its 1512 form inside the page's 85rem
 * gutter (`app/page.tsx` says why the container caps there). This is what
 * "it runs at the best zoom for everyone" honestly means: the page fits
 * ITSELF to the window across the whole design range — it never touches
 * `transform`, never rasterizes text, and never overrides the visitor's own
 * browser zoom, which stays theirs.
 */

/**
 * Half-width of the deadband around the retention mark, as a share of the
 * exhibit's own window. Guards a crossfade between two states of a diagram;
 * chatter here costs nothing but would still look nervous.
 */
const STAGE_DEADBAND = 0.03;

/**
 * The benchmark ladder's own window: 0 as the figure's top enters from the
 * foot of the viewport, 1 once its bottom is comfortably above the middle. The
 * bars draw across that, so the decision claim's exhibit arrives WITH the
 * reader instead of sitting there already finished. See `BenchmarkFigure` for
 * why both bars run on one clock and why the default is the composed figure.
 */
const BENCH_WINDOW = { from: 0.95, to: 0.55 };

/**
 * The retention exhibit's window and mark. The claim is "read in flight, never
 * kept", and this is the one exhibit on the page that can ENACT it under the
 * reader's own scroll: the email arrives whole, and as the reader crosses the
 * paragraph that says the body is discarded, the body is discarded.
 *
 * Measured against the EXHIBIT rather than the claim block, so the collapse
 * cannot happen while the thing collapsing is off screen. `from` above `to` is
 * legal and deliberate: `trackProgress`'s span is `height + (from − to)·vh`,
 * which stays positive, and it puts both endpoints inside the exhibit's own
 * visible traversal.
 */
const RETENTION_WINDOW = { from: 0.8, to: 0.35 };
const RETENTION_MARK = 0.5;

/**
 * The rails' entrance window: `{ from: 1, to: 1 }` — from the box touching
 * the fold to fully in frame, the closing band's own grammar (`scrub.ts`
 * derives it). Chosen over a mid-viewport window because the two take rails
 * are viewport-tall flex boxes whose content centres itself: a window that
 * ends deeper than the fold is unreachable for them once the pin holds, and
 * an exhibit stuck at 99% scale forever is exactly the kind of quiet defect
 * this page keeps having to measure for.
 */
const RAIL_ZOOM_WINDOW = { from: 1, to: 1 };

/** Where the dolly starts. 0.9 is a real arrival — visible at a glance,
 *  finished by the time the box is whole in frame — without ever reading as
 *  an effect layered on the exhibit: the box scales as ONE object, chrome
 *  and all, the way a camera closes on a subject. */
const RAIL_ZOOM_FROM = 0.9;

/**
 * THE CINEMATIC ZOOM LIVES HERE NOW — the owner's call, twice over
 * (2026-08-21): the oner plays at natural size with no zoom at all
 * (`OnerStage`), and "the zoom was for boxes, when we scroll through them,
 * which are five of them". So each of the spine's five rails arrives on a
 * dolly-in: the box enters the fold at 0.9 of its size and closes to 1 as
 * the reader scrolls it into frame, driven by scroll POSITION — reversible
 * by construction, which is what makes it honest for a rail (the exhibits'
 * own stories stay takes and clips; this is only the camera picking the box
 * up). It completes before the rail pins, so the pinned exhibit — the state
 * every geometry gate on this page measures — renders untransformed.
 *
 * Deliberately NOT a drift: past the entrance the transform is removed
 * outright, so the exhibit's text and footage render crisp at rest and
 * nothing keeps rasterizing under a live transform. Reduced motion never
 * arms it, and a box already on screen at load is never taken apart — the
 * same two rules every driven exhibit on this page follows.
 */
function RailZoom({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let stop: (() => void) | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      el.style.willChange = "transform";
      stop = trackProgress(el, RAIL_ZOOM_WINDOW, (progress) => {
        if (progress >= 1) {
          el.style.transform = "";
          el.style.willChange = "";
          return;
        }
        el.style.willChange = "transform";
        const eased = 1 - Math.pow(1 - progress, 3);
        const scale = RAIL_ZOOM_FROM + (1 - RAIL_ZOOM_FROM) * eased;
        el.style.transform = `scale(${scale.toFixed(4)})`;
      });
    });
    return () => {
      cancelAnimationFrame(raf);
      stop?.();
      el.style.transform = "";
      el.style.willChange = "";
    };
  }, []);
  return (
    <div ref={ref} style={{ transformOrigin: "50% 50%" }}>
      {children}
    </div>
  );
}

function Claim({
  eyebrow,
  headline,
  label,
  children,
  inline,
  continued,
  paced = true,
}: {
  eyebrow?: string;
  headline?: string;
  /** The artifact's wall label — rendered below `lg`, where the artifact is
   *  inline and has no sticky column to be labelled in. */
  label?: string;
  children: React.ReactNode;
  /** The below-`lg` artifact snapshot for this screen, when it has one. */
  inline?: React.ReactNode;
  /** A micro-beat of the claim above it: no eyebrow, no headline of its own,
   *  and shorter, because it carries one paragraph and a change of state
   *  rather than a new argument. */
  continued?: boolean;
  /**
   * Whether this claim is PACED — held to most of a viewport and centred in
   * it. True only where a claim is paired with a rail exhibit, which is what
   * the pacing exists for: the flow column is the rail's runway (sticky can
   * only travel inside its containing block), and a dvh-paced band is what
   * keeps the pin share stable as viewports grow tall — the measured failure
   * that argument comes from is in the pin walk's tall corners.
   */
  paced?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col",
        paced
          ? cn("justify-center py-16", continued ? "min-h-[60vh]" : "min-h-[80vh]")
          : "py-20",
      )}
    >
      {eyebrow && <p className="label-caps mb-4">{eyebrow}</p>}
      {headline && (
        <h2 className="max-w-xl text-balance text-2xl font-medium tracking-tight text-strong sm:text-3xl xl:text-4xl">
          {headline}
        </h2>
      )}
      {/* The owner's sizing edit (2026-08-20): the scrolling text steps DOWN
          from the exhibits — 0.9375rem on a 26rem measure at 1024, riding the
          section's fluid ramp to 1.0625rem on 30rem at 1512+ (the section
          docblock derives it). The exhibits are the page; the prose
          annotates, at every width. */}
      <div
        className={cn(
          "max-w-[var(--measure)] space-y-4 text-[length:clamp(0.9375rem,0.41vw_+_0.675rem,1.0625rem)] leading-relaxed text-muted",
          headline && "mt-5",
        )}
      >
        {children}
      </div>
      {inline && (
        <div className="mt-8 lg:hidden">
          {label && <p className="label-caps mb-2">{label}</p>}
          {inline}
        </div>
      )}
    </div>
  );
}

/**
 * The benchmark ladder, drawn under the reader's own descent.
 *
 * The figure itself is untouched and still server-renders complete: what this
 * adds is a `--bench` on its wrapper, which `BenchmarkFigure`'s bars read as
 * `scaleX(var(--bench, 1))`. Nobody driving means the composed figure, so
 * reduced motion, no JS and every other consumer of the figure get exactly
 * what they got before.
 *
 * Linear, not eased: what is growing is a length on a measured axis, and the
 * numeral beside each bar is static text stating the true value the whole
 * time. It refuses to take apart a figure that is already on screen at load,
 * the same rule the closing act follows.
 */
function DrawnBenchmark() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let stop: (() => void) | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      el.style.setProperty("--bench", "0");
      stop = trackProgress(el, BENCH_WINDOW, (progress) => {
        el.style.setProperty("--bench", progress.toFixed(4));
      });
    });
    return () => {
      cancelAnimationFrame(raf);
      stop?.();
    };
  }, []);
  return (
    <div ref={ref}>
      <BenchmarkFigure />
    </div>
  );
}

export function ClaimsDescent() {
  /**
   * The verdict rail's ladder — the owner's 02b pick ("what it kept"), run
   * as the TAKE he picked it as:
   *
   *   0 raw       the mail as Gmail hands it over;
   *   1 split     the two verdicts disagree AND the deciding phrases light —
   *               the lit spans are the winning verdict's own evidence
   *               (`traceEvidence`), so the chips and their cause land as
   *               one beat;
   *   2 dissolve  every sentence the walk never matched fades to a residue —
   *               Applied's copy, never the visitor's Gmail;
   *   3 retained  the lit phrases go too and the kept record rises: even the
   *               deciding phrase is read and used, never stored.
   *
   * The INITIAL state is `split` — the resting exhibit for SSR, no-JS and
   * reduced motion is the disagreement itself, the most demonstrative still
   * the ladder holds — and the take's first beat winds it back to `raw` so
   * a watching visitor gets the story in order.
   */
  const [verdictStage, setVerdictStage] = useState(1);
  const VERDICT_STAGES: readonly VerdictStage[] = ["raw", "split", "dissolve", "retained"];

  const verdictBeats = useMemo<readonly RailBeat[]>(
    () => [
      { enter: () => setVerdictStage(0), line: KEPT.narration[0], hold: 3000 },
      { enter: () => setVerdictStage(1), line: KEPT.narration[1], hold: 3800 },
      { enter: () => setVerdictStage(2), line: KEPT.narration[2], hold: 2800 },
      { enter: () => setVerdictStage(3), line: KEPT.narration[3], hold: 800 },
    ],
    [],
  );

  /**
   * The held rail's two beats — the owner's 08c pick ("where it waits"), as
   * its lab take: Cedar's note alone, then its settle into the real review
   * queue. Rests settled (the queue is the truth a non-watching visitor
   * needs); the take winds it back.
   */
  const [settled, setSettled] = useState(true);
  const heldBeats = useMemo<readonly RailBeat[]>(
    () => [
      { enter: () => setSettled(false), line: HELD_TAKE.narration[0], hold: 2600 },
      { enter: () => setSettled(true), line: HELD_TAKE.narration[1], hold: 3000 },
      // The gate line is a beat of its own — no state change, the settled
      // queue is the image it narrates over.
      { enter: () => {}, line: HELD_TAKE.narration[2], hold: 800 },
    ],
    [],
  );

  /**
   * The retention flow exhibit's stage. `true` — the record — is the SSR
   * default and where reduced motion stays, so a visitor who is never going
   * to see the collapse gets its result rather than its setup. The scrub
   * only takes the exhibit apart if the reader has not already seen it, the
   * same rule the closing act follows.
   */
  const keptRef = useRef<HTMLDivElement>(null);
  const [kept, setKept] = useState(true);
  useEffect(() => {
    const el = keptRef.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let stop: (() => void) | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      setKept(false);
      stop = trackProgress(el, RETENTION_WINDOW, (progress) => {
        setKept((prev) => latch(progress, RETENTION_MARK, prev, STAGE_DEADBAND));
      });
    });
    return () => {
      cancelAnimationFrame(raf);
      stop?.();
    };
  }, []);

  return (
    /* The fluid spread's three vars — the section docblock derives every
       number. Slopes are (target − base)/(1512 − 1024) as vw with a px
       intercept, chosen so 1024 lands EXACTLY on the geometry the fold and
       pin gates were measured against. `--rail-big`'s min() term is the
       fold fit: the transport at the frame's foot must clear a 100dvh fold
       from a 5rem pin with py-6 — see the sizing paragraph. */
    /* `--rail-row` is the row rail's own width since the big-box restaging
       (2026-08-21): same ramp as `--rail-big`, but its fold cap multiplies by
       1152/864 = 1.3333 — the ratio of the 4:3 `one-letter` re-capture — and
       its floor drops to 26rem so a short viewport shrinks the box instead of
       cropping its transport under the fold (at 600dvh the cap resolves
       ~432px, under the 36rem the rules rail can hold there). */
    <section className="border-t border-line-soft [--rail:clamp(30rem,32.787vw_+_9.016rem,40rem)] [--rail-big:clamp(36rem,min(26.23vw_+_19.213rem,(100dvh_-_17.25rem)*1.8286),44rem)] [--rail-row:clamp(26rem,min(26.23vw_+_19.213rem,(100dvh_-_17.25rem)*1.3333),44rem)] [--measure:clamp(26rem,13.115vw_+_17.606rem,30rem)]">
      {/* ---- 1 · VERDICT, rail RIGHT: the merged claim's two micro-beats,
              with the 02b take riding beside them. The take opens on `raw`
              as the rail pins — the same beat the first paragraph argues —
              and runs to the kept record on its own clock. -------------- */}
      <div className="mx-auto grid w-full max-w-[85rem] gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,var(--rail))]">
        <div>
          <Claim
            eyebrow={CLAIMS.verdict.eyebrow}
            headline={CLAIMS.verdict.headline}
            label={ARTIFACT.labels[0]}
            inline={<VerdictEmail stage="raw" />}
          >
            <p>{CLAIMS.verdict.raw}</p>
          </Claim>

          <Claim
            continued
            label={ARTIFACT.labels[1]}
            inline={
              <>
                <VerdictEmail stage="split" />
                {/* Chips first, arithmetic second — inline, the reader has
                    to see the disagreement before its tally means anything.
                    At `lg` the chips live in the sticky column, so the
                    tally is what the claim side holds (below). */}
                <VerdictTally className="mt-6" />
              </>
            }
          >
            <p>{CLAIMS.verdict.split}</p>
            {/* The claim side of micro-beat two: the tally is the claim's
                own evidence — the same two calls, one level deeper — not a
                filler figure. `lg`+ only: below `lg` it renders inline
                after the chips it explains. */}
            <VerdictTally className="hidden lg:block" />
          </Claim>

          {/* THE TAKE'S RUNWAY. The rail plays on its own clock, and this is
              the scroll the phase spends holding it in frame while it does —
              without it the pin releases mid-dissolve at short viewports.
              Smaller than the old escalation tail (that one also carried the
              scroll-driven exit marks, which the take replaced). `lg`-only:
              below `lg` there is no rail to hold. */}
          <div aria-hidden className="hidden h-[60vh] lg:block" />
        </div>

        {/* The rail's box is the VIEWPORT, not the exhibit: this exhibit
            changes height at every beat (raw, split, the record), so there
            is no one measured constant to centre it against, and a box that
            owns the whole free viewport re-centres each stage for free.

            Pinned at 4.5rem — the oner's own offset, the page's other
            viewport-tall pinned box — and UNPADDED, both for the fold: at
            1024x600 the split beat's exhibit plus the take's chrome runs the
            box to the fold's edge, and the old `top-20` + `py-4` spent 24px
            of that budget putting the provenance line 10.6px UNDER it
            (measured 2026-08-20, production build). The box is the viewport;
            padding inside it only ever manifests as crop at the one height
            where the fold guarantee is tight. */}
        <div className="hidden lg:block">
          <div
            data-rail="verdict"
            className="sticky top-[4.5rem] flex min-h-[calc(100dvh-4.5rem)] flex-col justify-center"
          >
            <RailZoom>
              <RailTake
                beats={verdictBeats}
                label={KEPT.label}
                opening={KEPT.opening}
                resting={KEPT.resting}
              >
                <VerdictEmail evidence stage={VERDICT_STAGES[verdictStage] ?? "split"} />
              </RailTake>
            </RailZoom>
          </div>
        </div>
      </div>

      {/* ---- 2 · RULES, rail LEFT — the spine's first handoff, and the
              page's ONE BIG BOX. The recording was an in-flow figure here;
              it is the phase's exhibit now, promoted to its own rail at
              `--rail-big` (36rem at 1024 → 44rem at 1512+, height-fitted):
              the densest clip on the page — the sandbox, its scores, the
              line where the rules answer alone — renders at or past the
              recorded UI's own scale instead of 0.41x of it. The flow keeps
              the benchmark, drawn under the reader's descent: figure and
              footage argue the same sentence from two sides of the
              gutter. --------------------------------------------------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-[85rem] gap-x-12 px-6 lg:grid-cols-[minmax(0,var(--rail-big))_minmax(0,1fr)]">
          <div className="hidden lg:block">
            {/* Box hugs its exhibit; the sticky offset centres it in the
                free viewport and `mb-14` lands its release on the phase's
                closing line. `--exhibit` is now a FORMULA of the same var
                that sets the rail's width — picture (the encode's 630:1152
                aspect over the frame's inner width) plus the frame's chrome,
                a CONSTANT because the stacked caption wraps at a capped
                measure (`ProductClip`) — so the centring tracks the fluid
                width continuously instead of going stale between
                breakpoints. The chrome constants are MEASURED against the
                rendered exhibit on `next build && next start` (2026-08-20,
                this restaging), because `next dev` cannot measure this page;
                the xl step is the figcaption's `xl:pt-1`. A dropped var is
                loud (`calc()` over an undefined var un-pins the rail and the
                pin walk reds); a stale constant shifts the pin by half its
                error. */}
            <div
              data-rail="rules"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:calc((var(--rail-big)_-_2px)*0.546875_+_8.46rem)] xl:[--exhibit:calc((var(--rail-big)_-_2px)*0.546875_+_8.71rem)]"
            >
              <RailZoom>
                <ProductClip
                  stack
                  clip={CLIPS.rulesReadTheBody}
                  name={FOOTAGE.rules.name}
                  caption={FOOTAGE.rules.caption}
                />
              </RailZoom>
            </div>
          </div>
          <div>
            <Claim
              eyebrow={DECISION.eyebrow}
              headline={DECISION.headline}
              inline={
                <ProductClip
                  stack
                  clip={CLIPS.rulesReadTheBody}
                  name={FOOTAGE.rules.name}
                  caption={FOOTAGE.rules.caption}
                />
              }
            >
              <p>{DECISION.body}</p>
            </Claim>
            <Claim continued>
              <DrawnBenchmark />
              <p className="text-sm text-dim">{DECISION.gate}</p>
            </Claim>
          </div>
        </div>
      </div>

      {/* ---- 3 · REVIEW, rail RIGHT: the decision phase's second half,
              split into its own beat — one phase was carrying two ideas,
              and the held exhibit deserved the claim column it never had.
              The 08c take rides here: Cedar's note, then its settle into
              the real review queue, the product stating its own gate. --- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-[85rem] gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,var(--rail))]">
          <div>
            <Claim
              eyebrow={REVIEW.eyebrow}
              headline={REVIEW.headline}
              label={HELD.mail}
              inline={<HeldExhibit settled={false} queue={false} />}
            >
              <p>{REVIEW.body}</p>
            </Claim>
            <Claim continued>
              <p>{REVIEW.gate}</p>
            </Claim>
          </div>
          {/* Viewport-tall box, the verdict rail's argument: the exhibit's
              height moves in BOTH beats (the card's body collapses while
              the queue rises), so no constant centres both states. Same
              4.5rem offset and no padding, for the verdict rail's fold
              reasons — the two take rails are one construction. */}
          <div className="hidden lg:block">
            <div
              data-rail="review"
              className="sticky top-[4.5rem] flex min-h-[calc(100dvh-4.5rem)] flex-col justify-center"
            >
              <RailZoom>
                <RailTake
                  beats={heldBeats}
                  label={HELD_TAKE.label}
                  opening={HELD_TAKE.opening}
                  resting={HELD_TAKE.resting}
                >
                  <HeldExhibit settled={settled} />
                </RailTake>
              </RailZoom>
            </div>
          </div>
        </div>
      </div>

      {/* ---- 4 · ROW, rail LEFT: the tracked recording (03c-i, "ride the
              letter") against the hero's own sentence, promoted from a
              passing clause to the beat it deserved: the mail becomes the
              move. The camera move is disclosed in the clip's own words
              (`FOOTAGE.letter`), per the footage covenant.

              THE PAGE'S SECOND BIG BOX since 2026-08-21 — the owner's call,
              off a screenshot of the old 478x129 strip: "a big square and
              rectangle box that covers the entire half of the left side".
              The clip was re-captured for it at a 704x528 CSS frame (4:3,
              encoded 1408x1056 — scenes.mjs derives both), so the box is
              real picture, not a letterboxed strip: at `--rail-row`'s 44rem
              ceiling the recording renders at the product's own scale, and
              the left column it sits in is half the 85rem gutter. --------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-[85rem] gap-x-12 px-6 lg:grid-cols-[minmax(0,var(--rail-row))_minmax(0,1fr)]">
          <div className="hidden lg:block">
            {/* `--exhibit` = picture (1056:1408 = 0.75 over the inner width)
                + the same measured chrome constants the rules rail derives. */}
            <div
              data-rail="row"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:calc((var(--rail-row)_-_2px)*0.75_+_8.46rem)] xl:[--exhibit:calc((var(--rail-row)_-_2px)*0.75_+_8.71rem)]"
            >
              <RailZoom>
                <ProductClip
                  stack
                  clip={CLIPS.oneLetter}
                  name={FOOTAGE.letter.name}
                  caption={FOOTAGE.letter.caption}
                />
              </RailZoom>
            </div>
          </div>
          <div>
            <Claim
              eyebrow={ROW.eyebrow}
              headline={ROW.headline}
              inline={
                <ProductClip
                  stack
                  clip={CLIPS.oneLetter}
                  name={FOOTAGE.letter.name}
                  caption={FOOTAGE.letter.caption}
                />
              }
            >
              <p>{ROW.body}</p>
            </Claim>
            <Claim continued>
              <p>{ROW.aside}</p>
            </Claim>
          </div>
        </div>
      </div>

      {/* ---- 5 · RETENTION, rail RIGHT: the pinned exhibit is the READING —
              a pass of mail going in, counted by the strip that counts it
              (`PRIVACY.retention` opens "the classifier reads a message's
              body to decide, then discards it", and this is the first of
              those two events). What a read message leaves behind — the
              record — stays IN THE FLOW beside the paragraph it enacts: as
              the reader crosses the sentence that says the body is
              discarded, the body is discarded. ------------------------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-[85rem] gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,var(--rail))]">
          <div>
            <Claim
              eyebrow={PRIVACY.eyebrow}
              headline={PRIVACY.headline}
              inline={
                <ProductClip
                  stack
                  clip={CLIPS.boardSyncs}
                  name={FOOTAGE.sync.name}
                  caption={FOOTAGE.sync.caption}
                />
              }
            >
              <p>{PRIVACY.scope}</p>
            </Claim>
            <Claim continued>
              <p>{PRIVACY.retention}</p>
              {/* The record. `min-h` holds the taller of the two states so
                  the collapse does not pull the page up under the reader —
                  MEASURED at a 26rem measure, where the body wraps most: raw
                  is 349px and the record 344px, so 23rem clears both. */}
              <div ref={keptRef} className="pt-4">
                <p className="label-caps mb-2 h-4">{ARTIFACT.labels[kept ? 3 : 0]}</p>
                <div className="min-h-[23rem] max-w-[26rem]">
                  <VerdictEmail stage={kept ? "retained" : "raw"} />
                </div>
              </div>
            </Claim>
            <Claim continued paced={false}>
              <p>
                {PRIVACY.mechanism}{" "}
                <span className="break-all font-mono text-[0.8125rem] text-strong">
                  {PRIVACY.testPath}
                </span>
              </p>
              <p className="text-sm text-dim">
                {PRIVACY.systemCardLead}{" "}
                <a
                  href="/system-card"
                  {...NEW_TAB}
                  className="text-muted underline underline-offset-4 transition-colors hover:text-strong"
                >
                  {PRIVACY.systemCardLink}
                </a>{" "}
                — {PRIVACY.policyLead}{" "}
                <a
                  href="/privacy"
                  {...NEW_TAB}
                  className="text-muted underline underline-offset-4 transition-colors hover:text-strong"
                >
                  {PRIVACY.policyLink}
                </a>
                .
              </p>
            </Claim>
          </div>
          {/* Box hugs its exhibit, the offset does the centring, `mb-14`
              lands it on the phase's closing line — the rules rail above
              argues all four, and `--exhibit` is measured the same way. */}
          <div className="hidden lg:block">
            <div
              data-rail="retention"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:calc((var(--rail)_-_2px)*0.269097_+_8.46rem)] xl:[--exhibit:calc((var(--rail)_-_2px)*0.269097_+_8.71rem)]"
            >
              <RailZoom>
                <ProductClip
                  stack
                  clip={CLIPS.boardSyncs}
                  name={FOOTAGE.sync.name}
                  caption={FOOTAGE.sync.caption}
                />
              </RailZoom>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
