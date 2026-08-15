import { QuietEnvelope } from "@/components/boot/QuietEnvelope";
import { QuietLine } from "@/components/boot/QuietLine";

/**
 * Instant pending state for /import — the Triage boot's quiet form, at the
 * drop zone's REAL measure.
 *
 * The box that used to stand here was `h-44`. The card it stands in for
 * measures 330px (verified at 1024 on a production build), so the page jumped
 * 154px the moment content arrived — the "and not to their size either" half
 * of the report. Nothing here declares a height any more: every box below
 * transcribes the class list of the box it replaces (`ImportMail`'s drop zone
 * is `rounded-xl border border-dashed px-6 py-12 sm:py-16`, its buttons are
 * `px-4 py-2 text-sm`), so the height is computed from the same padding and
 * the same type metrics the real card is computed from, and it cannot drift
 * when that card changes.
 *
 * WHICH BRANCH THIS AIMS AT. The route is dual-mode — shell-wrapped signed in,
 * standalone public page signed out — and a `loading.tsx` cannot know which is
 * coming without reading the session, which is the very wait it exists to
 * cover. So it aims at the signed-in branch: the shell's `PageHeader` band and
 * the page's own `mx-auto my-auto w-full max-w-3xl space-y-8` measure,
 * transcribed. That is the branch where a jump can be FELT — a soft navigation
 * from the rail holds the shell still and swaps only this pane. Signed out the
 * fallback paints onto a blank document, where the standalone page's own
 * header is 56px rather than this 36 and there is nothing on screen for it to
 * disagree with.
 *
 * Deliberately keeps `border-dashed`: it is the one thing that says "drop
 * target" rather than "plate", and at hairline weight it says it quietly.
 */
export default function ImportLoading() {
  return (
    <div
      aria-busy="true"
      // `aria-label` starting "Loading" is load-bearing beyond a11y: it is
      // half of BootOverlay's PENDING_SELECTOR, the signal that keeps the boot
      // loop on screen until no route-level pending surface is left.
      aria-label="Loading mail import"
      className="boot-quiet flex flex-1 flex-col"
    >
      {/* The `PageHeader` band, `lg`-only exactly like the real one: /import
          passes it no children, so below `lg` it renders nothing at all and
          TopBar carries the session edge instead. */}
      <div className="hidden justify-end lg:flex">
        <div className="h-9 w-9 rounded-lg border border-line" />
      </div>

      {/* The page's own wrapper, transcribed — `my-auto` centres the short
          pre-drop state in the scroll pane on both sides of the swap. */}
      <div className="mx-auto my-auto w-full max-w-3xl space-y-8">
        {/* `ImportMail`'s two resting boxes, in its own `space-y-6`. */}
        <div className="space-y-6">
          {/* The drop zone: the page's one action, and the classify envelope
              is alive at the centre of it. */}
          <div className="rounded-xl border border-dashed border-line-soft px-6 py-12 text-center sm:py-16">
            {/* `block`, matching the lucide `Mail` it replaces: Tailwind's
                preflight blocks every svg, so an inline box here would add a
                descender the real icon's line never has. */}
            <QuietEnvelope index={0} lit className="mx-auto block h-8 w-11" />
            <p className="mt-4 text-[15px]">
              <QuietLine className="w-56 border-line-strong" />
            </p>
            <p className="mt-1 text-[13px]">
              <QuietLine className="w-72" />
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <span className="rounded-lg border border-line-soft px-4 py-2 text-sm">
                <QuietLine className="w-20 border-line-strong" />
              </span>
              <span className="rounded-lg border border-line-soft px-4 py-2 text-sm">
                <QuietLine className="w-28" />
              </span>
            </div>
            <p className="mt-6 text-xs leading-relaxed">
              <QuietLine className="w-80 max-w-full" />
            </p>
          </div>

          {/* The on-device note. Two line boxes because the sentence wraps to
              two at this measure. */}
          <div className="rounded-xl border border-line-soft px-4 py-3 text-sm">
            <p>
              <QuietLine className="w-full max-w-[38rem] border-line-strong" />
            </p>
            <p>
              <QuietLine className="w-40" />
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
