"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, HELD, PRIVACY } from "./copy";
import { CLIPS } from "./footage";
import { HeldExhibit } from "./HeldExhibit";
import { ProductClip } from "./ProductClip";
import { latch, trackProgress } from "./scrub";
import { VerdictEmail, type VerdictStage } from "./VerdictEmail";
import { VerdictTally } from "./VerdictTally";

/**
 * The descent: one claim per screen, with the email riding alongside. The SAME
 * copy the other variants render as sections — imported from `copy.ts`,
 * restaged, never rewritten — plus the claim only this staging can make
 * (`CLAIMS.verdict`), because it is demonstrated by the artifact rather than
 * asserted.
 *
 * THE SECTION IS THE PAGE'S SPINE, AND THE SPINE ALTERNATES. The owner chose
 * this landing FOR the pinned-scroll language and rejected the build where it
 * happened on one phase and evaporated: the verdict claim had a pinned rail,
 * the decision claim went full width, retention was a plain in-flow pairing,
 * and the page read as one trick that happens once. The direction he set is
 * the architecture now: every phase is one column pinned while the other
 * flows past it, and the pinned SIDE switches at every major phase — that
 * switch is what marks a phase change, and it is why each handoff has a
 * reason to exist. With the window act and the closing act (both full-stage
 * pins) as bookends, the page runs:
 *
 *   window act (full frame: the workday oner) → verdict (RIGHT rail: the
 *   email, raw → split → dissolve → the kept record — the owner's 02b pick)
 *   → decision (LEFT rail: the held mail settling into the review queue —
 *   the owner's 08c pick; the rules recording loops in the flow beside the
 *   paragraph it evidences) → retention (RIGHT rail: the sync recording;
 *   the record enacts its collapse in the flow) → access (LEFT rail: the
 *   import recording — `AccessPhase`) → closing act (full frame, plays
 *   itself).
 *
 * Which exhibit rides which rail is decided by what the exhibit DOES: the
 * artifacts that change state under the reader ride the rails, where the
 * phase's own progress can drive them, and the recordings — which loop and
 * need no driving — sit in the flow beside the sentences they evidence. An
 * earlier full-width staging of the decision claim is deliberately
 * superseded here: it measured fine, and it broke the language the page was
 * chosen for.
 *
 * The exhibit's stage follows SCROLL PROGRESS, not an observer. The previous
 * mechanism was an enter-only IntersectionObserver (`if (!isIntersecting)
 * continue`), so once the last sentinel left the centre band nothing
 * intersected again and the last-fired stage persisted whatever the reader
 * did next. There is one continuous signal now: progress through the paired
 * claims, against the measured position of the second micro-beat within them.
 * It reverses by construction.
 *
 * Below `lg` stickiness would fight the reading flow, so each screen carries
 * its own inline snapshot of the artifact at the right stage — a layout
 * decision, not a fallback.
 *
 * THREE claims, and the first is two micro-beats. `CLAIMS.verdict` owns both:
 * cause and effect used to be two claims 160vh apart, and a reader who
 * stopped after the first left with the problem and none of the
 * differentiator. Merging them into one static annotated diagram would have
 * cost more than it saved — the exhibit's power is that it happens IN ORDER,
 * the preview visibly ending before the sentence that matters and only then
 * the two verdicts disagreeing.
 */

/**
 * Half-width of the deadband around the micro-beat boundary, as a share of
 * the paired claims' own height (~40px at a 949-tall viewport). Smaller than
 * the window act's, because what it guards is a crossfade between two states
 * of a diagram rather than a layout animation — chatter here costs nothing
 * but would still look nervous.
 */
const STAGE_DEADBAND = 0.03;

/**
 * Progress through the paired claims: 0 when their top crosses the viewport's
 * middle, 1 when their bottom does — so the boundary the reader feels (a claim
 * "becomes the claim" as it crosses the centre) is the one the arithmetic
 * uses. The same centre band the IntersectionObserver used, without the
 * enter-only trap.
 */
