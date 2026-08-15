import type { Metadata } from "next";

import { ClaimsDescent } from "@/components/marketing/ClaimsDescent";
import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { HERO } from "@/components/marketing/copy";
import { AccessSection } from "@/components/marketing/sections";
import { WindowAct } from "@/components/marketing/WindowAct";

/**
 * Landing B — the MERGED candidate: B's framed window containing the whole
 * app, driven by C's scroll. (A and C stand unchanged for comparison.)
 *
 * The sequence is the argument, one idea per screen:
 *
 *   1  the promise (display headline);
 *   2  the board, live in the window — the product before any explanation;
 *   3  the verdict lands — the window's row travels to closed, on its own;
 *   4  the mail behind it — the detail pane docks open (the approved
 *      composition), its trail ending in the receipt card's "the email that
 *      did it ↓";
 *   5–6 the descent takes that exact email: read whole, then the SPLIT
 *      VERDICT — the same body classified live twice, preview vs whole —
 *      the one artifact on the page nothing else can fake, placed after the
 *      act it explains;
 *   7  the benchmark that chose what ships;
 *   8  what is kept (retention), the email stripped to its record;
 *   9  the seats, and the one CTA.
 *
 * Screens 2–4 are `WindowAct` (the window pins, scroll advances the scene);
 * 5–8 are C's `ClaimsDescent`, untouched — same copy, same staging, so the
 * hand-off from the window's open trail to the descent's email is one
 * continuous case: the same Larkspur application end to end.
 */
export const metadata: Metadata = {
  title: "Landing B — the window, in motion",
  robots: { index: false, follow: false },
};

export default function LandingB() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- hero: the headline at display scale ------------------------- */}
      <section className="mx-auto w-full max-w-6xl px-6 pt-20 pb-12 sm:pt-24">
        <h1 className="max-w-4xl text-balance text-5xl font-semibold tracking-[-0.025em] text-strong sm:text-6xl lg:text-7xl">
          {HERO.headline}
        </h1>
        <p className="mt-6 max-w-xl text-balance text-lg text-muted">{HERO.subhead}</p>
      </section>

      {/* ---- the window act: the app proves it before the page explains -- */}
      <WindowAct />

      {/* ---- the descent: the email behind the act, one claim per screen - */}
      <ClaimsDescent />

      <AccessSection />
      <MarketingFooter />
    </main>
  );
}
