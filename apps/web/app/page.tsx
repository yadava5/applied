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
 *   2  the WINDOW ACT — the workday oner (the owner's 01a pick): the framed
 *      app pins full-stage and one continuous take plays through a real
 *      working session on the real board — the pulse opens, a day bar is
 *      pressed, the board narrows, Kestrel's row opens on its mail trail,
 *      the filter clears — on the closing act's pin-and-play clock, pausable
 *      and disarmed by reduced motion (`WindowAct` / `OnerStage`);
 *   3  the descent (`ClaimsDescent`) — FIVE phases now (the owner's call,
 *      2026-08-20: "five or six boxes aside from the oner", sides strictly
 *      alternating), each one column PINNED while the other flows past, and
 *      the rails running as TAKES — narrated, autoplaying, pausable — the
 *      way the owner picked them off the motion lab: the email plays raw →
 *      split → dissolve → the kept record on the RIGHT (02b), the rules
 *      recording rides the LEFT as the page's one BIG box, the held mail
 *      settles into the real review queue on the RIGHT (08c), the tracked
 *      "ride the letter" recording rides the LEFT against the hero's own
 *      promise (03c-i), and the sync recording rides the RIGHT for
 *      retention while the kept record collapses in the flow;
 *   4  access (`AccessPhase`) — the page's one conversion surface, which the
 *      nav's "Get access" reaches at any depth. It HAD a left rail, pinning
 *      the import recording beside the promise that recording evidenced;
 *      the owner retired that clip on 2026-08-20 (scripts/footage/clips.mjs
 *      says why) and the phase collapsed to a single column rather than
 *      borrow another phase's exhibit to keep the rail occupied;
 *   5  the CLOSING ACT — full-stage pin again, playing on its own clock:
 *      once the scene is in view it runs to completion, slowed, while the
 *      pin holds the page (see ClosingAct for why it cannot be outrun).
 *
 * Full frame → R → L → R → L → R → the ask → full frame. The alternation is
 * the page's rhythm and the side-switch is what a phase change looks like;
 * the ask stays the one beat without an exhibit — putting one back needs a
 * recording of the import path worth watching, not a rearrangement of the
 * five the page already has, each of which is where it is because of the
 * sentence beside it.
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
    /* ONE GUTTER, 85rem, THE WHOLE PAGE (the owner's edit, 2026-08-20: "we
       have that much of space to use, use that"). `max-w-6xl` capped every
       surface at 1152 and threw 350px away at the 1512 he works at, while
       the descent's exhibits sat in 30rem boxes — the page went wide for
       nothing and narrow for its evidence. Every document surface on `/` —
       nav, hero, the window act's frame, the descent's grids, the ask, the
       closing act's seat, the footer — now shares one 85rem (1360px) cap:
       at 1512 that is 76px of margin a side instead of 180, at 1024 it
       changes NOTHING (976 usable was already under both caps, and the fold
       budgets below are measured there), and past 1512 it stops. It stops
       because the parts stop honestly: the descent's clip exhibits cap at
       the width their 1152px encodes can fill without fabricating pixels,
       and the prose caps at a readable measure (`ClaimsDescent` derives
       both) — a wider gutter past that would only re-open the dead margin
       this edit removes. A and C keep `max-w-6xl`; the fluid spread is this
       staging's. */
    <main className="flex flex-col bg-background text-foreground">
      <MarketingNav wide />

      {/* ---- hero: the headline at display scale -------------------------
          The paddings and the display bump are a FOLD budget, not taste: at
          1024×600 the board's summary strip plus one full application row
          need `pipeline-board` to start by ~466px, and this page's whole bet
          is that row being visible before anyone scrolls. The 7xl step waits
          for `xl` because at 1024 those extra ~25px of headline are exactly
          the row's margin. Re-measure on `next build && next start` if any
          of this moves — `next dev` cannot measure it. */}
      <section className="mx-auto w-full max-w-[85rem] px-6 pt-9 pb-4 sm:pt-11">
        <h1 className="max-w-4xl text-balance text-5xl font-semibold tracking-[-0.025em] text-strong sm:text-6xl xl:text-7xl">
          {HERO.headline}
        </h1>
        <p className="mt-4 max-w-xl text-balance text-lg text-muted">{HERO.subhead}</p>
      </section>

      {/* ---- the window act: the app proves it before the page explains -- */}
      <WindowAct />

      {/* ---- the descent: the email behind the act, one claim per screen - */}
      <ClaimsDescent />

      {/* The CTA on the spine's own gutter. A and C keep the shared
          `AccessSection` and are unchanged. */}
      <AccessPhase />
      <ClosingAct />
      <MarketingFooter wide />
    </main>
  );
}