const DESCENT_WINDOW = { from: 0.5, to: 0.5 };

/**
 * The benchmark ladder's own window: 0 as the figure's top enters from the
 * foot of the viewport, 1 once its bottom is comfortably above the middle. The
 * bars draw across that, so the decision claim's exhibit arrives WITH the
 * reader instead of sitting there already finished — the back half of this
 * page had nothing left in it that answered a scroll, and this is the cheapest
 * honest thing that does. See `BenchmarkFigure` for why both bars run on one
 * clock and why the default is the composed figure.
 */
const BENCH_WINDOW = { from: 0.95, to: 0.55 };

/**
 * The retention exhibit's window and mark. The claim is "read in flight, never
 * kept", and this is the one exhibit on the page that can ENACT it rather than
 * assert it: the email arrives whole, and as the reader crosses the paragraph
 * that says the body is discarded, the body is discarded — `VerdictEmail`
 * already animates `raw` → `retained`, and what was missing was anyone to
 * drive it. It used to be hardcoded `retained`, so the page showed the
 * aftermath of an event it never let anyone watch.
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
 * Where the held mail settles into the review queue, as progress through the
 * decision phase's own block (the same centre-band window the verdict pair
 * uses). Before the mark the rail holds Cedar's note alone — the mail the
 * rules will not guess about — and past it the note takes its place in the
 * real queue. 0.35 lands the settle while the reader is crossing from the
 * body/recording beat into the benchmark beat, with the rail pinned in frame
 * on both sides of the mark.
 */
