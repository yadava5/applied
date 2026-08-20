import { NEW_TAB } from "./chrome";
import { ACCESS, FOOTAGE } from "./copy";
import { CLIPS } from "./footage";
import { ProductClip } from "./ProductClip";

/**
 * Landing B's access phase — the same `ACCESS` copy the shared section
 * renders (imported, never rewritten), restaged in the page's spine language:
 * one column pinned, the other flowing, with the pinned side switched from
 * the retention phase before it (see `ClaimsDescent`'s docblock for the whole
 * run). The pinned exhibit is the recording of the import page doing exactly
 * what `ACCESS.noSeat` promises — "parsed and classified in your browser" —
 * beside the CTA that promises it, which is the one claim on the page that
 * used to have nothing behind it.
 *
 * A and C keep `AccessSection` (sections.tsx) and are unchanged; this exists
 * so B's one conversion surface speaks the same language as every phase
 * around it instead of dropping back to a static section for the ask.
 *
 * It carries the `#access` id on B, where `AccessSection` is not mounted —
 * the nav's "Get access" anchor (`ACCESS_ANCHOR`) has exactly one target per
 * page, whichever staging renders it. `scroll-mt` clears the sticky nav, the
 * same offset the shared section uses.
 *
 * THE FLOW COLUMN IS THE RAIL'S RUNWAY. Sticky can only travel inside its
 * containing block, so the pin exists exactly to the extent the flowing side
 * outruns the rail — and a first cut of this phase paced the copy as one
 * `75vh` screen, which left the section the rail's own height and the pin
 * with zero range: the clip translated 1:1 with scroll and at 768 its chrome
 * strip (with the play/pause control) cropped above the fold while the body
 * was still on screen. The same crop the board rework existed to kill. So
 * the copy is paced like every phase before it — the descent's claim /
 * micro-beat grammar, `80vh` then `60vh`, `lg`-only because below `lg` there
 * is no rail to pace against and the stacked twin already reads right. The
 * two beats are the two beats the copy actually has: the constraint
 * (`ACCESS.cap` — one hundred seats, invited one at a time) and the path
 * that needs no seat (`ACCESS.noSeat` + the CTA), so the ask arrives as its
 * own moment with the recording of exactly that path still pinned beside it.
 */
export function AccessPhase() {
  return (
    <section id="access" className="scroll-mt-20 border-t border-line-soft">
      <div className="mx-auto grid w-full max-w-6xl gap-x-16 px-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
        {/* Slack reclaimed to the phase's closing line, the same negative
            bottom margin the descent's clip rails carry — `ClaimsDescent`'s
            decision rail argues it. `31rem` is this exhibit's measured height
            (505px at 1024, 509 at 1512): the import caption is the longest on
            the page, so this is the tallest of the three rails and the one
            with the least slack to take back — at 1024×643 it has almost none
            and the `min(0px, …)` floor holds it where it is. */}
        <div className="hidden lg:block">
          <div className="pointer-events-none sticky top-20 mb-[min(0px,calc(3.5rem_+_(31rem_+_8rem_-_100dvh)/2))] flex min-h-[calc(100dvh-5rem)] flex-col justify-center py-6">
            <ProductClip
              stack
              className="pointer-events-auto"
              clip={CLIPS.importClassifies}
              name={FOOTAGE.import.name}
              caption={FOOTAGE.import.caption}
            />
          </div>
        </div>
        <div className="flex min-h-[75vh] flex-col justify-center py-16 lg:block lg:min-h-0 lg:py-0">
          {/* Beat one: the constraint. */}
          <div className="flex flex-col justify-center lg:min-h-[80vh] lg:py-16">
            <p className="label-caps mb-4">{ACCESS.eyebrow}</p>
            <h2 className="max-w-xl text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              {ACCESS.headline}
            </h2>
            <p className="mt-5 max-w-xl text-muted">{ACCESS.cap}</p>
          </div>
          {/* Beat two: the path that needs no seat, and the ask. `mt-4`
              below `lg` keeps the paragraph rhythm the single-screen staging
              had (the old `space-y-4`); at `lg` the beat box owns the gap.

              It is the phase's LAST beat, so at `lg` it is unpaced — `py-20`,
              the descent's own closing line — rather than centred in `60vh`.
              Centred, the ask ended 119px above the section's rule at 1024 and
              223 at 1512 while the rail's exhibit ended at 24, so the phase
              closed with its two columns at visibly different heights. Unpaced
              they close on the same line at every viewport, and the slack that
              did nothing but hold them apart comes out.

              THIS SHORTENS THE RUNWAY 5c91e80 BOUGHT, and that is the one
              trade in this change: beat one still paces at `80vh`, but the
              rail's runway measures 274px at 1024×768 against the 387px that
              commit recorded — 26% of the band, against the gate's 20% floor
              and against the 0% the defect it fixed read. The pin engages;
              it engages over less. */}
          <div className="flex flex-col justify-center lg:py-20">
            <p className="mt-4 max-w-xl text-muted lg:mt-0">{ACCESS.noSeat}</p>
            <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
              <a
                href="/import"
                {...NEW_TAB}
                className="inline-flex min-h-11 items-center rounded-lg bg-strong px-5 py-2.5 font-medium text-background transition-opacity hover:opacity-90"
              >
                {ACCESS.cta} <span aria-hidden className="ml-2">→</span>
              </a>
              <span className="text-sm text-dim">
                {ACCESS.aside}{" "}
                <a
                  href={ACCESS.seatHref}
                  className="text-muted underline-offset-4 hover:text-strong hover:underline"
                >
                  {ACCESS.seatLink}
                </a>
              </span>
            </div>
          </div>
          <div className="mt-10 lg:hidden">
            <ProductClip
              stack
              clip={CLIPS.importClassifies}
              name={FOOTAGE.import.name}
              caption={FOOTAGE.import.caption}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
