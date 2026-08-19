import type { Metadata } from "next";

import { ClaimsDescent } from "@/components/marketing/ClaimsDescent";
import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { ClosingAct } from "@/components/marketing/ClosingAct";
import { FOOTAGE, HERO } from "@/components/marketing/copy";
import { CLIPS, ProductClip } from "@/components/marketing/ProductClip";
import { AccessSection } from "@/components/marketing/sections";
import { WindowAct } from "@/components/marketing/WindowAct";

/**
 * Landing B — the MERGED candidate: B's framed window containing the whole
 * app, driven by C's scroll. (A and C stand unchanged for comparison.)
 *
 * The sequence is the argument, one idea per screen:
 *
 *   1  the promise (display headline);
 *   2  the board, live in the window — the product before any explanation,
 *      and captioned, because the scene the page bets on cannot be the one
 *      with nothing to read on it;
 *   3  the offer lands — the receipt strip announces it, then the window's
 *      row travels to offered, on its own (a WIN, deliberately: the page's
 *      flagship moment must never turn the visitor down);
 *   4  the mail behind it — the detail pane docks open (the approved
 *      composition) once the row has landed, and the strip's "not every
 *      reply says its verdict ↓" hands off to the harder case;
 *   5  the descent takes that harder case — the interview invitation whose
 *      preview reads as a routine acknowledgment — and makes ONE claim in
 *      two beats: first the mail as Gmail hands it over, the preview visibly
 *      ending where the inviting begins; then the SPLIT VERDICT — the same
 *      body classified live twice — the one artifact on the page nothing
 *      else can fake, placed after the act it explains;
 *   6  the benchmark that chose what ships;
 *   7  what is kept (retention), the email stripped to its record;
 *   8  the seats, and the one CTA — the page's single conversion surface,
 *      reachable from the nav at any depth ("Get access").
 *
 * Screens 2–4 are `WindowAct` (the window pins, scroll advances the scene);
 * 5–7 are `ClaimsDescent` — same copy, same staging as /landing-c. The act
 * and the descent are two cases from the same board on purpose: the offer is
 * the promise kept (Larkspur), and the invitation is why keeping it takes
 * reading past the preview (Northstar, sitting in the interviewing group of
 * the very board the act plays on).
 */
export const metadata: Metadata = {
  title: "Landing B — the window, in motion",
  robots: { index: false, follow: false },
};

export default function LandingB() {
  return (
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav />

      {/* ---- hero: the headline at display scale -------------------------
          The paddings and the display bump are a FOLD budget, not taste: at
          1024×600 the board's summary strip plus one full application row
          need `pipeline-board` to start by ~466px, and this page's whole bet
          is that row being visible before anyone scrolls. The 7xl step waits
          for `xl` because at 1024 those extra ~25px of headline are exactly
          the row's margin. Re-measure on `next build && next start` if any
          of this moves — `next dev` cannot measure it. */}
      <section className="mx-auto w-full max-w-6xl px-6 pt-9 pb-4 sm:pt-11">
        <h1 className="max-w-4xl text-balance text-5xl font-semibold tracking-[-0.025em] text-strong sm:text-6xl xl:text-7xl">
          {HERO.headline}
        </h1>
        <p className="mt-4 max-w-xl text-balance text-lg text-muted">{HERO.subhead}</p>
      </section>

      {/* ---- the window act: the app proves it before the page explains -- */}
      <WindowAct />

      {/* ---- the descent: the email behind the act, one claim per screen - */}
      <ClaimsDescent />

      {/* The CTA's own evidence, beside the CTA. `ACCESS.noSeat` promises the
          fallback path is "parsed and classified in your browser", and until
          now that was the one sentence on the page with nothing behind it.
          Landing B only: A and C pass no exhibit and are unchanged. The clip
          keeps its caption beneath it here rather than beside it — this
          section's shell is `max-w-5xl`, which has no room for a second
          column at any width. */}
      <AccessSection
        exhibit={
          <ProductClip
            clip={CLIPS.importClassifies}
            name={FOOTAGE.import.name}
            caption={FOOTAGE.import.caption}
            className="max-w-3xl xl:grid-cols-1"
          />
        }
      />
      <ClosingAct />
      <MarketingFooter />
    </main>
  );
}
