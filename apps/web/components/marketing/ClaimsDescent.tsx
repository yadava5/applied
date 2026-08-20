"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, HELD, HELD_TAKE, KEPT, PRIVACY, REVIEW, ROW } from "./copy";
import type { TakeClock } from "./director";
import { CLIPS } from "./footage";
import { HeldExhibit } from "./HeldExhibit";
import { ProductClip } from "./ProductClip";
import { RailTake } from "./RailTake";
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
 * bookends pin and PLAY. The rails now do the same (`RailTake`), with the
 * scroll still holding one job on them — the clock freezes when the rail
 * leaves the viewport, so nothing finishes unwatched. The flow exhibits
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
 * SIZING (the owner's edit, 2026-08-20): the flowing prose is set smaller
 * and narrower than the exhibits it argues for (`Claim` — 0.9375rem on a
 * 26rem measure), and ONE box is materially bigger: the rules recording's
 * rail is 36rem, which renders the densest clip on the page at the encode's
 * native 2x width (576 CSS px of a 1152 encode) — the one exhibit that
 * earns the room, because it is the only one whose type was measurably
 * degraded at the old 30rem (0.41x of authored size).
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
        <h2 className="max-w-xl text-balance text-2xl font-medium tracking-tight text-strong sm:text-3xl">
          {headline}
        </h2>
      )}
      {/* The owner's sizing edit (2026-08-20): the scrolling text steps DOWN
          from the exhibits — 0.9375rem on a 26rem measure, where it was
          16px on 36rem. The exhibits are the page; the prose annotates. */}
      <div
        className={cn(
          "max-w-[26rem] space-y-4 text-[0.9375rem] leading-relaxed text-muted",
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

  const verdictTake = useCallback(async (clock: TakeClock) => {
    setVerdictStage(0);
    clock.say(KEPT.narration[0]);
    await clock.hold(3000);
    setVerdictStage(1);
    clock.say(KEPT.narration[1]);
    await clock.hold(3800);
    setVerdictStage(2);
    clock.say(KEPT.narration[2]);
    await clock.hold(2800);
    setVerdictStage(3);
    clock.say(KEPT.narration[3]);
    await clock.hold(800);
  }, []);

  /**
   * The held rail's two beats — the owner's 08c pick ("where it waits"), as
   * its lab take: Cedar's note alone, then its settle into the real review
   * queue. Rests settled (the queue is the truth a non-watching visitor
   * needs); the take winds it back.
   */
  const [settled, setSettled] = useState(true);
  const heldTake = useCallback(async (clock: TakeClock) => {
    setSettled(false);
    clock.say(HELD_TAKE.narration[0]);
    await clock.hold(2600);
    setSettled(true);
    clock.say(HELD_TAKE.narration[1]);
    await clock.hold(3000);
    clock.say(HELD_TAKE.narration[2]);
    await clock.hold(800);
  }, []);

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
    <section className="border-t border-line-soft">
      {/* ---- 1 · VERDICT, rail RIGHT: the merged claim's two micro-beats,
              with the 02b take riding beside them. The take opens on `raw`
              as the rail pins — the same beat the first paragraph argues —
              and runs to the kept record on its own clock. -------------- */}
      <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
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
            <RailTake
              take={verdictTake}
              label={KEPT.label}
              opening={KEPT.opening}
              resting={KEPT.resting}
            >
              <VerdictEmail evidence stage={VERDICT_STAGES[verdictStage] ?? "split"} />
            </RailTake>
          </div>
        </div>
      </div>

      {/* ---- 2 · RULES, rail LEFT — the spine's first handoff, and the
              page's ONE BIG BOX. The recording was an in-flow figure here;
              it is the phase's exhibit now, promoted to its own rail at
              36rem: 576 CSS px is the 1152 encode's native 2x width, so the
              densest clip on the page — the sandbox, its scores, the line
              where the rules answer alone — renders at the recorded UI's own
              scale instead of 0.41x of it. The flow keeps the benchmark,
              drawn under the reader's descent: figure and footage argue the
              same sentence from two sides of the gutter. ---------------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-6xl gap-x-12 px-6 lg:grid-cols-[minmax(0,36rem)_minmax(0,1fr)]">
          <div className="hidden lg:block">
            {/* Box hugs its exhibit; the sticky offset centres it in the
                free viewport and `mb-14` lands its release on the phase's
                closing line. `--exhibit` is the exhibit's MEASURED height —
                measured on `next build && next start`, because `next dev`
                cannot measure this page. A dropped constant is loud
                (`calc()` over an undefined var un-pins the rail and the pin
                walk reds); a stale one shifts the pin by half its error. */}
            <div
              data-rail="rules"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:28.125rem] xl:[--exhibit:28.3125rem]"
            >
              <ProductClip
                stack
                clip={CLIPS.rulesReadTheBody}
                name={FOOTAGE.rules.name}
                caption={FOOTAGE.rules.caption}
              />
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
        <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
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
              <RailTake
                take={heldTake}
                label={HELD_TAKE.label}
                opening={HELD_TAKE.opening}
                resting={HELD_TAKE.resting}
              >
                <HeldExhibit settled={settled} />
              </RailTake>
            </div>
          </div>
        </div>
      </div>

      {/* ---- 4 · ROW, rail LEFT: the tracked recording (03c-i, "ride the
              letter") against the hero's own sentence, promoted from a
              passing clause to the beat it deserved: the mail becomes the
              move. The camera move is disclosed in the clip's own words
              (`FOOTAGE.letter`), per the footage covenant. -------------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
          <div className="hidden lg:block">
            <div
              data-rail="row"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:16.5rem] xl:[--exhibit:16.75rem]"
            >
              <ProductClip
                stack
                clip={CLIPS.oneLetter}
                name={FOOTAGE.letter.name}
                caption={FOOTAGE.letter.caption}
              />
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
        <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
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
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:16.5rem] xl:[--exhibit:16.75rem]"
            >
              <ProductClip
                stack
                clip={CLIPS.boardSyncs}
                name={FOOTAGE.sync.name}
                caption={FOOTAGE.sync.caption}
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
