import type { CSSProperties } from "react";

import { QuietEnvelope } from "@/components/boot/QuietEnvelope";
import { QuietLine } from "@/components/boot/QuietLine";
import { LOCKED_PAGE_CLASS } from "@/components/shell/geometry";
import { cn } from "@/lib/utils";

/** The stage groups the worklist draws — enough to fill the pane at 1024 and
 *  then some, because the pane clips and the real board's group count depends
 *  on the account, not on this file. */
const GROUPS = [4, 3, 2];

/**
 * Instant pending state for /dashboard — the Triage boot's quiet form
 * (boot-demos variant 01): hairline outlines at the loaded board's geometry,
 * with the classify signal travelling the worklist rows instead of pulsing
 * theme-colored blobs.
 *
 * WHY THE PAGE CANNOT REFLOW, stated as something checkable rather than as a
 * promise. The root is `LOCKED_PAGE_CLASS` — the same constant `page.tsx`
 * declares, imported rather than hand-copied, which is the whole reason
 * `geometry.ts` exists. At `lg` that pins this surface to the shell's pane
 * (`AppShellFrame`'s `lg:has-[.page-locked]:min-h-0` collapses the wrapper's
 * minimum), so both sides of the swap are exactly one pane tall and the
 * document's height is not a function of what is inside. Below `lg` the lock
 * releases for both, and the page flows.
 *
 * That leaves the geometry INSIDE the pane, which is where the previous
 * version was wrong: it drew a `w-52` stage spine and a `h-64` pulse column
 * beside the rows. The signed-in board renders neither. `PipelineBoard` at
 * `variant="locked"` portals its stage lens into the shell's rail
 * (`railStages`), so the in-board `aside` is skipped entirely and the worklist
 * takes the full measure — the skeleton was shifting every row 228px right of
 * where content would land. The pulse is a full-width band ABOVE the rows,
 * `hidden lg:grid lg:grid-cols-4`, measured at 54.5px on a production build at
 * 1024, and that is what stands here now.
 *
 * Everything below transcribes the class list of the box it replaces, so the
 * heights are computed from the same padding and type metrics as the real
 * ones. Nothing declares a row height. The band and row numbers were measured
 * against the real `SyncBar`/`PipelinePulse`/`PipelineBoard` rendered at the
 * width the shell gives them at 1024; the route itself needs a session, so it
 * is those components that were measured, not this page.
 */
export default function DashboardLoading() {
  return (
    <section
      className={cn("boot-quiet", LOCKED_PAGE_CLASS)}
      aria-busy="true"
      // Starting "Loading" is load-bearing beyond a11y: it is half of
      // BootOverlay's PENDING_SELECTOR, the signal that holds the boot loop on
      // screen until no route-level pending surface is left.
      aria-label="Loading dashboard"
      style={{ "--boot-quiet-step": "0.6s" } as CSSProperties}
    >
      {/* `SyncBar`'s header row: title + inline subtitle on one baseline, the
          sync cluster right. The loaded row's siblings inside SyncBar are
          `sr-only` at rest (absolute, out of flow), so this row IS the bar. */}
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="shrink-0 text-sm font-semibold">
          <QuietLine className="w-28 border-line-strong" />
        </h2>
        <span className="shrink-0 text-[13px]">
          <QuietLine className="w-52" />
        </span>
        {/* The sync cluster. `h-9`, not a transcribed `px-3 py-2` control:
            `PageHeader`'s own comment records `data-sync-header-row` measured
            at height 36 on all four routes at 1024 and 1383, and 36 is what
            the `⋯` trigger beside it is — so the row is pinned by the one
            element whose height is stated in the source. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span className="h-9 w-28 rounded-lg border border-line-soft" />
          <div className="h-9 w-9 rounded-lg border border-line" />
        </div>
      </div>

      {/* `PipelineBoard`'s own column. No stage spine and no chip row: in the
          shell both live in the rail at this width. */}
      <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-1">
        {/* The pulse band — four cells, full width, `lg`-up, on the same
            `border-y` the real band draws. */}
        <div className="hidden border-y border-line-soft lg:grid lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="min-w-0 border-line-soft px-3 py-2 first:pl-0 last:pr-0 [&+&]:border-l"
            >
              <div className="grid gap-1">
                <span className="label-caps">
                  <QuietLine className="w-28" />
                </span>
                <span className="text-[11px]/4">
                  <QuietLine className="w-20 border-line-strong" />
                </span>
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-4 lg:min-h-0 lg:flex-1 lg:flex-row lg:gap-5">
          <div className="flex min-w-0 flex-1 flex-col gap-3 lg:min-h-0">
            {/* The worklist — the dashboard's one scroll region when loaded,
                clipped here so the quiet form can never grow the pane. */}
            <div className="space-y-4 lg:min-h-0 lg:flex-1 lg:overflow-hidden lg:pr-1">
              {GROUPS.map((count, group) => (
                <section key={group} className="rounded-xl">
                  {/* The sticky stage heading. */}
                  <div className="mb-2 flex items-baseline gap-2 px-1 lg:py-1">
                    <span className="label-caps">
                      <QuietLine className="w-20" />
                    </span>
                    <span className="font-mono text-xs">
                      <QuietLine className="w-4" />
                    </span>
                    <span className="h-px flex-1 bg-line-soft" aria-hidden="true" />
                  </div>
                  <ul className="space-y-1.5">
                    {Array.from({ length: count }).map((_, row) => (
                      <li
                        key={row}
                        className="flex flex-col gap-y-1.5 rounded-lg border border-line-soft py-2 pl-3 pr-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3"
                      >
                        <div className="flex min-w-0 items-center gap-3 sm:flex-1 sm:basis-56">
                          <QuietEnvelope
                            index={group * 4 + row}
                            lit={group === 0 && row === 0}
                            className="h-[13px] w-[18px]"
                          />
                          <span className="min-w-0 flex-1 text-sm leading-snug">
                            <QuietLine className="w-2/5 border-line-strong" />
                          </span>
                        </div>
                        <span className="text-sm leading-snug">
                          <QuietLine className="w-24" />
                        </span>
                        {/* The row's stage control — 24px, and what sets the
                            loaded row's 42px content height. */}
                        <span className="ml-auto h-6 w-28 shrink-0 rounded-md border border-line-soft" />
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
