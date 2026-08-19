"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { motion, useMotionValue, useTransform, type MotionValue } from "motion/react";

import { cn } from "@/lib/utils";
import { BoardStill } from "./BoardStill";
import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";
import { useWideViewport } from "./scrub";

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

/**
 * The strip the camera clears below the board's foot for the docked receipt
 * (`ReceiptStrip`): the bar covers the stage's last ~25px once it extends
 * into the frame's padding, plus a breath so it never sits on a row. It
 * replaces a 152px clearing for a floating card, which left the card adrift
 * in a black band that read as debris at every mid-scroll offset.
 *
 * It is reserved for the WHOLE act rather than from the scene the receipt
 * arrives in. The pan is scrubbed off one motion value now, and a `room` that
 * appeared partway through would move the pan's target under it.
 */
const OVERLAY_ROOM = 44;

export function LandingBoard({
  height = "min(72vh, 680px)",
  className,
  caption = true,
  camera,
  verdict,
  docked,
  overlay,
}: {
  /** The stage's fixed height — the reservation that keeps CLS at zero. */
  height?: string;
  className?: string;
  /** Off when the caller's frame carries the provenance line itself (B). */
  caption?: boolean;
  /**
   * The window act's camera, 0 (the board's head) → 1 (its foot), scrubbed
   * off the act's scroll progress (`WindowAct`). The board is taller than the
   * stage, so the head shows the pulse band and the still-quiet rows and the
   * foot is where the verdict row lands and the pane docks open beside it.
   *
   * A transform inside the clip, so the page's own scroll geometry never
   * moves: CLS stays zero by construction. Supplying it is what marks this
   * mount as CHOREOGRAPHED — every other caller gets the resting board.
   */
  camera?: MotionValue<number>;
  /** The offer has landed: the row is committed to `offered` and travels
   *  there by the board's own layout animation. Reverses. */
  verdict?: boolean;
  /** The detail pane is docked open on that row. Reverses. */
  docked?: boolean;
  /** A figure floated over the stage's foot (the act's receipt strip). */
  overlay?: ReactNode;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const panRef = useRef<HTMLDivElement>(null);
  const wide = useWideViewport();
  const near = useNearViewport(stageRef);
  const choreographed = camera !== undefined;

  /**
   * The camera has handed the frame back to the visitor.
   *
   * The window CROPS a live product, so every control the crop pushes
   * off-stage becomes unreachable — and the detail pane's own close × is one
   * of them at the foot (measured at a 768-tall viewport: the × sits 304px
   * above the stage mid-act, 97px above it once the pane is docked, with only
   * Escape left to close a pane the visitor opened themselves). Rather than
   * layer a marketing-owned close over another component's chrome, the frame
   * gives the board back: an open card returns the camera to the head, which
   * is the resting frame — known good, and where the pane renders its whole
   * header, title and ×.
   *
   * Traversal counts as taking the wheel, deliberately: ↑/↓ loads another
   * card through the same call, and the position row it renumbers (`3 of
   * 10`) lives in the head the crop removes — so a reader who starts
   * browsing the trail at the foot gets the frame back too, without having
   * clicked anything.
   *
   * It does not re-engage, and it is the ONE piece of this act that does not
   * reverse with the scroll. The camera is narration, and a visitor who has
   * opened a card has stopped watching and started using; the same rule
   * MarketingBoard follows for state it must not overwrite. The authored
   * composition still plays in full, in both directions, for every reader who
   * lets it.
   *
   * It is a MOTION VALUE rather than React state because the camera is no
   * longer a rendered branch: `panY` is written straight to the element, and
   * a React `? :` around it could not reach the transform at all. It folds
   * into the mapping instead — a released camera multiplies the pan and both
   * crop fades to zero, which is exactly "back at the head".
   */
  const released = useMotionValue(0);

  // The camera's mapping. Nothing here does anything for callers without a
  // `camera`: `engaged` is pinned at 0 and every derived value with it.
  const restingCamera = useMotionValue(0);
  const engaged = useTransform(
    [camera ?? restingCamera, released] as MotionValue<number>[],
    ([progress, letGo]: number[]) => progress * (1 - letGo),
  );
  /** The measured full-pan distance, negative, written by the observer below
   *  rather than held in state — the pan is a value, not a render. */
  const panDistance = useMotionValue(0);
  const panY = useTransform(
    [engaged, panDistance] as MotionValue<number>[],
    ([progress, distance]: number[]) => progress * distance,
  );
  /** The crop edges. They used to switch at a scene boundary; they are two
   *  more things the reader's scroll now moves continuously. */
  const headFade = useTransform(engaged, (progress) => 1 - progress);
  const footFade = engaged;
  /** The receipt stands down WITH the camera. A released camera is back at the
   *  head, where a receipt bar would cover rows it has nothing to say about —
   *  the same rule the crop fades follow, and the reason this multiplies the
   *  caller's own scrubbed opacity rather than replacing it. */
  const receiptFade = useTransform(released, (letGo) => 1 - letGo);

  // The pan target, measured through a ResizeObserver rather than once per
  // scene: the board GROWS when the pane docks open (743 → 783), and a
  // measurement taken at scene time would pan to a foot that has since moved.
  //
  // Both beats of the act sit at the board's foot; only the head rests at the
  // top. The pan goes PAST the foot by `OVERLAY_ROOM`: the receipt strip
  // (`overlay`) docks over the frame's foot, so the room is what keeps it off
  // the last row it would otherwise cover — measured, a floating card in a
  // larger cleared band covered either rows or nothing, and "nothing" read as
  // debris.
  //
  // The trade at the foot is deliberate: holding it crops the pane's own head
  // — the `9 of 10` nav row, the title, and the pane's × — in exchange for
  // the row and the whole trail. The row beside it carries the identity the
  // title was carrying. That trade covers the pane the PAGE opens, and only
  // for as long as the page is the one driving: the moment the visitor opens
  // a card themselves the camera releases and the pane's × comes back into
  // frame, because a cropped control the visitor reached for is a broken
  // control, not a composition.
  //
  // The scene that docks the pane used to return to the head, and measurement
  // caught what that cost: the moved row lands near the board's foot (the
  // offered group, one group above closed — measured at 679–735 of a 783px
  // board when the destination was the closed group itself), while a
  // head-anchored stage shows only 0–552 at a 768-tall viewport and 0–384 at
  // 600. So the scene captioned "the row opens on the mail that moved it" was
  // arguing about a row that was off-stage at every height. Holding at the
  // foot puts the row and the mail behind it in one frame. The row the
  // visitor watched arrive is never out of sight.
  useEffect(() => {
    if (!choreographed) return;
    const stage = stageRef.current;
    const pan = panRef.current;
    if (!stage || !pan) return;
    const measure = () =>
      panDistance.set(-Math.max(0, pan.scrollHeight - stage.clientHeight + OVERLAY_ROOM));
    if (typeof ResizeObserver === "undefined") {
      measure();
      return;
    }
    const ro = new ResizeObserver(measure);
    // Both sides of the subtraction: the board's own height changes when the
    // pane docks, and the stage's is `calc(100dvh - 13.5rem)`, so resizing the
    // window mid-act moves the divisor without touching the dividend.
    ro.observe(pan);
    ro.observe(stage);
    return () => ro.disconnect();
  }, [choreographed, panDistance]);

  const live = near && wide;

  return (
    <div className={className}>
      {/* ---- the stage (`lg`+) ------------------------------------------- */}
      <div ref={stageRef} className="relative hidden lg:block" style={{ height }}>
        <div className="absolute inset-0 overflow-clip">
          {/* The camera's dolly. Scrubbed, so there is no transition to
              collapse under reduced motion — the value itself steps there
              (WindowAct). Static at 0 for callers without a camera. */}
          <motion.div ref={panRef} style={{ y: panY }}>
            {live ? (
              <MarketingBoard
                verdict={verdict}
                docked={docked}
                onVisitorOpen={() => released.set(1)}
              />
            ) : (
              <StageSkeleton />
            )}
          </motion.div>
        </div>
        {/* The crop edge: the board continues below this line, and the fade
            says so. Decoration only — it must never intercept the board —
            and it fades out as the camera reaches the foot, where "this
            continues" would be false and the closed rows are the scene's
            whole point. A released camera is back at the head, so the board
            continues below the line again and the fade says so. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background"
          style={{ opacity: headFade }}
        />
        {/* The other crop edge. While the camera holds the foot the board —
            and, once docked, the pane's head — continues ABOVE the frame, and
            without a signal the top edge read as content cut mid-element (the
            pane "starting mid-content" was the reported defect). Same
            instrument as the bottom fade, mirrored. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-background to-transparent"
          style={{ opacity: footFade }}
        />
        {/* The act's receipt, docked over the frame's foot — window chrome,
            not a float: the negative offsets carry it across the stage's
            padding to the frame's own edges, mirroring the provenance bar at
            the head. `OVERLAY_ROOM` is what keeps the last row clear of it.
            Its arrival is scrubbed by the caller; its stand-down is `released`.

            Inert to the pointer, and on the WRAPPER rather than the figure
            inside it: the bar is mounted for the whole act now (it has to be,
            to scrub) so it lies over the frame's foot even at rest, where it
            is invisible and must not be swallowing hits on the last row. The
            figure has nothing to click. */}
        {overlay ? (
          <motion.div
            className="pointer-events-none absolute -bottom-5 -left-5 -right-5 z-10"
            style={{ opacity: receiptFade }}
          >
            {overlay}
          </motion.div>
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
 * Whether the stage has come within 600px of the viewport — the mount signal,
 * fired early so the product is running by the time the visitor's eyes get
 * there (the hero embeds are in view at load). One-way: once the board is
 * mounted it stays mounted, so a visitor's drags survive scrolling away.
 */
function useNearViewport(ref: RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);

  useEffect(() => {
    const el = ref.current;
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
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);

  return near;
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
