import type { CSSProperties } from "react";

import { QuietEnvelope } from "@/components/boot/QuietEnvelope";

/**
 * Instant pending state for /inbox — the Triage boot's quiet form: hairline
 * outlines at the loaded Filed view's exact geometry (#297's shape: the
 * PageHeader band, the filter/search plate, then ONE list plate with
 * divider rows — not a stack of separate plates), with the classify signal
 * travelling the rows. `page-locked` matches the loaded page so the pane's
 * scroll math never flips during the swap. A cold navigation here previously
 * answered the click with nothing until `GET /applications/mail` came back
 * (700–1150 ms of origin time, #203). Warm navigations inside the
 * router-cache window skip this entirely.
 */
export default function InboxLoading() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading inbox"
      className="boot-quiet page-locked relative flex flex-col gap-3 lg:min-h-0 lg:flex-1"
      style={{ "--boot-quiet-step": "0.6s" } as CSSProperties}
    >
      {/* The PageHeader band: ViewSwitch left; the ⋯ session menu's square
          only exists at lg, exactly like the loaded row. */}
      <div className="flex items-center justify-between gap-3">
        <div className="h-8 w-40 rounded-lg border border-line-strong" />
        <div className="hidden h-9 w-9 rounded-lg border border-line lg:block" />
      </div>
      {/* The filter/search plate: chips row, then the search line. */}
      <div className="space-y-3 rounded-xl border border-line-soft p-4 lg:shrink-0">
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-6 w-16 rounded-full border border-line" />
          ))}
        </div>
        <div className="flex items-center gap-3 border-t border-line-soft pt-3">
          <div className="h-8 min-w-0 flex-1 basis-48 rounded-lg border border-line" />
          <div className="h-8 w-16 rounded-lg border border-line" />
        </div>
      </div>
      {/* The list plate: divider rows at the loaded rows' height. */}
      <div className="rounded-xl border border-line-soft px-3 lg:min-h-0 lg:overflow-hidden">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="flex h-11 items-center gap-3 border-b border-line-soft px-1 last:border-b-0"
          >
            <QuietEnvelope index={i} lit={i === 0} className="h-[14px] w-5" />
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <span className="h-2 w-2/5 rounded-full border border-line-strong" />
              <span className="h-1.5 w-1/5 rounded-full border border-line" />
            </div>
            <span className="h-5 w-16 shrink-0 rounded-full border border-line-strong" />
          </div>
        ))}
      </div>
    </section>
  );
}
