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

/**
 * The strip the camera clears below the board's foot for the docked receipt
 * (`ReceiptStrip`): the bar covers the stage's last ~25px once it extends
 * into the frame's padding, plus a breath so it never sits on a row. It
 * replaces a 152px clearing for a floating card, which left the card adrift
 * in a black band that read as debris at every mid-scroll offset.
 */
const OVERLAY_ROOM = 44;

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
  /**
   * The camera has handed the frame back to the visitor.
   *
   * The window CROPS a live product, so every control the crop pushes
   * off-stage becomes unreachable — and the detail pane's own close × is one
   * of them at beats 1 and 2 (measured at a 768-tall viewport: the × sits
   * 304px above the stage at beat 1, 97px above it at beat 2, with only
   * Escape left to close a pane the visitor opened themselves). Rather than
   * layer a marketing-owned close over another component's chrome, the frame
   * gives the board back: an open card returns the camera to the head, which
   * is beat 0's frame — known good, and where the pane renders its whole
   * header, title and ×.
   *
   * Traversal counts as taking the wheel, deliberately: ↑/↓ loads another
   * card through the same call, and the position row it renumbers (`3 of
   * 10`) lives in the head the crop removes — so a reader who starts
   * browsing the trail at beat 2 gets the frame back too, without having
   * clicked anything.
   *
   * It does not re-engage. The camera is narration, and a visitor who has
   * opened a card has stopped watching and started using; the same rule the
   * beats already follow for state (MarketingBoard skips the verdict move on
   * a row the visitor moved, and the board's seeded open stands down for a
   * card the visitor chose). The authored beat-2 composition still plays in
   * full for every reader who lets it.
   */
  const [released, setReleased] = useState(false);

  // The camera. Nothing here runs for beat-less callers.
  //
  // Beats 1 AND 2 sit at the board's foot; only the head rests at the top.
  // Both pan PAST the foot by `OVERLAY_ROOM`: the receipt strip (`overlay`)
  // docks over the frame's foot, so the room is what keeps it off the last
  // row it would otherwise cover — measured, a floating card in a larger
  // cleared band covered either rows or nothing, and "nothing" read as
  // debris. The strip stays through beat 2 because it covers no rows and its
  // "the email that did it ↓" is the hand-off line into the descent.
  //
  // The trade at beat 2 is deliberate: holding the foot crops the pane's own
  // head — the `9 of 10` nav row, the title, and the pane's × — in exchange
  // for the row and the whole trail. The row beside it carries the identity
  // the title was carrying. That trade covers the pane the PAGE opens, and
  // only for as long as the page is the one driving: the moment the visitor
  // opens a card themselves the camera releases (see `released`) and the
  // pane's own × comes back into frame, because a cropped control the
  // visitor reached for is a broken control, not a composition.
  //
  // Beat 2 used to return to the head, and measurement caught what that cost:
  // the moved row lands near the board's foot (the offered group, one group
  // above closed — measured at 679–735 of a 783px board when the destination
  // was the closed group itself), while a head-anchored stage shows only
  // 0–552 at a 768-tall viewport and 0–384 at 600. So the scene captioned
  // "the row opens on the mail that moved it" was arguing about a row that
  // was off-stage at every height. Holding at the foot puts the row and the
  // mail behind it in one frame, and turns beat 2 from a cut back to the
  // head into a small settle — the pane docking is what grows the board, and
  // that growth is the whole move now that both beats share one `room`. The
  // row the visitor watched arrive is never out of sight.
  //
  // Measured through a ResizeObserver rather than once per beat: the board
  // GROWS when the pane docks open (743 → 783), and a measurement taken at
  // beat time would pan to a foot that has since moved.
  useEffect(() => {
    if (beat === undefined) return;
    const stage = stageRef.current;
    const pan = panRef.current;
    if (!stage || !pan) return;
    const room = beat >= 1 ? OVERLAY_ROOM : 0;
    // `released` resolves to 0 INSIDE the measure rather than skipping the
    // effect: the pane docking open grows the board (743 → 783), the observer
    // fires on that growth, and a skipped effect would leave the last panned
    // value behind exactly when the visitor needs the frame back.
    const measure = () =>
      setPanY(
        released || beat < 1 ? 0 : -Math.max(0, pan.scrollHeight - stage.clientHeight + room),
      );
    // The observer's own first callback is the initial measurement, so the
    // effect body never sets state synchronously (react-hooks/set-state-in-effect).
    if (typeof ResizeObserver === "undefined") {
      const id = window.setTimeout(measure, 0);
      return () => window.clearTimeout(id);
    }
    const ro = new ResizeObserver(measure);
    // Both sides of the subtraction: the board's own height changes when the
    // pane docks, and the stage's is `calc(100dvh - 13.5rem)`, so resizing the
    // window mid-act moves the divisor without touching the dividend.
    ro.observe(pan);
    ro.observe(stage);
    return () => ro.disconnect();
  }, [beat, released]);

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
            {live ? (
              <MarketingBoard beat={beat} onVisitorOpen={() => setReleased(true)} />
            ) : (
              <StageSkeleton />
            )}
          </div>
        </div>
        {/* The crop edge: the board continues below this line, and the fade
            says so. Decoration only — it must never intercept the board —
            and it stands down while the camera is AT the foot (beats 1 and
            2), where "this continues" would be false and the closed rows are
            the scene's whole point. A released camera is back at the head, so
            the board continues below the line again and the fade says so. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background transition-opacity duration-500 motion-reduce:transition-none",
            (beat ?? 0) >= 1 && !released && "opacity-0",
          )}
        />
        {/* The other crop edge. While the camera holds the foot the board —
            and, at beat 2, the docked pane's head — continues ABOVE the
            frame, and without a signal the top edge read as content cut
            mid-element (the pane "starting mid-content" was the reported
            defect). Same instrument as the bottom fade, mirrored: it shows
            only while the camera is panned, and a released or resting frame
            has the board's own head at the top, where a fade would be a lie. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-background to-transparent transition-opacity duration-500 motion-reduce:transition-none",
            ((beat ?? 0) < 1 || released) && "opacity-0",
          )}
        />
        {/* The act's receipt, docked over the frame's foot — window chrome,
            not a float: the negative offsets carry it across the stage's
            padding to the frame's own edges, mirroring the provenance bar at
            the head. `OVERLAY_ROOM` is what keeps the last row clear of it.
            It stands down with the camera: a released frame is back at the
            head, where a receipt bar would cover rows it has nothing to say
            about. */}
        {overlay && !released ? (
          <div className="absolute -bottom-5 -left-5 -right-5 z-10">{overlay}</div>
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
