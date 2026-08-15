import type { Metadata } from "next";

import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { HERO } from "@/components/marketing/copy";
import { LandingBoard } from "@/components/marketing/LandingBoard";
import { AccessSection, DecisionSection, PrivacySection } from "@/components/marketing/sections";

/**
 * Landing candidate A — FULL BLEED. The product fills the first screen: one
 * compact headline band, then the board takes every remaining pixel of the
 * viewport (the Linear stance — a live workspace, zero hero CTAs, no
 * surround). The stage height is viewport-derived but fixed per viewport, so
 * the reservation still holds and CLS stays zero.
 *
 * All three candidates share copy (`components/marketing/copy.ts`) and
 * sections; only the staging differs. `noindex` while the choice is open —
 * `/` keeps serving the current page untouched.
 */
export const metadata: Metadata = {
  title: "Landing A — full bleed",
  robots: { index: false, follow: false },
};

export default function LandingA() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- the takeover: one band of words, then the product ----------- */}
      {/* The viewport takeover is a `lg`+ composition — below it the still
          renders at natural height rather than floating in a 100dvh void. */}
      <section className="flex flex-col lg:min-h-[calc(100dvh-3.5rem)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-x-12 gap-y-3 px-6 pt-9 pb-6 lg:flex-row lg:items-end lg:justify-between">
          <h1 className="max-w-xl text-balance text-3xl font-semibold tracking-tight text-strong sm:text-4xl">
            {HERO.headline}
          </h1>
          <p className="max-w-md text-balance text-sm text-muted lg:pb-1 lg:text-right">
            {HERO.subhead}
          </p>
        </div>
        <div className="w-full flex-1 px-4 pb-4 lg:px-6">
          <LandingBoard height="clamp(480px, calc(100dvh - 16.5rem), 900px)" />
        </div>
      </section>

      <DecisionSection />
      <PrivacySection />
      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
