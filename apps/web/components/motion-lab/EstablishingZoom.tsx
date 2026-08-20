"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";

import { BoardStill } from "@/components/marketing/BoardStill";
import { useWideViewport, trackProgress } from "@/components/marketing/scrub";

/**
 * Candidate 01 — the establishing zoom, on the real board.
 *
 * The live `MarketingBoard` (the shipped `PipelineBoard` over the showcase
 * fixture — same mount as the landing's window act, resting state) starts at
 * 0.8×, whole pipeline in frame, and scrubs to 1.0× across the first half of
 * this section's runway. Real DOM at every scale, so there is nothing here
 * that CAN be a recording — drag a card mid-zoom if you doubt it.
 *
 * Honesty of the frame at rest: the SSR/no-JS/reduced-motion state is the
 * board at 1.0×, which is simply the product. The scrub only runs when the
 * viewport is wide enough for the board to exist (`lg`, same rule as the
 * landing) and motion is allowed; below `lg` this renders `BoardStill`,
 * exactly as the landing does.
 */
const MarketingBoard = dynamic(
  () => import("@/components/marketing/MarketingBoard").then((m) => m.MarketingBoard),
  { ssr: false },
);

/** Scale at the runway's start — whole pipeline visible in one frame. */
const SCALE_FROM = 0.8;

/** The zoom completes halfway through the runway; the back half holds 1.0×
 *  so the reader arrives at product scale before the section releases. */
const ZOOM_SPAN = 0.5;

export function EstablishingZoom() {
  const wide = useWideViewport();
  const runwayRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const runway = runwayRef.current;
    if (!wide || !runway) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // The act's own window ({from:0,to:1}): progress 0 the moment the sticky
    // frame engages, so the board HOLDS 0.8× while the section arrives and
    // spends the first half of the pinned runway reaching 1.0×. A
    // viewport-share window here left progress at 0.43 by the time the frame
    // was fully on screen — the zoom was over before anyone saw it.
    return trackProgress(runway, { from: 0, to: 1 }, (p) => {
      const t = Math.min(1, p / ZOOM_SPAN);
      const scale = SCALE_FROM + (1 - SCALE_FROM) * t;
      if (stageRef.current) stageRef.current.style.transform = `scale(${scale})`;
    });
  }, [wide]);

  if (!wide) {
    return (
      <div>
        <BoardStill />
        <p className="mt-3 text-xs text-dim">
          The zoom needs the wide board — view this plate at 1024px or above.
        </p>
      </div>
    );
  }

  return (
    <div ref={runwayRef} className="h-[170vh]">
      <div className="sticky top-14">
        <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
          <div className="flex items-center gap-2 border-b border-line-soft px-5 py-2">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
            <span className="label-caps">Live fixture data — the shipped board, not a video</span>
          </div>
          <div className="h-[560px] overflow-hidden bg-background">
            <div
              ref={stageRef}
              style={{ transform: "scale(1)", transformOrigin: "50% 0%" }}
              className="p-5"
            >
              <MarketingBoard />
            </div>
          </div>
        </div>
        <p className="mt-3 text-xs text-dim">
          Scroll drives the scale: 0.8× as the frame arrives, 1.0× by the runway&apos;s midpoint.
          Scroll back up and it un-zooms — position, not a timeline.
        </p>
      </div>
    </div>
  );
}
