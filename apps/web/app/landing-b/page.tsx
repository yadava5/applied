import type { Metadata } from "next";

import { LandingBoard } from "@/components/marketing/LandingBoard";
import { MarketingFooter, MarketingNav, NEW_TAB } from "@/components/marketing/chrome";
import { BOARD, HERO } from "@/components/marketing/copy";
import { AccessSection, DecisionSection, PrivacySection } from "@/components/marketing/sections";

/**
 * Landing candidate B — FRAMED. The headline carries the weight (display
 * scale, left-aligned) and the board sits below it in a deliberate specimen
 * frame: a caption rail on the frame's own edge stating what the object is —
 * live fixtures, the shipped board, not a video. Cursor's composition, with
 * real DOM where Cursor puts words.
 *
 * Same copy and sections as A and C; only the staging differs.
 */
export const metadata: Metadata = {
  title: "Landing B — framed",
  robots: { index: false, follow: false },
};

export default function LandingB() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- hero: the headline at display scale ------------------------- */}
      <section className="mx-auto w-full max-w-6xl px-6 pt-20 pb-14 sm:pt-24">
        <h1 className="max-w-4xl text-balance text-5xl font-semibold tracking-[-0.025em] text-strong sm:text-6xl lg:text-7xl">
          {HERO.headline}
        </h1>
        <p className="mt-6 max-w-xl text-balance text-lg text-muted">{HERO.subhead}</p>
      </section>

      {/* ---- the specimen frame ------------------------------------------ */}
      <section className="mx-auto w-full max-w-6xl px-4 pb-8 sm:px-6">
        <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-2.5 sm:px-5">
            <span className="label-caps flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
              {BOARD.live}
            </span>
            <a
              href="/demo"
              {...NEW_TAB}
              className="label-caps text-muted transition-colors hover:text-strong"
            >
              {BOARD.open} →
            </a>
          </div>
          <div className="bg-background p-4 lg:p-5">
            <LandingBoard height="min(62vh, 620px)" caption={false} />
          </div>
        </div>
      </section>

      <DecisionSection />
      <PrivacySection />
      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