const HELD_MARK = 0.35;

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
   * it. True only where a claim is paired with the travelling exhibit, which
   * is what the pacing exists for: the claim has to sit opposite the state
   * the exhibit is showing. An unpaired claim paced the same way is where the
   * measured 175px and 180px of empty ground came from, because centring
   * short content in a tall box puts half the slack above it and half below.
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
        <h2 className="max-w-xl text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          {headline}
        </h2>
      )}
      <div className={cn("max-w-xl space-y-4 text-muted", headline && "mt-5")}>{children}</div>
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
 * time. A reveal that accelerates would be the page performing at the reader
 * rather than answering them.
 *
 * It refuses to take apart a figure that is already on screen at load, the
 * same rule the closing act follows — pulling a finished bar back to nothing
 * under someone's eyes is worse than never animating it.
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
  const pairRef = useRef<HTMLDivElement>(null);
  const secondBeatRef = useRef<HTMLDivElement>(null);

  /**
   * The verdict rail's ladder — the owner's 02b pick ("what it kept"), as
   * scroll states rather than the lab's timed take, because every rail state
   * on this page is a function of position and reverses by construction.
   *
   *   0 raw       the mail as Gmail hands it over;
   *   1 split     the two verdicts disagree AND the deciding phrases light —
   *               the lit spans are the winning verdict's own evidence
   *               (`traceEvidence`), so the chips and their cause land as
   *               one beat;
   *   2 dissolve  every sentence the walk never matched fades to a residue —
   *               Applied's copy, never the visitor's Gmail (the wall label
   *               carries that rail);
   *   3 retained  the lit phrases go too and the kept record rises: even the
   *               deciding phrase is read and used, never stored.
   *
   * Stages 2–3 are the phase's EXIT gesture: their marks sit past the second
   * micro-beat, so the reader leaves the verdict phase watching the mail
   * reduce to the record — the shape the retention phase later argues in
   * full. REDUCED MOTION caps the ladder at `split`: the dissolve is pure
   * motion-grammar, and the pre-pick staging (raw ⇄ split) is this exhibit's
   * legible resting pair.
   */
  const [verdictStage, setVerdictStage] = useState(0);
  const VERDICT_STAGES: readonly VerdictStage[] = ["raw", "split", "dissolve", "retained"];
  const VERDICT_LABELS = [0, 1, 4, 3] as const;

  /**
   * Where the second micro-beat starts, as a share of the pair's own height —
   * MEASURED, because the claims are `min-h` boxes over live copy and their
   * real heights are whatever the type does at this width. A hardcoded 0.5
   * would put the exhibit's advance in the wrong place at every viewport but
   * one. In a ref rather than state: the motion-value handler reads it, and a
   * measurement is not a reason to render.
   */
  const splitAtRef = useRef(0.5);
  /**
   * Where the rail UNPINS, as progress through the pair: the sticky box's
   * bottom is the viewport's bottom (`top-20` + a `100dvh - 5rem` box), so
   * the release begins when the pair's bottom reaches it — half a viewport
   * of rect travel before progress 1 (`DESCENT_WINDOW` puts 1 at the
   * centre). MEASURED like `splitAt`, because it moves with every quantity
   * the type does: the escalation's marks are derived from it so the
   * dissolve and the record always fire while the exhibit is PINNED — the
   * first cut hardcoded tail fractions and the dissolve played at
   * railTop −112px, off the top of the frame (measured, 1024×600).
   */
  const unpinAtRef = useRef(1);
  useEffect(() => {
    const pair = pairRef.current;
    const second = secondBeatRef.current;
    if (!pair || !second) return;
    // Rects, not `offsetTop`: neither element is positioned, so `offsetTop`
    // would be measured against whatever ancestor happens to be.
    const measure = () => {
      const height = pair.getBoundingClientRect().height;
      if (height <= 0) return;
      splitAtRef.current =
        (second.getBoundingClientRect().top - pair.getBoundingClientRect().top) / height;
      unpinAtRef.current = 1 - (0.5 * window.innerHeight) / height;
    };
    if (typeof ResizeObserver === "undefined") {
      const id = window.setTimeout(measure, 0);
      return () => window.clearTimeout(id);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(pair);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const pair = pairRef.current;
    if (!pair) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    return trackProgress(pair, DESCENT_WINDOW, (progress) => {
      setVerdictStage((prev) => {
        /**
         * The escalation marks, derived from two MEASUREMENTS rather than
         * hardcoded: the record's mark backs off the unpin point by the
         * latch's own reach (mark + deadband is where it actually fires)
         * plus a stride of margin, and the dissolve halves the interval —
         * so both states land while the exhibit is pinned, with equal dwell,
         * at every viewport the type reflows to. The escalation tail (the
         * `lg`-only spacer at the pair's foot) is what buys the interval;
         * if a viewport ever leaves no honest room between the split and
         * the release, the ladder collapses to raw ⇄ split rather than
         * flashing states nobody can read.
         */
        const splitAt = splitAtRef.current;
        const retainedAt = unpinAtRef.current - STAGE_DEADBAND - 0.04;
        const dissolveAt = splitAt + (retainedAt - splitAt) / 2;
        const room = retainedAt - splitAt > 4 * STAGE_DEADBAND;
        if (room && !reduce && latch(progress, retainedAt, prev >= 3, STAGE_DEADBAND)) return 3;
        if (room && !reduce && latch(progress, dissolveAt, prev >= 2, STAGE_DEADBAND)) return 2;
        if (latch(progress, splitAt, prev >= 1, STAGE_DEADBAND)) return 1;
        return 0;
      });
    });
  }, []);

  /**
   * The retention exhibit's stage. `true` — the record — is the SSR default and
   * where reduced motion stays, so a visitor who is never going to see the
   * collapse gets its result rather than its setup. The scrub only takes the
   * exhibit apart if the reader has not already seen it, the same rule the
   * closing act follows.
   */
  /**
   * The held exhibit's beat. `true` — settled in the queue — is the SSR
   * default and where reduced motion stays, so a visitor who will never see
   * the settle gets the resting truth (the mail, held, in the tray) rather
   * than its setup. The scrub only takes the exhibit apart if the reader has
   * not already seen it — the closing act's rule, shared by every driven
   * exhibit on this page.
   */
  const heldPhaseRef = useRef<HTMLDivElement>(null);
  const [settled, setSettled] = useState(true);
  useEffect(() => {
    const el = heldPhaseRef.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let stop: (() => void) | undefined;
    const raf = requestAnimationFrame(() => {
      if (el.getBoundingClientRect().top < window.innerHeight) return;
      setSettled(false);
      stop = trackProgress(el, DESCENT_WINDOW, (progress) => {
        setSettled((prev) => latch(progress, HELD_MARK, prev, STAGE_DEADBAND));
      });
    });
    return () => {
      cancelAnimationFrame(raf);
      stop?.();
    };
  }, []);

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
      {/* ---- the merged claim: two micro-beats against one travelling
              exhibit. One headline, stated once, and the artifact beside it
              advances raw → split underneath it. ------------------------- */}
      <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div ref={pairRef}>
          <Claim
            eyebrow={CLAIMS.verdict.eyebrow}
            headline={CLAIMS.verdict.headline}
            label={ARTIFACT.labels[0]}
            inline={<VerdictEmail stage="raw" />}
          >
            <p>{CLAIMS.verdict.raw}</p>
          </Claim>

          <div ref={secondBeatRef}>
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
              {/* The claim side of micro-beat two. One paragraph used to
                  float alone in this column for a whole screen while the
                  exhibit disagreed with itself across the gutter; the tally
                  is the claim's own evidence — the same two calls, one level
                  deeper — not a filler figure. `lg`+ only: below `lg` it
                  renders inline after the chips it explains. */}
              <VerdictTally className="hidden lg:block" />
            </Claim>
          </div>

          {/* THE ESCALATION'S RUNWAY — the 02b tail. Not dead ground: this
              is the scroll the exhibit's two solo beats spend, with the
              flow's argument finished and the rail holding centre — the
              mail dissolves to its lit phrases, then to the record, while
              the wall label names each state. Every pixel of it produces a
              visible change, which is the page's own bar for runway. The
              marks are derived from the measured pin (see the drive above),
              so the tail's height sets the DWELL, not the correctness.
              `lg`-only: below `lg` there is no rail to perform into, and
              the inline snapshots already carry the states. */}
          <div aria-hidden className="hidden h-[80vh] lg:block" />
        </div>

        {/* ---- the artifact, riding alongside (`lg`+) ---------------------
            `top-20` is a measured offset, not a round number: the exhibit is
            464px of fixed content plus its wall label, and its last line is
            the one that says the email is synthetic and the verdicts are
            computed live — the sentence that stops a visitor reading these as
            verdicts on real mail. At a 600px viewport, 96px of offset and
            64px of padding cropped it away; 80 + 24 clears the nav by 24px
            and the whole exhibit fits.

            What is new is the BOX. The panel used to be pinned to the top of
            a viewport it could only half fill, which is where the measured
            ~320px of dead ground beneath it came from. It now owns the whole
            free viewport and centres itself in it, so the slack is margin
            above and below rather than a hole under a card. `min-h`, not `h`:
            an exhibit taller than the viewport grows the box instead of being
            cropped symmetrically by it. --------------------------------- */}
        <div className="hidden lg:block">
          {/* This rail keeps the viewport-tall box the three clip rails gave
              up (see the decision rail below): its exhibit CHANGES HEIGHT
              between stages — raw, split, retained — so there is no one
              measured constant to centre it against, and a box that owns the
              whole free viewport re-centres each stage for free. It carries
              no playback control and its band is the descent's longest, so
              neither of the two costs that moved the others applies here. */}
          <div
            data-rail="verdict"
            className="sticky top-20 flex min-h-[calc(100dvh-5rem)] flex-col justify-center py-6"
          >
            {/* The exhibit's wall label. It changes with the stage, so the
                reader is never looking at a state the page has not named —
                and it is what marks each beat as a new moment rather than a
                redrawn diagram. */}
            <p className="label-caps mb-2 h-4">
              {ARTIFACT.labels[VERDICT_LABELS[verdictStage] ?? 0]}
            </p>
            <VerdictEmail evidence stage={VERDICT_STAGES[verdictStage] ?? "raw"} />
          </div>
        </div>
      </div>

      {/* ---- the decision: the spine's first handoff — the pinned side
              SWITCHES. The held mail rides the LEFT rail (the owner's 08c
              pick, "where it waits"): Cedar's ambiguous note, which settles
              into the REAL review queue as the reader crosses the phase —
              the honest other half of "how it decides", enacted by the
              component that actually holds such mail, in the product's own
              words ("held because Applied wasn't sure · your decision files
              them"). The rules recording is KEPT — the owner's call,
              2026-08-20: the approved clips stay alongside the new takes —
              and moves INTO THE FLOW, directly under the paragraph it
              evidences, where it renders once for every width instead of a
              rail copy and an inline twin. The benchmark ladder stays in the
              flow as the claim's second beat — it is the argument's own
              figure, and it still draws under the reader's descent. ------ */}
      <div className="border-t border-line-soft">
        <div
          ref={heldPhaseRef}
          className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]"
        >
          {/* THE RAIL'S BOX IS ITS EXHIBIT, NOT THE VIEWPORT. Centring used to
              be the box's job — `min-h-[calc(100dvh-5rem)]` with
              `justify-center`, which put the exhibit in the middle of the free
              viewport by making the BOX a viewport tall — and it cost two
              measured things.

              A pin lives inside `band - rail`, so an empty box that tall ATE
              THE PHASE'S RUNWAY: #access held only 0.170 of its band at
              1512×949, under the 0.20 floor its own gate enforces, and the
              gate could not see it because it only ever ran at 1024×768.

              And the phase did not CLOSE LEVEL. At release the exhibit's
              bottom sat half the leftover height above the section's end, so
              the two columns bottomed out at different heights and the gap
              widened with the viewport — 34px at 1024×643, 88px at 1512×949,
              the flowing side hanging lower, which is what the owner saw.

              So the centring moves into the sticky OFFSET, where it costs
              nothing: the box hugs its exhibit, and `top` is what puts that
              box in the middle of the free viewport — `5rem` for the nav plus
              half of what is left over. Pinned, this renders where it rendered
              before. `mb-14` is the release: `5rem` above the section's rule
              less the `1.5rem` the box pads with, so the exhibit comes to rest
              on THE PHASE'S CLOSING LINE — the line the flow column's last
              beat ends on too (`paced={false}`, `py-20`).

              `--exhibit` is the exhibit's MEASURED height, to the nearest
              eighth-rem — measured on `next build && next start`, because
              `next dev` cannot measure this page. A CENTRING constant only —
              release and alignment come off the box's real height — so a
              stale value shifts the pinned exhibit by half its error and
              nothing else. Eighth-rem rather than quarter: 4px of
              granularity is 2px of shift and cannot hold 1px; 2px of
              granularity can. `max(5rem, …)` is the floor for short
              viewports, where the exhibit is taller than the free viewport
              and there is nothing left to centre.

              THIS RAIL NO LONGER USES ONE. The held exhibit is the other
              kind of rail cargo: its height moves in BOTH beats (the card's
              body collapses while the queue rises — measured at 1024×600 on
              `next build && next start`: 401.6px un-settled against ~313px
              settled), so there is no one constant that centres both states,
              which is the same fact that keeps the verdict rail on the
              viewport-tall box. It takes that staging: the box owns the free
              viewport and `justify-center` re-centres every state for free.
              The runway cost that retired this box on the CLIP rails does
              not apply here — their bands were a single claim's screen,
              while this phase's flow now carries three beats plus the
              recording, so the band affords the tall box (the pin walk's
              four corners are the proof, not this sentence). The clip rails
              below (retention, access) keep the hugging box and their
              measured constants, unchanged.

              NOTHING IN CI MEASURES THESE TWO NUMBERS. The pin walk watches
              runway and band, which a wrong centring constant does not move;
              where the exhibit actually comes to rest was checked by hand
              against dc1bdee's approved render (`next build && next start`,
              1024×600 / 643 / 768 and 1512×949: every rail within 0.5px, the
              verdict rail — which never changed — 0.0px as the control). A
              re-measure needs that comparison run again, not a green suite.

              A DROPPED constant is at least loud, which a stale one is not:
              `calc()` over an undefined `var()` is invalid at computed-value
              time, so `top` would fall back to `auto`, the rail would stop
              pinning, and the pin walk reds. Nothing above these rails
              declares `--exhibit` — the verdict rail, which does not use one,
              resolves it empty — so each rail reads only its own. */}
          <div className="hidden lg:block">
            <div
              data-rail="decision"
              className="sticky top-20 flex min-h-[calc(100dvh-5rem)] flex-col justify-center py-6"
            >
              {/* The wall label, the verdict rail's device: the exhibit
                  changes state under the reader, so the label names the
                  state — the mail alone, then its place in the queue. */}
              <p className="label-caps mb-2 h-4">{settled ? HELD.queue : HELD.mail}</p>
              <HeldExhibit settled={settled} />
            </div>
          </div>
          <div>
            <Claim eyebrow={DECISION.eyebrow} headline={DECISION.headline}>
              <p>{DECISION.body}</p>
              {/* The rules recording, in the flow it evidences — one mount
                  for every width, where the rail copy + inline twin used to
                  be two. It loops and needs no driving, and `ProductClip`'s
                  own centre-band observer still means no two recordings on
                  the page run at once. */}
              <ProductClip
                stack
                clip={CLIPS.rulesReadTheBody}
                name={FOOTAGE.rules.name}
                caption={FOOTAGE.rules.caption}
              />
            </Claim>
            {/* UNPACED, so the phase closes level. Held to `60vh` and centred,
                this beat ended 176px above the section's rule at 1512 against
                the rail's 24 — the two columns bottoming out at visibly
                different heights, which is what the owner saw. Unpaced it ends
                `py-20` above the rule at EVERY height, which is the line the
                rail's reclaim now targets. */}
            <Claim
              continued
              paced={false}
              label={HELD.mail}
              inline={<HeldExhibit settled={false} queue={false} />}
            >
              <DrawnBenchmark />
              <p className="text-sm text-dim">{DECISION.gate}</p>
            </Claim>
          </div>
        </div>
      </div>

      {/* ---- retention: the spine hands back to the RIGHT. The pinned
              exhibit is the READING — a pass of mail going in, counted by the
              strip that counts it (`PRIVACY.retention` opens "the classifier
              reads a message's body to decide, then discards it", and this is
              the first of those two events). What a read message leaves
              behind — the record — stays IN THE FLOW beside the paragraph it
              enacts: it arrives as the email and, as the reader crosses the
              sentence that says the body is discarded, the body is
              discarded. An exhibit that changes state under the reader stays
              with its claim; the one that loops rides the rail. --------- */}
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
                  is 349px and the record 344px, so 23rem clears both. The
                  width is capped at that measure so the measurement stays
                  true now that the column around it is wider. */}
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
          {/* Box hugs its exhibit, the offset does the centring, `mb-14` lands
              it on the phase's closing line, and `--exhibit` carries the two
              measured heights the `xl:pt-1` on the caption produces — the
              decision rail above argues all four. Here that is 263.9px below
              `xl` and 267.9px from `xl` on: the sync recording is a wide, short
              crop, so it is the shortest box on the page and the one whose old
              viewport-tall box wasted the most runway. */}
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
