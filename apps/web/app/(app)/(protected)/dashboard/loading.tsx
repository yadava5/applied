import type { CSSProperties } from "react";

import { QuietEnvelope } from "@/components/boot/QuietEnvelope";

/**
 * Instant pending state for /dashboard — the Triage boot's quiet form
 * (boot-demos variant 01): hairline outlines at the loaded board's exact
 * geometry, with the classify signal travelling the worklist rows instead of
 * pulsing theme-colored blobs. Same band/spine/row sizes as before (the
 * loaded SyncBar header, the h-8 stage buttons + h-64 pulse column, nine
 * h-10 worklist rows), so the swap to content never reflows the page.
 */
export default function DashboardLoading() {
  return (
    <section
      className="boot-quiet page-locked flex flex-col gap-3 lg:min-h-0 lg:flex-1"
      aria-busy="true"
      aria-label="Loading dashboard"
      style={{ "--boot-quiet-step": "0.6s" } as CSSProperties}
    >
      {/* Header: title + inline subtitle on one baseline, sync cluster right —
          the same single-line band the loaded SyncBar renders. */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <div className="h-7 w-32 rounded-lg border border-line-strong" />
          <div className="h-3 w-56 rounded border border-line" />
        </div>
        <div className="h-9 w-40 rounded-lg border border-line" />
      </div>

      {/* No stand-in for the notification chip (#212): at `lg`+ it overlays
          the header row and costs no height, so the skeleton's geometry is
          already the loaded one's. */}

      {/* Spine (stages + pulse column) + worklist — the same geometry the
          loaded board renders into. */}
      <div className="flex min-h-0 flex-1 gap-5">
        <div className="hidden w-52 shrink-0 flex-col gap-2 lg:flex">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 rounded-lg border border-line-soft" />
          ))}
          {/* The pulse's instrument column under the stage buttons. */}
          <div className="mt-2 h-64 rounded-lg border border-line-soft" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2 overflow-hidden">
          {Array.from({ length: 9 }).map((_, i) => (
            <div
              key={i}
              className="flex h-10 items-center gap-3 rounded-lg border border-line-soft px-3"
            >
              <QuietEnvelope index={i} lit={i === 0} className="h-[13px] w-[18px]" />
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <span className="h-2 w-2/5 rounded-full border border-line-strong" />
                <span className="h-1.5 w-1/4 rounded-full border border-line" />
              </div>
              <span className="h-5 w-14 shrink-0 rounded-full border border-line-strong" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
