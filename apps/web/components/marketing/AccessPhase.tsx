import { NEW_TAB } from "./chrome";
import { ACCESS } from "./copy";

/**
 * The landing's access phase — the same `ACCESS` copy the shared section
 * renders (imported, never rewritten), in the spine's own container.
 *
 * A and C keep `AccessSection` (sections.tsx) and are unchanged; this exists
 * so the one conversion surface sits on the same gutter as every phase above
 * it — the landing's 85rem spread since the 2026-08-20 widening
 * (`app/page.tsx` argues the cap) — rather than stepping in to the shared
 * section's narrower `max-w-5xl` block, which at 1152 and wider reads as the
 * ask having come from a different page.
 *
 * It carries the `#access` id here, where `AccessSection` is not mounted —
 * the nav's "Get access" anchor (`ACCESS_ANCHOR`) has exactly one target per
 * page, whichever staging renders it. `scroll-mt` clears the sticky nav, the
 * same offset the shared section uses.
 *
 * THE RAIL IS GONE, AND THAT IS THE HONEST ANSWER RATHER THAN A LOSS TAKEN
 * QUIETLY. This phase was built around a pinned exhibit: the `import-classifies`
 * recording, playing the exact path `ACCESS.noSeat` promises, beside the CTA
 * that promises it. The owner retired that recording (scripts/footage/clips.mjs
 * records why — it never showed the file being chosen, and it ran too fast to
 * read), and the page has no second recording to put in its place: the other
 * two are already mounted where they argue something, and moving one here
 * would be a rail holding whatever was nearest, which is the definition of
 * filler on a page whose whole claim is that each exhibit evidences the
 * sentence beside it. So the rail collapses instead of being filled.
 *
 * WHICH TAKES THE PACING WITH IT, and that is not tidying either. The two
 * beats used to be paced at `80vh` and then unpaced — and the docblock that
 * set those numbers said plainly what they were for: "THE FLOW COLUMN IS THE
 * RAIL'S RUNWAY. Sticky can only travel inside its containing block, so the
 * pin exists exactly to the extent the flowing side outruns the rail." With
 * no rail to outrun, a viewport-tall beat is a screen of empty column, so the
 * copy is content-paced: the constraint, then the path that needs no seat,
 * then the ask.
 *
 * The spine no longer misses the beat the retirement cost it — the descent
 * grew to five alternating rails on 2026-08-20 (R → L → R → L → R), so the
 * ask is simply the phase without an exhibit rather than a broken rhythm.
 * Putting a rail HERE still needs a recording of the import path worth
 * watching, not a rearrangement of the five that exist.
 */
export function AccessPhase() {
  return (
    <section id="access" className="column-ruled scroll-mt-20 border-t border-line-soft">
      <div className="mx-auto w-full max-w-[85rem] px-6 py-20 sm:py-24">
        <div className="max-w-xl">
          <p className="label-caps mb-4">{ACCESS.eyebrow}</p>
          <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
            {ACCESS.headline}
          </h2>
          {/* The ask's payoff sits ABOVE its evidence, which is the one place
              on the page a payoff line may. Every other phase earns its payoff
              from the exhibit beside it; this phase's evidence is the whole
              page above it, so the sentence that says what a seat is FOR
              belongs before the sentence about Google's cap. */}
          <p className="mt-5 text-strong">{ACCESS.payoff}</p>
          <p className="mt-4 text-muted">{ACCESS.cap}</p>
          <p className="mt-4 text-muted">{ACCESS.noSeat}</p>
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
      </div>
    </section>
  );
}
