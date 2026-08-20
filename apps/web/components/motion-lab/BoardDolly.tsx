"use client";

import { LayoutGroup } from "motion/react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { BoardStill } from "@/components/marketing/BoardStill";
import { latch, trackProgress, useWideViewport } from "@/components/marketing/scrub";

/**
 * 01b — the dolly: the establishing zoom grown into a full scroll-driven
 * shot. The board arrives at 0.78×, comes to product scale, the camera
 * travels DOWN the pipeline — three stages of real cards pass — and at the
 * foot the act's own verdict plays: Larkspur's offer commits, the row
 * glides to the offered group, and the mail behind it docks open.
 *
 * Everything is a function of scroll POSITION (the landing's own doctrine —
 * tempo.ts): the shot cannot outrun the reader's hand, and scrolling back
 * up reverses all of it, the verdict included. The camera itself eases
 * toward its position-derived target with a light damp, which is what makes
 * the travel read as a dolly rather than a scrub.
 */
const MarketingBoard = dynamic(
  () => import("@/components/marketing/MarketingBoard").then((m) => m.MarketingBoard),
  { ssr: false },
);

/** Marks, as shares of the pinned runway. Zoom, then travel, then the act. */
const M = { zoomEnd: 0.28, travelStart: 0.32, travelEnd: 0.58, verdict: 0.64, dock: 0.82 } as const;

const CAPTIONS = [
  "Scroll: the board rises to product scale.",
  "Dolly down the pipeline — assessment, interviews, offers, all real cards.",
  "A verdict lands: the offer moves its own row to the offered group.",
  "And the mail that moved it docks open. Scroll up — every beat reverses.",
] as const;

const FRAME_H = 560;

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function BoardDolly() {
  const wide = useWideViewport();
  const [reduced, setReduced] = useState(false);
  const runwayRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [verdict, setVerdict] = useState(false);
  const [docked, setDocked] = useState(false);
  const [zone, setZone] = useState(0);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const runway = runwayRef.current;
    if (!wide || reduced || !runway) return;
    let v = false;
    let k = false;
    return trackProgress(runway, { from: 0, to: 1 }, (p) => {
      const camera = cameraRef.current;
      const stage = stageRef.current;
      const frame = frameRef.current;
      if (!camera || !stage || !frame) return;
      const fw = frame.clientWidth;
      const sw = stage.offsetWidth;
      const sh = stage.offsetHeight;
      // Scale: 0.78 → 1 across the approach, held for the rest of the shot.
      const s = 0.78 + 0.22 * easeInOut(Math.min(1, p / M.zoomEnd));
      // Travel: top → foot across the middle of the runway, then hold. The
      // foot is bottom-aligned so the offered group (where the verdict
      // lands) owns the frame while the act plays.
      const travel = easeInOut(
        Math.min(1, Math.max(0, (p - M.travelStart) / (M.travelEnd - M.travelStart))),
      );
      const footY = Math.min(0, FRAME_H - s * sh);
      const y = footY * travel;
      const x = (fw - s * sw) / 2;
      camera.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${s})`;

      v = latch(p, M.verdict, v, 0.03);
      k = latch(p, M.dock, k, 0.03);
      setVerdict(v);
      setDocked(k);
      setZone(p < M.travelStart ? 0 : p < M.verdict ? 1 : p < M.dock ? 2 : 3);
    });
  }, [wide, reduced]);

  if (!wide) return <BoardStill />;

  if (reduced) {
    // No scrub, no runway: the settled board, which is simply the product.
    return (
      <div className="overflow-hidden rounded-2xl border border-line bg-surface">
        <div className="h-[560px] overflow-hidden bg-background p-4">
          <LayoutGroup id="lab-dolly-still">
            <MarketingBoard />
          </LayoutGroup>
        </div>
      </div>
    );
  }

  return (
    <div ref={runwayRef} className="h-[280vh]">
      <div className="sticky top-14">
        <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
          <div className="flex items-center gap-2 border-b border-line-soft px-4 py-2">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-viz-rules" />
            <span className="label-caps">
              live fixture data — the shipped board, driven by your scroll
            </span>
          </div>
          <div ref={frameRef} className="relative overflow-hidden bg-background" style={{ height: FRAME_H }}>
            <div ref={cameraRef} style={{ transformOrigin: "0 0" }}>
              <div ref={stageRef} className="p-4">
                {/* Same layout-id namespacing as TakeStage — see its note. */}
                <LayoutGroup id="lab-dolly">
                  <MarketingBoard verdict={verdict} docked={docked} />
                </LayoutGroup>
              </div>
            </div>
          </div>
          <p
            aria-live="polite"
            className="min-h-[3.25rem] border-t border-line-soft px-4 py-3 text-sm leading-relaxed text-muted"
          >
            {CAPTIONS[zone]}
          </p>
        </div>
      </div>
    </div>
  );
}
