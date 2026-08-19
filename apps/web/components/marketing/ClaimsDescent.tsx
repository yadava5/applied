"use client";

import { useEffect, useRef, useState } from "react";
import { useMotionValueEvent, useScroll } from "motion/react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, PRIVACY } from "./copy";
import { CLIPS, ProductClip } from "./ProductClip";
import { latch } from "./scrub";
import { VerdictEmail } from "./VerdictEmail";
import { VerdictTally } from "./VerdictTally";

/**
 * The descent: one claim per screen, with the email riding alongside. The SAME
 * copy the other variants render as sections — imported from `copy.ts`,
 * restaged, never rewritten — plus the claim only this staging can make
 * (`CLAIMS.verdict`), because it is demonstrated by the artifact rather than
 * asserted.
 *
 * THE SECTION IS TWO MOVEMENTS, NOT ONE COLUMN AND ONE RAIL. It used to be a
 * single 3152px two-column grid whose right column held a 421px sticky panel:
 * measured, that left ~320px of empty ground under the panel and kept it
 * empty for the remaining ~2.5 viewports, which is the black space the owner
 * screenshotted. The panel was earning its keep for exactly one of the four
 * claims — the merged verdict claim, where the exhibit ADVANCING from `raw`
 * to `split` under one headline IS the argument. For the other two the file's
 * own note already admitted the column "repeats the previous screen's
 * artifact". So:
 *
 *   · the merged claim keeps the pairing, and the exhibit is CENTRED in the
 *     free viewport rather than pinned to its top, so its slack reads as
 *     margin on both sides instead of a hole beneath it;
 *   · the decision claim goes full width, which is a gain rather than a loss:
 *     its two real exhibits (the benchmark ladder and the recording of the
 *     rules layer answering a body) were boxed into a 576px prose measure
 *     beside a repeat of the previous screen's email;
 *   · the retention claim keeps a pairing, but a plain one in flow — the
 *     record the database keeps beside the paragraph that describes it, with
 *     no rail and nothing pinned.
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

export function ClaimsDescent() {
  const pairRef = useRef<HTMLDivElement>(null);
  const secondBeatRef = useRef<HTMLDivElement>(null);
  const [split, setSplit] = useState(false);

  // Progress through the paired claims: 0 when their top crosses the
  // viewport's middle, 1 when their bottom does — so the boundary the reader
  // feels (a claim "becomes the claim" as it crosses the centre) is the one
  // the arithmetic uses.
  const { scrollYProgress } = useScroll({
    target: pairRef,
    offset: ["start center", "end center"],
  });

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

  useMotionValueEvent(scrollYProgress, "change", (progress) => {
    setSplit((prev) => latch(progress, splitAtRef.current, prev, STAGE_DEADBAND));
  });

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
          <div className="sticky top-20 flex min-h-[calc(100dvh-5rem)] flex-col justify-center py-6">
            {/* The exhibit's wall label. It changes with the stage, so the
                reader is never looking at a state the page has not named —
                and it is what marks the second micro-beat as a new moment
                rather than a redrawn diagram. */}
            <p className="label-caps mb-2 h-4">{ARTIFACT.labels[split ? 1 : 0]}</p>
            <VerdictEmail stage={split ? "split" : "raw"} />
          </div>
        </div>
      </div>

      {/* ---- the decision: full width. The only claim of the three that is
              about a layer the reader cannot see working, and the only one
              whose exhibits are its own — the benchmark ladder and the
              recording of the rules answering a body. They were boxed into
              the prose measure beside a repeat of the email above; the
              paragraph keeps that measure, the exhibits do not. --------- */}
      <div className="mx-auto w-full max-w-6xl px-6">
        <Claim paced={false} eyebrow={DECISION.eyebrow} headline={DECISION.headline}>
          <p>{DECISION.body}</p>
        </Claim>
        <div className="grid gap-8 pb-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
          <div className="space-y-4">
            <BenchmarkFigure />
            <p className="text-sm text-dim">{DECISION.gate}</p>
          </div>
          {/* The recording goes second because the argument is claim,
              evidence, gate, and only then the thing running: the rules
              answering a body on their own, and deferring to the neural
              layers before they can — on the surface the paragraph names
              ("in your own browser, on the demo"). */}
          <ProductClip
            clip={CLIPS.rulesReadTheBody}
            name={FOOTAGE.rules.name}
            caption={FOOTAGE.rules.caption}
          />
        </div>
      </div>

      {/* ---- retention: the record beside the paragraph that describes it.
              A pairing in flow — no rail, nothing pinned — so the exhibit
              arrives with its claim and leaves with it. ------------------ */}
      <div className="mx-auto w-full max-w-6xl px-6">
        <div className="grid gap-x-16 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:items-start">
          <Claim paced={false} eyebrow={PRIVACY.eyebrow} headline={PRIVACY.headline}>
            <p>{PRIVACY.scope}</p>
            <p>{PRIVACY.retention}</p>
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
          <div className="pb-20 lg:pt-20">
            <p className="label-caps mb-2">{ARTIFACT.labels[3]}</p>
            <VerdictEmail stage="retained" />
          </div>
        </div>
      </div>
    </section>
  );
}
