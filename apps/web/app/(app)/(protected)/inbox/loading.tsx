import type { CSSProperties } from "react";

import { QuietEnvelope } from "@/components/boot/QuietEnvelope";
import { QuietLine } from "@/components/boot/QuietLine";
import { LOCKED_PAGE_CLASS } from "@/components/shell/geometry";
import { cn } from "@/lib/utils";

/**
 * Instant pending state for /inbox — the Triage boot's quiet form at the
 * loaded Filed view's geometry: the `PageHeader` band, `FiledMailList`'s
 * filter/search plate, then ONE list plate of divider rows, with the classify
 * signal travelling them. A cold navigation here previously answered the click
 * with nothing until `GET /applications/mail` came back (700–1150 ms of origin
 * time, #203).
 *
 * `LOCKED_PAGE_CLASS` is imported rather than repeated: the loaded page
 * declares the same constant, so the pane's scroll math is identical on both
 * sides of the swap by construction and cannot drift the way two hand-copied
 * literals can.
 *
 * SIZE, which the previous version got wrong. Rows were `h-11` (44px). A real
 * filed row measures 93px — two lines of subject/sender plus the wrapped meta
 * line — so seven of them were 343px short and every divider sat somewhere
 * content would not be. Nothing here declares a height any more: each box
 * transcribes the class list of the box it replaces (`px-1 py-3` rows,
 * `px-3 py-1 text-xs` chips, the `border-t pt-3` search line), so the heights
 * come out of the same padding and type metrics the real list is measured
 * from. Verified at 1024 against `FiledMailList` rendered at the width the
 * shell gives it; the route needs a session, so it is the component that was
 * measured, not this page.
 *
 * No pager stand-in, deliberately: `FILED_PAGE_SIZE` is 50 and the account
 * holds 32 stored messages, so the loaded list renders no pager at all — one
 * was measured at zero.
 */
export default function InboxLoading() {
  return (
    <section
      aria-busy="true"
      // "Loading…" is half of BootOverlay's PENDING_SELECTOR, not just a label.
      aria-label="Loading inbox"
      className={cn("boot-quiet relative", LOCKED_PAGE_CLASS)}
      style={{ "--boot-quiet-step": "0.6s" } as CSSProperties}
    >
      {/* The `PageHeader` band: the Filed/Live-scan switch left, the standing
          privacy link beside the `⋯` session menu — whose square only exists
          at `lg`, exactly like the loaded row. */}
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-lg border border-line-soft p-0.5">
            <span className="rounded-md px-3 py-1.5 text-xs">
              <QuietLine className="w-8 border-line-strong" />
            </span>
            <span className="rounded-md px-3 py-1.5 text-xs">
              <QuietLine className="w-14" />
            </span>
          </div>
          <span className="text-xs">
            <QuietLine className="w-56" />
          </span>
        </div>
        <div className="hidden h-9 w-9 shrink-0 rounded-lg border border-line lg:block" />
      </div>

      {/* `FiledMailList`'s own column — its `gap-4`, not the page's `gap-3`. */}
      <div className="flex flex-col gap-4 lg:min-h-0 lg:flex-1">
        {/* The filter/search plate: the category chips, then the search line. */}
        <div className="space-y-3 rounded-xl border border-line-soft p-4 lg:shrink-0">
          <div className="flex flex-wrap items-center gap-1.5">
            {/* `inline-block`, not the chips' own `inline-flex`: a flex parent
                has no line box, so the strut a QuietLine stands on would be
                gone and the chip would collapse to 18px against the loaded
                26. */}
            {["w-8", "w-14", "w-16", "w-14", "w-10"].map((w, i) => (
              <span
                key={i}
                className="inline-block rounded-full border border-line px-3 py-1 text-xs"
              >
                <span
                  className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-line-strong align-middle"
                  aria-hidden="true"
                />
                <QuietLine className={w} />
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line-soft pt-3">
            <div className="h-[34px] min-w-0 flex-1 basis-48 rounded-lg border border-line" />
            <span className="rounded-lg border border-line px-3 py-1.5 text-xs">
              <QuietLine className="w-8" />
            </span>
          </div>
        </div>

        {/* The list plate. `overflow-hidden` rather than the loaded
            `overflow-y-auto`: a pending surface must never be scrollable. */}
        <ul className="rounded-xl border border-line-soft px-3 lg:min-h-0 lg:overflow-hidden">
          {Array.from({ length: 8 }).map((_, i) => (
            <li
              key={i}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-soft px-1 py-3 last:border-b-0"
            >
              <div className="flex min-w-0 basis-full items-center gap-3 sm:basis-0 sm:flex-1">
                <QuietEnvelope index={i} lit={i === 0} className="h-[14px] w-5" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    <QuietLine className="w-3/5 border-line-strong" />
                  </p>
                  <p className="text-xs">
                    <QuietLine className="w-2/5" />
                  </p>
                </div>
              </div>
              <span className="w-24 text-xs">
                <span
                  className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-line-strong align-middle"
                  aria-hidden
                />
                <QuietLine className="w-10" />
              </span>
              <span className="h-1 w-14 shrink-0 rounded-full border border-line" aria-hidden />
              <span className="w-10 text-right font-mono text-[11px]">
                <QuietLine className="w-7" />
              </span>
              <span className="hidden w-12 text-right font-mono text-[10px] md:inline">
                <QuietLine className="w-9" />
              </span>
              {/* The meta line the loaded row wraps onto — `basis-full`, so it
                  is what makes a filed row 93px rather than 61. */}
              <span className="basis-full text-[11px]">
                <span className="inline-block rounded-full border border-line px-2 py-1 text-[11px]">
                  <QuietLine className="w-20" />
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
