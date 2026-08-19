import type { Metadata } from "next";

import { ChangedRow } from "@/components/marketing/ChangedRow";
import { ClaimsDescent } from "@/components/marketing/ClaimsDescent";
import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { HERO } from "@/components/marketing/copy";
import { LandingBoard } from "@/components/marketing/LandingBoard";
import { AccessSection } from "@/components/marketing/sections";

/**
 * Landing candidate C — IN MOTION. The hero is the outcome at its smallest:
 * the single row the classifier just moved (Larkspur — the same application
 * the descent's email decides). Then the page descends, one claim at a time,
 * the email riding alongside — read whole, cut at Gmail's preview, classified
 * live, stripped to what the database keeps. The FULL board appears after the
 * argument, and Access closes. The most editorial of the three; the
 * discipline is one claim at a time, never a return to the chaptered case
 * study this family replaces.
 *
 * The descent is THREE claims over four screens: the first owns two of them,
 * because the preview ending and the two verdicts disagreeing have to happen
 * in that order to be a demonstration rather than a diagram.
 *
 * Same copy as A and B (`copy.ts`); the staging is the difference.
 */
export const metadata: Metadata = {
  title: "Landing C — in motion",
  robots: { index: false, follow: false },
};

export default function LandingC() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- hero: the row that just changed ----------------------------- */}
      <section className="mx-auto w-full max-w-6xl px-6 pt-16 pb-16 sm:pt-20">
        <h1 className="max-w-2xl text-balance text-4xl font-semibold tracking-tight text-strong sm:text-5xl">
          {HERO.headline}
        </h1>
        <p className="mt-4 max-w-xl text-balance text-muted">{HERO.subhead}</p>
        <div className="mt-10 max-w-2xl">
          <ChangedRow />
        </div>
      </section>

      {/* ---- the descent: one claim per screen --------------------------- */}
      <ClaimsDescent />

      {/* ---- the whole board, after the argument ------------------------- */}
      <section className="border-t border-line-soft">
        <div className="w-full px-4 py-14 lg:px-6">
          <LandingBoard height="min(62vh, 640px)" />
        </div>
      </section>

      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
