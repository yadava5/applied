"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, PRIVACY } from "./copy";
import { CLIPS } from "./footage";
import { ProductClip } from "./ProductClip";
import { latch, trackProgress } from "./scrub";
import { VerdictEmail } from "./VerdictEmail";
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
 *   window act (full frame) → verdict (RIGHT rail: the email, raw → split)
 *   → decision (LEFT rail: the rules recording, looping) → retention (RIGHT
 *   rail: the sync recording; the record enacts its collapse in the flow)
 *   → access (LEFT rail: the import recording — `AccessPhase`) → closing act
 *   (full frame, plays itself).
 *
 * Which exhibit rides which rail is decided by what the exhibit DOES: the
 * two artifacts that change state under the reader (the split verdict, the
 * kept record) sit where their claims can drive them — the verdict on its
 * rail, the record in the flow beside the sentence it enacts — and the
 * recordings, which loop and need no driving, take the rail on the phases
 * whose claims they evidence. An earlier full-width staging of the decision
 * claim is deliberately superseded here: it measured fine, and it broke the
 * language the page was chosen for.
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
  const [split, setSplit] = useState(false);

  /**
   * Where the second micro-beat starts, as a share of the pair's own height —
   * MEASURED, because the claims are `min-h` boxes over live copy and their
   * real heights are whatever the type does at this width. A hardcoded 0.5
   * would put the exhibit's advance in the wrong place at every viewport but
   * one. In a ref rather than state: the motion-value handler reads it, and a
   * measurement is not a reason to render.
   */
  const splitAtRef = useRef(0.5);
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
    return trackProgress(pair, DESCENT_WINDOW, (progress) => {
      setSplit((prev) => latch(progress, splitAtRef.current, prev, STAGE_DEADBAND));
    });
  }, []);

  /**
   * The retention exhibit's stage. `true` — the record — is the SSR default and
   * where reduced motion stays, so a visitor who is never going to see the
   * collapse gets its result rather than its setup. The scrub only takes the
   * exhibit apart if the reader has not already seen it, the same rule the
   * closing act follows.
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
                and it is what marks the second micro-beat as a new moment
                rather than a redrawn diagram. */}
            <p className="label-caps mb-2 h-4">{ARTIFACT.labels[split ? 1 : 0]}</p>
            <VerdictEmail stage={split ? "split" : "raw"} />
          </div>
        </div>
      </div>

      {/* ---- the decision: the spine's first handoff — the pinned side
              SWITCHES. The recording of the rules layer answering a body
              rides the LEFT rail, looping, while the claim that explains it
              flows past on the right: the reader is watching the layer that
              ships work for the whole time they are reading why it ships.
              The benchmark ladder stays in the flow as the claim's second
              beat — it is the argument's own figure, and it still draws
              under the reader's descent. ------------------------------- */}
      <div className="border-t border-line-soft">
        <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
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
              eighth-rem, and it takes TWO values because the exhibit does:
              417.8px below `xl` and 421.8px from `xl` on, because
              `ProductClip`'s figcaption carries `xl:pt-1`. That is a media
              query at 1280 and it was positive-controlled as one — 417.8px at
              1279, 421.8px at 1280, on `next build && next start`.

              ONE CONSTANT FOR BOTH WAS OFF THE APPROVED RENDER. `26.25rem`
              (420px) was measured at 1024 and centred that exhibit 1.1px high
              and the 1512 one 0.9px low, against a 1px bar. This is a CENTRING
              constant only — release and alignment come off the box's real
              height — so a stale value shifts the pinned exhibit by half its
              error and nothing else, which is exactly how 4px of exhibit
              became 2px of render. Eighth-rem rather than quarter: 4px of
              granularity is 2px of shift and cannot hold 1px; 2px of
              granularity can. `max(5rem, …)` is the floor for short viewports,
              where the exhibit is taller than the free viewport and there is
              nothing left to centre.

              NOTHING IN CI MEASURES THESE TWO NUMBERS. The pin walk watches
              runway and band, which a wrong centring constant does not move;
              where the exhibit actually comes to rest was checked by hand
              against dc1bdee's approved render (`next build && next start`,
              1024×600 / 643 / 768 and 1512×949: every rail within 0.5px, the
              verdict rail — which never changed — 0.0px as the control). A
              re-measure needs that comparison run again, not a green suite. */}
          <div className="hidden lg:block">
            <div
              data-rail="decision"
              className="sticky top-[max(5rem,calc(5rem_+_(100dvh_-_8rem_-_var(--exhibit))/2))] mb-14 py-6 [--exhibit:26.125rem] xl:[--exhibit:26.375rem]"
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
            {/* UNPACED, so the phase closes level. Held to `60vh` and centred,
                this beat ended 176px above the section's rule at 1512 against
                the rail's 24 — the two columns bottoming out at visibly
                different heights, which is what the owner saw. Unpaced it ends
                `py-20` above the rule at EVERY height, which is the line the
                rail's reclaim now targets. `paced` was already documented as
                being for claims paired with a travelling exhibit; the clip
                beside this one loops rather than advancing, so pacing bought
                the beat nothing here and cost it the centring slack. */}
            <Claim continued paced={false}>
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
