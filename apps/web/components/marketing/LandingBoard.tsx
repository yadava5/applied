"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { BoardStill } from "./BoardStill";
import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";

/**
 * The landing's board embed: the REAL product, mounted the only safe way.
 *
 * Three constraints shaped this component, all verified rather than assumed:
 *
 *  1. TRANSPORT. `PipelineBoard`'s `transport` prop DEFAULTS to the live
 *     transport, which PATCHes /api/applications/* — on localhost, against a
 *     signed-in owner's real production data. So this embed only ever mounts
 *     `MarketingBoard`, whose transport is in-memory by construction, and
 *     `tests/unit/landing-variants.test.mjs` asserts no other path exists
 *     from the landing pages to the board.
 *
 *  2. DATES. The demo fixtures are dated RELATIVE to today; prerendering them
 *     bakes the build day in and React #418 fires from three days after
 *     build (measured — see app/demo/page.tsx). /demo pays for that with
 *     `force-dynamic`; a marketing page must not (700–1150 ms origin TTFB).
 *     So the board is mounted CLIENT-SIDE only, on approach
 *     (IntersectionObserver, 600px early) and only at `lg`+ — the server
 *     renders a skeleton into reserved geometry instead.
 *
 *  3. GEOMETRY. The stage has a fixed height and `overflow-clip`, so mounting
 *     the board moves nothing: CLS stays zero by construction, and there is
 *     no nested scroller — the crop is visual, with the fade below saying
 *     "this continues". `clip`, not `hidden`: `hidden` would make the stage a
 *     scroll container and break the flow board's sticky spine.
 *
 * Below `lg` the embed is `BoardStill` — a designed capture, not a broken
 * layout. The live board keeps rendering (CSS-hidden) once mounted so a
 * resize never resets a visitor's drags.
 */
const MarketingBoard = dynamic(
  () => import("./MarketingBoard").then((m) => m.MarketingBoard),
  { ssr: false },
);

const LG = "(min-width: 1024px)";

/** The strip beat 1 clears below the board's foot for the receipt card. */
const OVERLAY_ROOM = 152;

export function LandingBoard({
  height = "min(72vh, 680px)",
  className,
  caption = true,
  beat,
  overlay,
}: {
  /** The stage's fixed height — the reservation that keeps CLS at zero. */
  height?: string;
  className?: string;
  /** Off when the caller's frame carries the provenance line itself (B). */
  caption?: boolean;
  /**
   * The window act's scene index (WindowAct → MarketingBoard). Here it also
   * drives the CAMERA: the board is taller than the stage, and beat 1 pans
   * the crop to the board's foot so the closed group is on screen when the
   * verdict row arrives there; every other beat rests at the head, where the
   * pulse band and — from beat 2 — the opened detail pane sit. A transform
   * inside the clip, so the page's own scroll geometry never moves: CLS
   * stays zero by construction. Reduced motion pans by cut, not by glide.
   */
  beat?: number;
  /** A figure floated over the stage's foot (the act's receipt card). */
  overlay?: ReactNode;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const panRef = useRef<HTMLDivElement>(null);
  const [panY, setPanY] = useState(0);
  const [near, setNear] = useState(false);
  const [wide, setWide] = useState(false);

  // The camera. Measured at beat time (not cached): the board's height
  // changes when the pane docks open and rows fold, and a stale measure
  // would pan past the foot. Nothing here runs for beat-less callers.
  //
  // Beat 1 pans PAST the foot by `OVERLAY_ROOM`: the board's last rows clear
  // the stage's lower band entirely, and the receipt card (`overlay`) lands
  // in the emptied strip instead of on top of the very rows it documents —
  // measured, a bottom-corner float covered either the moved row's identity
  // or its neighbours' controls at every corner.
  useEffect(() => {
    if (beat === undefined) return;
    if (beat === 1) {
      const stage = stageRef.current;
      const pan = panRef.current;
      if (!stage || !pan) return;
      setPanY(-Math.max(0, pan.scrollHeight - stage.clientHeight + OVERLAY_ROOM));
    } else {
      setPanY(0);
    }
  }, [beat]);

  // `lg`+ is a mount condition, not just a display one: a phone should never
  // download the dashboard bundle for a board it will not show. Tracked live
  // so rotating a tablet mounts the board when it becomes usable.
  useEffect(() => {
    const mq = window.matchMedia(LG);
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      const id = setTimeout(() => setNear(true), 0);
      return () => clearTimeout(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          io.disconnect();
        }
      },
      // Mount well before arrival so the product is running by the time the
      // visitor's eyes get there — the hero embeds are in view at load.
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const live = near && wide;

  return (
    <div className={className}>
      {/* ---- the stage (`lg`+) ------------------------------------------- */}
      <div ref={stageRef} className="relative hidden lg:block" style={{ height }}>
        <div className="absolute inset-0 overflow-clip">
          {/* The camera's dolly — static (translate 0) for beat-less callers. */}
          <div
            ref={panRef}
            className="transition-transform duration-700 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none"
            style={{ transform: `translateY(${panY}px)` }}
          >
            {live ? <MarketingBoard beat={beat} /> : <StageSkeleton />}
          </div>
        </div>
        {/* The crop edge: the board continues below this line, and the fade
            says so. Decoration only — it must never intercept the board —
            and it stands down while the camera is AT the foot (beat 1),
            where "this continues" would be false and the closed rows are
            the scene's whole point. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background transition-opacity duration-500 motion-reduce:transition-none",
            beat === 1 && "opacity-0",
          )}
        />
        {/* The act's receipt card, in the strip beat 1 cleared below the
            board's foot — beside nothing, covering nothing. */}
        {overlay ? (
          <div className="absolute bottom-2 left-1 z-10 w-full max-w-[26rem]">{overlay}</div>
        ) : null}
      </div>
      <div
        className={cn(
          "mt-3 hidden flex-wrap items-center justify-between gap-2",
          caption && "lg:flex",
        )}
      >
        <span className="inline-flex items-center gap-2 text-xs text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          {BOARD.live}
        </span>
        <a
          href="/demo"
          {...NEW_TAB}
          className="text-xs text-muted underline-offset-4 hover:text-strong hover:underline"
        >
          {BOARD.open} →
        </a>
      </div>

      {/* ---- the still (below `lg`) -------------------------------------- */}
      <div className="lg:hidden">
        <BoardStill />
      </div>
    </div>
  );
}

/**
 * What the server renders into the reservation: the board's silhouette.
 * Pulses only for visitors who have not asked motion to stop.
 */
function StageSkeleton() {
  return (
    <div aria-hidden className="flex h-full flex-col gap-4 motion-safe:animate-pulse">
      <div className="flex items-center justify-between gap-4">
        <div className="h-5 w-44 rounded bg-surface-2" />
        <div className="h-5 w-56 rounded bg-surface-2" />
      </div>
      <div className="flex min-h-0 flex-1 gap-5">
        <div className="hidden w-56 shrink-0 rounded-xl bg-surface lg:block" />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-20 rounded-xl border border-line-soft bg-surface" />
          ))}
        </div>
      </div>
    </div>
  );
}
