"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ARTIFACT, CLAIMS, DECISION, FOOTAGE, PRIVACY } from "./copy";
import { CLIPS, ProductClip } from "./ProductClip";
import { VerdictEmail, type VerdictStage } from "./VerdictEmail";
import { VerdictTally } from "./VerdictTally";

/**
 * The descent: one claim per screen, with the email riding alongside. The SAME
 * copy the other variants render as sections — imported from `copy.ts`,
 * restaged, never rewritten — plus the claim only this staging can make
 * (`CLAIMS.verdict`), because it is demonstrated by the artifact rather than
 * asserted.
 *
 * At `lg`+ the artifact is one sticky `VerdictEmail` whose stage follows the
 * sentinel in the middle of the viewport (IntersectionObserver over a centre
 * band — no scroll-jacking, the page scrolls normally and the artifact only
 * ever responds). Below `lg` stickiness would fight the reading flow, so each
 * screen carries its own inline snapshot of the artifact at the right stage —
 * a layout decision, not a fallback.
 *
 * THREE claims, FOUR sentinels. `CLAIMS.verdict` owns the first two: cause and
 * effect used to be two claims 160vh apart, and a reader who stopped after the
 * first left with the problem and none of the differentiator. Merging them into
 * one static annotated diagram would have cost more than it saved — the
 * exhibit's power is that it happens IN ORDER, the preview visibly ending
 * before the sentence that matters and only then the two verdicts disagreeing.
 * So the merged claim keeps both artifact stages as micro-beats under one
 * headline: `WindowAct`'s shape, and the reason STAGES is indexed by SENTINEL
 * rather than by claim.
 */

/** Sentinel index → the artifact's stage and its wall label (`ARTIFACT`), which
 *  is why these two arrays must stay the same length:
 *
 *    0  the merged claim's first micro-beat — the mail as Gmail hands it over;
 *    1  its second — the same body, classified twice, the verdicts disagreeing;
 *    2  the decision screen, which keeps those two live verdicts on screen
 *       because they are the rules layer the benchmark chose doing its work;
 *    3  retention — the same email stripped to the row the database keeps.
 */
const STAGES: VerdictStage[] = ["raw", "split", "split", "retained"];

function Claim({
  eyebrow,
  headline,
  label,
  children,
  inline,
  continued,
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
}) {
  return (
    <div
      className={cn(
        "flex flex-col justify-center py-16",
        continued ? "min-h-[60vh]" : "min-h-[80vh]",
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
  const [active, setActive] = useState(0);
  const claimsRef = useRef<HTMLDivElement>(null);

  // The claims are found by attribute rather than by collected refs — one
  // container ref, queried inside the effect, keeps every `.current` read
  // out of render (react-hooks/refs).
  useEffect(() => {
    const root = claimsRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number((entry.target as HTMLElement).dataset.claim);
          if (Number.isInteger(index)) setActive(index);
        }
      },
      // A band around the viewport's middle: a claim becomes "the claim"
      // when it crosses the centre, whichever direction the reader scrolls.
      { rootMargin: "-40% 0px -40% 0px", threshold: 0 },
    );
    for (const el of root.querySelectorAll("[data-claim]")) io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="border-t border-line-soft">
      <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        {/* ---- the claims -------------------------------------------------- */}
        <div ref={claimsRef}>
          {/* ---- one claim, two micro-beats: the headline is stated once and
                  the exhibit beside it advances raw → split underneath it. --- */}
          <div data-claim={0}>
            <Claim
              eyebrow={CLAIMS.verdict.eyebrow}
              headline={CLAIMS.verdict.headline}
              label={ARTIFACT.labels[0]}
              inline={<VerdictEmail stage="raw" />}
            >
              <p>{CLAIMS.verdict.raw}</p>
            </Claim>
          </div>

          <div data-claim={1}>
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

          <div data-claim={2}>
            <Claim eyebrow={DECISION.eyebrow} headline={DECISION.headline}>
              <p>{DECISION.body}</p>
              <BenchmarkFigure className="mt-2" />
              <p className="text-sm text-dim">{DECISION.gate}</p>
              {/* The only beat of the four whose exhibit column repeats the
                  previous screen's artifact, and the only one whose claim is
                  about a layer the reader cannot see working. The recording
                  is that layer working, on the surface this paragraph names
                  ("in your own browser, on the demo") — the rules answering
                  a body on their own, and deferring to the neural layers
                  before they can. It goes last because the argument is
                  claim, evidence, gate, and only then the thing running. */}
              <ProductClip
                clip={CLIPS.rulesReadTheBody}
                name={FOOTAGE.rules.name}
                caption={FOOTAGE.rules.caption}
                className="mt-2"
              />
            </Claim>
          </div>

          <div data-claim={3}>
            <Claim
              eyebrow={PRIVACY.eyebrow}
              headline={PRIVACY.headline}
              label={ARTIFACT.labels[3]}
              inline={<VerdictEmail stage="retained" />}
            >
              <p>{PRIVACY.scope}</p>
              <p>{PRIVACY.retention}</p>
              <p>
                {PRIVACY.mechanism}{" "}
                <span className="break-all font-mono text-[0.8125rem] text-strong">{PRIVACY.testPath}</span>
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
        </div>

        {/* ---- the artifact, riding alongside (`lg`+) ---------------------- */}
        <div className="hidden lg:block">
          {/* `top-20 py-6`, tighter than the `top-24 py-16` this replaces.
              The exhibit is 464px of fixed content plus its wall label, and
              its last line is the one that says the email is synthetic and
              the verdicts are computed live — the sentence that stops a
              visitor reading these as verdicts on real mail. At a 600px
              viewport, 96px of offset and 64px of padding cropped it away.
              80 + 24 clears the nav by 24px and the whole exhibit fits.
              Nothing moves out of the card: the offset pays for it. */}
          <div className="sticky top-20 py-6">
            {/* The exhibit's wall label. It changes with the stage, so the
                reader is never looking at a state the page has not named —
                and on the merged claim it is what marks the second micro-beat
                as a new moment rather than a redrawn diagram. */}
            <p className="label-caps mb-2 h-4">{ARTIFACT.labels[active]}</p>
            <VerdictEmail stage={STAGES[active]} />
          </div>
        </div>
      </div>
    </section>
  );
}
