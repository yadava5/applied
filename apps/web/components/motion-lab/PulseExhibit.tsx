"use client";

import { useEffect, useState } from "react";

import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { showcaseApplications } from "@/components/marketing/showcase";
import { todayISO } from "@/lib/dashboard/age";
import { toPulseRow, type PulseRow } from "@/lib/dashboard/summary";

/**
 * Candidate 07 — a live micro-exhibit: the product's own pulse band mounted
 * over the showcase fixture. Momentum, age, deadlines, provenance — every
 * number below is computed by the shipped component from the rows at mount,
 * against the visitor's own clock. It is the "small boxes = animations of
 * different features" idea done as live computation instead of video.
 *
 * Mounted client-side only (the `rows` gate) for the same hydration reason
 * MarketingBoard is: the fixture dates resolve against the caller's clock,
 * and a server-rendered "today" can differ from the visitor's. The SSR/no-JS
 * frame is the reserved box with the label — composed, honest, no CLS.
 *
 * The band's click-throughs normally narrow the board's worklist; no board
 * is mounted here, so the filter callback is a no-op and the caption says so.
 */
export function PulseExhibit() {
  const [rows, setRows] = useState<PulseRow[] | null>(null);
  useEffect(() => {
    // Scheduled rather than set inline — a mount effect must not set state
    // synchronously (react-hooks/set-state-in-effect; trackProgress's idiom).
    const frame = requestAnimationFrame(() =>
      setRows(showcaseApplications(todayISO()).map(toPulseRow)),
    );
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="max-w-3xl">
      <div className="rounded-xl border border-line-soft bg-surface px-4 py-3">
        {rows ? (
          <PipelinePulse
            applications={rows}
            total={rows.length}
            needsReview={0}
            onFilter={() => {}}
          />
        ) : (
          <div className="flex h-24 items-center">
            <span className="label-caps">Live pulse — computing from the fixture…</span>
          </div>
        )}
      </div>
      <p className="mt-3 text-xs leading-relaxed text-dim">
        The shipped pulse band over the landing&apos;s showcase rows, computed at mount against
        your clock. The cells expand (the product&apos;s own interaction); their filter
        click-throughs are no-ops here because no worklist is mounted beneath them.
      </p>
    </div>
  );
}
