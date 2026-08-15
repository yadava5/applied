"use client";

import { useEffect, useRef, useState } from "react";

import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { CLAIMS, DECISION, PRIVACY } from "./copy";
import { VerdictEmail, type VerdictStage } from "./VerdictEmail";

/**
 * Variant C's middle act: one claim per screen, with the email riding
 * alongside. The SAME copy the other variants render as sections — imported
 * from `copy.ts`, restaged, never rewritten — plus the two claims only this
 * staging can make (`CLAIMS`), because they are demonstrated by the artifact
 * rather than asserted.
 *
 * At `lg`+ the artifact is one sticky `VerdictEmail` whose stage follows the
 * claim in the middle of the viewport (IntersectionObserver over a centre
 * band — no scroll-jacking, the page scrolls normally and the artifact only
 * ever responds). Below `lg` stickiness would fight the reading flow, so each
 * claim carries its own inline snapshot of the artifact at the right stage —
 * a layout decision, not a fallback.
 */

/** Claim index → the artifact's stage. The decision screen keeps the split
 *  verdicts on screen: the two live numbers are what the benchmark decided
 *  between. */
const STAGES: VerdictStage[] = ["raw", "split", "split", "retained"];

function Claim({
  eyebrow,
  headline,
  children,
  inline,
}: {
  eyebrow: string;
  headline: string;
  children: React.ReactNode;
  /** The below-`lg` artifact snapshot for this claim, when it has one. */
  inline?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[80vh] flex-col justify-center py-16">
      <p className="label-caps mb-4">{eyebrow}</p>
      <h2 className="max-w-xl text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
        {headline}
      </h2>
      <div className="mt-5 max-w-xl space-y-4 text-muted">{children}</div>
      {inline && <div className="mt-8 lg:hidden">{inline}</div>}
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
          <div data-claim={0}>
            <Claim
              eyebrow={CLAIMS.arrives.eyebrow}
              headline={CLAIMS.arrives.headline}
              inline={<VerdictEmail stage="raw" />}
            >
              <p>{CLAIMS.arrives.body}</p>
            </Claim>
          </div>

          <div data-claim={1}>
            <Claim
              eyebrow={CLAIMS.reads.eyebrow}
              headline={CLAIMS.reads.headline}
              inline={<VerdictEmail stage="split" />}
            >
              <p>{CLAIMS.reads.body}</p>
            </Claim>
          </div>

          <div data-claim={2}>
            <Claim eyebrow={DECISION.eyebrow} headline={DECISION.headline}>
              <p>{DECISION.body}</p>
              <BenchmarkFigure className="mt-2" />
              <p className="text-sm text-dim">{DECISION.gate}</p>
            </Claim>
          </div>

          <div data-claim={3}>
            <Claim
              eyebrow={PRIVACY.eyebrow}
              headline={PRIVACY.headline}
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
          <div className="sticky top-24 py-16">
            <VerdictEmail stage={STAGES[active]} />
          </div>
        </div>
      </div>
    </section>
  );
}
