import type { Metadata } from "next";

import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { HERO } from "@/components/marketing/copy";
import { LandingBoard } from "@/components/marketing/LandingBoard";
import { AccessSection, DecisionSection, PrivacySection } from "@/components/marketing/sections";

/**
 * Landing candidate A — FULL BLEED. The demo shell runs edge to edge as the
 * hero: maximum "this is the product", minimum surround (the Linear stance —
 * a live workspace, zero hero CTAs). The headline is deliberately compact and
 * centred; the board does the pitching.
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

      {/* ---- hero: six words, then the product --------------------------- */}
      <section className="mx-auto w-full max-w-3xl px-6 pt-16 pb-10 text-center sm:pt-20">
        <h1 className="text-balance text-4xl font-semibold tracking-tight text-strong sm:text-5xl">
          {HERO.headline}
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-balance text-muted">{HERO.subhead}</p>
      </section>

      {/* ---- the board, edge to edge ------------------------------------- */}
      <div className="w-full border-t border-line-soft px-4 pt-5 pb-6 lg:px-6">
        <LandingBoard height="min(74vh, 720px)" />
      </div>

      <DecisionSection />
      <PrivacySection />
      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
