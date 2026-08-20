import { AccessPhase } from "@/components/marketing/AccessPhase";
import { ClaimsDescent } from "@/components/marketing/ClaimsDescent";
import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";
import { ClosingAct } from "@/components/marketing/ClosingAct";
import { HERO } from "@/components/marketing/copy";
import { WindowAct } from "@/components/marketing/WindowAct";

/**
 * The landing (`/`) — the pinned-scroll composition, and the pin IS the page.
 * It was built and chosen as candidate B (it served at `/landing-b` while the
 * choice was open) for the fixed-scroll language, and the build where it
 * carried one phase and lapsed into ordinary sections for the rest was
 * rejected; the whole page speaks it now, as one alternating spine. It
 * replaces the project-shaped case study that used to live here — model
 * names, rule counts and test counts are the System Card's register, not a
 * product landing's. (`/landing-a` and `/landing-c` stand unchanged, and
 * noindex, as the comparison set.)
 *
 *   1  the promise (display headline);
 *   2  the WINDOW ACT — the framed app pins full-stage and the visitor's
 *      scroll advances the scene inside it: the resting board, the offer
 *      landing (a WIN, deliberately), the pane docking on the mail behind
 *      it, the camera tilting up to the pane's own chrome;
 *   3  the descent (`ClaimsDescent`) — three phases, each one column PINNED
 *      while the other flows past, the pinned side switching at every phase
 *      boundary: the email rides the RIGHT rail for the verdict claim, the
 *      rules recording rides the LEFT rail for the decision claim, the sync
 *      recording rides the RIGHT rail for retention while the kept record
 *      collapses in the flow;
 *   4  access (`AccessPhase`) — the same language, LEFT rail: the import
 *      recording pinned beside the page's one conversion surface, which the
 *      nav's "Get access" reaches at any depth;
 *   5  the CLOSING ACT — full-stage pin again, and the one surface that
 *      plays on its own clock: once the scene is in view it runs to
 *      completion, slowed, while the pin holds the page (see ClosingAct for
 *      why it cannot be outrun).
 *
 * Full frame → right → left → right → left → full frame: the alternation is
 * the page's rhythm, the side-switch is what a phase change looks like, and
 * no section drops out of the language between the bookends.
 *
 * NO `metadata` EXPORT, deliberately. This page INHERITS the root layout's
 * title ("Applied — your inbox, made legible"), description, OpenGraph and
 * Twitter cards — that block is written for the site root and a page-level
 * `title` string here would only get the layout's "%s · Applied" template
 * appended to it. It also carries NO `robots` key: the candidate route was
 * `index: false` while the choice was open, and `/` is the one landing that
 * must be indexable. `tests/unit/landing-variants.test.mjs` holds both halves
 * — A and C noindex, this page not.
 */
export default function Landing() {
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

      {/* The CTA in the spine's own language — the import recording pinned
          beside the promise it evidences. A and C keep the shared
          `AccessSection` and are unchanged. */}
      <AccessPhase />
      <ClosingAct />
      <MarketingFooter />
    </main>
  );
}
