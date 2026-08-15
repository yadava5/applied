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
   * drives the CAMERA: the board is taller than the stage, so beat 0 rests at
   * the head (the pulse band and the still-quiet rows) and beats 1 and 2 hold
   * at the foot, where the verdict row lands and the pane docks open beside
   * it. A transform inside the clip, so the page's own scroll geometry never
   * moves: CLS stays zero by construction. Reduced motion pans by cut, not by
   * glide.
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

  // The camera. Nothing here runs for beat-less callers.
  //
  // Beats 1 AND 2 sit at the board's foot; only the head rests at the top.
  // Beat 1 pans PAST the foot by `OVERLAY_ROOM`: the board's last rows clear
  // the stage's lower band entirely, and the receipt card (`overlay`) lands
  // in the emptied strip instead of on top of the very rows it documents —
  // measured, a bottom-corner float covered either the moved row's identity
  // or its neighbours' controls at every corner. Beat 2 drops that strip,
  // because the card stands down and the docked pane wants the room.
  //
  // Beat 2 used to return to the head, and measurement caught what that cost:
  // the moved row lands in the CLOSED group at the board's foot (679–735 of a
  // 783px board), while the head-anchored stage shows only 0–552 at a 768-tall
  // viewport and 0–384 at 600. So the scene captioned "the row opens on the
  // mail that moved it" was arguing about a row that was off-stage at every
  // height. Holding at the foot puts the row and the mail behind it in one
  // frame, and turns beat 2 from a cut back to the head into a 112px settle —
  // the row the visitor watched arrive is never out of sight.
  //
  // Measured through a ResizeObserver rather than once per beat: the board
  // GROWS when the pane docks open (743 → 783), and a measurement taken at
  // beat time would pan to a foot that has since moved.
  useEffect(() => {
    if (beat === undefined) return;
    const stage = stageRef.current;
    const pan = panRef.current;
    if (!stage || !pan) return;
    const room = beat === 1 ? OVERLAY_ROOM : 0;
    const measure = () =>
      setPanY(beat < 1 ? 0 : -Math.max(0, pan.scrollHeight - stage.clientHeight + room));
    // The observer's own first callback is the initial measurement, so the
    // effect body never sets state synchronously (react-hooks/set-state-in-effect).
    if (typeof ResizeObserver === "undefined") {
      const id = window.setTimeout(measure, 0);
      return () => window.clearTimeout(id);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(pan);
    return () => ro.disconnect();
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
            and it stands down while the camera is AT the foot (beats 1 and
            2), where "this continues" would be false and the closed rows are
            the scene's whole point. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background transition-opacity duration-500 motion-reduce:transition-none",
            (beat ?? 0) >= 1 && "opacity-0",
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
