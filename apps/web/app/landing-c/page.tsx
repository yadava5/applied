import type { Metadata } from "next";

import { ClaimsDescent } from "@/components/marketing/ClaimsDescent";
import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { HERO } from "@/components/marketing/copy";
import { LandingBoard } from "@/components/marketing/LandingBoard";
import { AccessSection } from "@/components/marketing/sections";

/**
 * Landing candidate C — IN MOTION. The board still leads (board-first is the
 * whole family's stance), and then the page descends: one claim per screen,
 * with one synthetic rejection email riding alongside — read, cut at Gmail's
 * preview, classified live by the shipped rules layer, and finally stripped
 * to the columns the database actually keeps. The most editorial of the
 * three; the discipline is one claim per screen, never a return to the
 * chaptered case study this family replaces.
 *
 * Same copy as A and B (`copy.ts`); the descent restages it.
 */
export const metadata: Metadata = {
  title: "Landing C — in motion",
  robots: { index: false, follow: false },
};

export default function LandingC() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- hero: the product first, compact ---------------------------- */}
      <section className="mx-auto w-full max-w-6xl px-6 pt-16 pb-10 sm:pt-20">
        <h1 className="max-w-2xl text-balance text-4xl font-semibold tracking-tight text-strong sm:text-5xl">
          {HERO.headline}
        </h1>
        <p className="mt-4 max-w-xl text-balance text-muted">{HERO.subhead}</p>
      </section>
      <div className="w-full border-t border-line-soft px-4 pt-5 pb-6 lg:px-6">
        <LandingBoard height="min(56vh, 560px)" />
      </div>

      {/* ---- the descent: one claim per screen --------------------------- */}
      <ClaimsDescent />

      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
