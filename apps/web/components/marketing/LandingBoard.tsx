"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import { cn } from "@/lib/utils";
import { BoardStill } from "./BoardStill";
import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";
import { useWideViewport, type Signal } from "./scrub";

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
 * arrives in. The pan is scrubbed off one continuous value now, and a `room` that
 * appeared partway through would move the pan's target under it.
 */
const OVERLAY_ROOM = 44;

/** How far the receipt strip travels up into the frame's foot, in px. */
const RECEIPT_RISE = 18;

/**
 * Air between the stage's top edge and the docked pane's head once the dock
 * tilt (`ActCamera.dockPan`) has finished: enough that the pane's rounded top
 * and its × sit clear of the top crop fade's densest band, small enough that
 * the tilt gives up as little of the board below as it can.
 */
const PANE_CLEARANCE = 16;

/**
 * The act's camera channel: four scrubbed inputs the window act publishes and
 * this component paints. Signals rather than props because they change on
 * every scroll frame and none of them is a reason to render.
 */
export interface ActCamera {
  /** 0 the board's head, 1 its foot. */
  pan: Signal;
  /**
   * 0 holding the foot, 1 tilted back up to the docked pane's head — the
   * scrubbed move that puts the pane's own chrome (title, traversal row, ×)
   * inside the frame once the page has opened it. The foot hold cropped that
   * chrome above the stage at every viewport height, and a pane whose close
   * control is off-screen is broken, not composed. The tilt's target is
   * measured from the pane's real box (`paneDistance` below).
   */
  dockPan: Signal;
  /** The receipt's opacity and its rise, kept apart because the announcement
   *  has to be legible long before it stops moving — the caller resolves the
   *  opacity early (`RECEIPT_FADE` in tempo.ts) and this only paints it. */
  receiptFade: Signal;
  receiptRise: Signal;
}

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
   *
   * Signals rather than props, because none of these is a reason to render:
   * they change on every scroll frame and all they do is move a transform and
   * two opacities.
   */
  camera?: ActCamera;
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
   * It is a REF rather than React state because the camera is no longer a
   * rendered branch: the pan is written straight to the element, and a React
   * `? :` around it could not reach the transform at all. It folds into the
   * mapping instead — a released camera multiplies the pan, both crop fades
   * and the receipt to zero, which is exactly "back at the head".
   */
  const released = useRef(false);

  /** The act's four scrubbed inputs, mirrored where `paint` can read them
   *  without a render, plus the two measured camera targets (negative):
   *  `panDistance` is the foot, `paneDistance` the dock tilt's own — the
   *  translate that puts the docked pane's head `PANE_CLEARANCE` under the
   *  stage's top edge. Null until the pane exists to be measured. */
  const pan = useRef(0);
  const dockPan = useRef(0);
  const receiptFade = useRef(0);
  const receiptRise = useRef(0);
  const panDistance = useRef(0);
  const paneDistance = useRef<number | null>(null);

  const bottomFadeRef = useRef<HTMLDivElement>(null);
  const topFadeRef = useRef<HTMLDivElement>(null);
  const receiptRef = useRef<HTMLDivElement>(null);

  /**
   * The whole camera, as one write per frame.
   *
   * Everything the act moves is derived from `engaged` — the scrubbed pan
   * folded with the release latch — so the pan and the two crop edges cannot
   * disagree about where the camera is. That was the point of the single
   * `useTransform` chain this replaces, and it is why it stays one expression
   * rather than three listeners each doing their own arithmetic.
   */
  const paint = useCallback(() => {
    const engaged = released.current ? 0 : pan.current;
    const dock = released.current ? 0 : dockPan.current;
    // The camera's position is one interpolation: the scrubbed pan toward the
    // foot, then the scrubbed dock tilt from wherever it is toward the pane's
    // head. Until the pane exists the tilt's target IS the foot, so an
    // unmeasured pane means no move rather than a wrong one.
    const foot = engaged * panDistance.current;
    const target = paneDistance.current ?? panDistance.current;
    const y = foot + dock * (target - foot);
    if (panRef.current) {
      panRef.current.style.transform = `translateY(${y.toFixed(2)}px)`;
    }
    // The crop edges follow the camera's DEPTH — where the frame actually is
    // between head (0) and foot (1) — not the raw pan input, because the dock
    // tilt moves the frame back up and the board genuinely continues below it
    // again. They used to switch at a scene boundary; they are two more
    // things the reader's scroll now moves continuously.
    const depth = panDistance.current ? y / panDistance.current : 0;
    if (bottomFadeRef.current) bottomFadeRef.current.style.opacity = String(1 - depth);
    if (topFadeRef.current) topFadeRef.current.style.opacity = String(depth);
    // The receipt stands down WITH the camera — on release (back at the head,
    // where a bar would cover rows it has nothing to say about) and across
    // the dock tilt, whose whole point is handing the frame to the pane's own
    // chrome: a marketing strip lying over the trail it announced would be
    // the crop defect restated as an overlay.
    if (receiptRef.current) {
      receiptRef.current.style.opacity = String(
        released.current ? 0 : receiptFade.current * (1 - dock),
      );
      receiptRef.current.style.transform = `translateY(${((1 - receiptRise.current) * RECEIPT_RISE).toFixed(2)}px)`;
    }
  }, []);

  /**
   * Let the next camera write ANIMATE instead of cutting. The scrub writes
   * per-frame with no transition — that is what a scrub is — but two moments
   * are not scrubs and used to land as hard cuts, which is the "it resizes
   * and goes up" the owner reported: the release (a click snapped the frame
   * from the foot to the head, 235–275px in one paint) and a pane that
   * finishes mounting under a tilt already in progress (the target jumps).
   * A transition is armed for one move and removed on a timer, so the scroll
   * scrub never runs through it. Reduced motion keeps the step — that is its
   * grammar for this whole act.
   */
  const glideTimer = useRef(0);
  const glide = useCallback((ms: number) => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const targets = [panRef, bottomFadeRef, topFadeRef, receiptRef];
    if (panRef.current) {
      panRef.current.style.transition = `transform ${ms}ms cubic-bezier(0.22, 1, 0.36, 1)`;
    }
    for (const ref of [bottomFadeRef, topFadeRef, receiptRef]) {
      if (ref.current) ref.current.style.transition = `opacity ${ms}ms ease`;
    }
    window.clearTimeout(glideTimer.current);
    glideTimer.current = window.setTimeout(() => {
      for (const ref of targets) ref.current?.style.removeProperty("transition");
    }, ms + 60);
  }, []);
  useEffect(() => () => window.clearTimeout(glideTimer.current), []);

  useEffect(() => {
    if (!camera) return;
    const stop = [
      camera.pan.subscribe((value) => {
        pan.current = value;
        paint();
      }),
      camera.dockPan.subscribe((value) => {
        dockPan.current = value;
        paint();
      }),
      camera.receiptFade.subscribe((value) => {
        receiptFade.current = value;
        paint();
      }),
      camera.receiptRise.subscribe((value) => {
        receiptRise.current = value;
        paint();
      }),
    ];
    return () => {
      for (const unsubscribe of stop) unsubscribe();
    };
  }, [camera, paint]);

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
  // The foot hold no longer ends the story. It crops the pane's own head —
  // the `9 of 10` nav row, the title, and the pane's × — and the owner's
  // verdict on that trade was final: chrome the visitor can see but not
  // reach is broken, whoever opened the pane. So the dock beat now TILTS the
  // camera back up to the pane's measured head (`ACT_MARKS.dockPan`,
  // `paneDistance`), trading the moved row — whose identity the pane's title
  // carries by then — for the mail's full chrome. The release on a visitor's
  // own open stays, and glides.
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
  //
  // THE DIVIDEND IS THE BOX, NOT `scrollHeight` — measured, and the difference
  // is a real defect this component shipped. Instrumenting ResizeObserver
  // before hydration on a production build at 1024x768:
  //
  //   forward, pane closed   box 743  scrollHeight 743   pan -235
  //   pane docks             box 769  scrollHeight 769   pan -261   RO fired
  //   pane un-docks          box 743  scrollHeight 768   pan -260   RO fired
  //
  // The observer is not the problem: it fires on the un-dock, because the box
  // genuinely changes. `scrollHeight` is. In that callback the box has already
  // settled to 743 while the departing pane is still laid out, so the overflow
  // extent reads 768 — and since the box then stops changing, no later
  // callback ever corrects it. The camera stayed 25px too low for the REST OF
  // THE VISIT, forward path included, clipping the very row the caption points
  // at; at 1512 x 949, where the whole pan is only 54px, that is a 48% error.
  //
  // So: read the box, which was correct at every instant sampled, and take a
  // second read on the following frame in case the one the observer hands us
  // is itself a transient. Resizes are rare; a spare rAF is free insurance
  // against a value that used to be wrong permanently.
  useEffect(() => {
    if (!choreographed) return;
    const stage = stageRef.current;
    const dolly = panRef.current;
    if (!stage || !dolly) return;
    const measure = () => {
      panDistance.current = -Math.max(
        0,
        dolly.getBoundingClientRect().height - stage.clientHeight + OVERLAY_ROOM,
      );
      // The dock tilt's target: the docked pane's head, PANE_CLEARANCE under
      // the stage's top. Measured as a rect difference against the dolly —
      // both rects carry the same translate, so the offset is intrinsic. The
      // pane mounts AFTER the dock latch (it waits out the row's travel), so
      // on a slow scroll it can arrive while the tilt is already partway in;
      // the target changing under a live scrub would snap, so that one
      // correction glides (below).
      const pane = dolly.querySelector('[data-testid="application-detail"]');
      const hadPane = paneDistance.current !== null;
      paneDistance.current = pane
        ? -Math.max(
            0,
            pane.getBoundingClientRect().top - dolly.getBoundingClientRect().top - PANE_CLEARANCE,
          )
        : null;
      if (!hadPane && paneDistance.current !== null && dockPan.current > 0) glide(350);
      paint();
    };
    if (typeof ResizeObserver === "undefined") {
      measure();
      return;
    }
    let settle = 0;
    const ro = new ResizeObserver(() => {
      measure();
      cancelAnimationFrame(settle);
      settle = requestAnimationFrame(measure);
    });
    // Both sides of the subtraction: the board's own height changes when the
    // pane docks, and the stage's is `calc(100dvh - 13.5rem)`, so resizing the
    // window mid-act moves the divisor without touching the dividend.
    ro.observe(dolly);
    ro.observe(stage);
    return () => {
      cancelAnimationFrame(settle);
      ro.disconnect();
    };
  }, [choreographed, paint, glide]);

  const live = near && wide;

  return (
    <div className={className}>
      {/* ---- the stage (`lg`+) ------------------------------------------- */}
      <div ref={stageRef} className="relative hidden lg:block" style={{ height }}>
        <div className="absolute inset-0 overflow-clip">
          {/* The camera's dolly. Scrubbed, so there is no transition to
              collapse under reduced motion — the value itself steps there
              (WindowAct). Static at 0 for callers without a camera. */}
          <div ref={panRef} style={{ transform: "translateY(0px)" }}>
            {live ? (
              <MarketingBoard
                verdict={verdict}
                docked={docked}
                onVisitorOpen={() => {
                  // The camera gives the frame back with a glide, not a cut:
                  // the release is the one camera move the reader's scroll
                  // does not own, so it is the one that gets a duration.
                  glide(650);
                  released.current = true;
                  paint();
                }}
              />
            ) : (
              <StageSkeleton />
            )}
          </div>
        </div>
        {/* The crop edge: the board continues below this line, and the fade
            says so. Decoration only — it must never intercept the board —
            and it fades out as the camera reaches the foot, where "this
            continues" would be false and the closed rows are the scene's
            whole point. A released camera is back at the head, so the board
            continues below the line again and the fade says so. */}
        <div
          ref={bottomFadeRef}
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background"
        />
        {/* The other crop edge. While the camera holds the foot the board —
            and, once docked, the pane's head — continues ABOVE the frame, and
            without a signal the top edge read as content cut mid-element (the
            pane "starting mid-content" was the reported defect). Same
            instrument as the bottom fade, mirrored. */}
        <div
          ref={topFadeRef}
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-background to-transparent"
          // The camera rests at the head, so this edge starts invisible — an
          // inline default rather than a paint, because the server renders it
          // too and a flash of the wrong crop edge is a flash of a lie.
          style={{ opacity: 0 }}
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
          <div
            ref={receiptRef}
            className="pointer-events-none absolute -bottom-5 -left-5 -right-5 z-10"
            style={{ opacity: 0 }}
          >
            {overlay}
          </div>
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
 * Pulses only for visitors who have not asked motion to stop. Exported for
 * the window act, whose stage fills the same reservation before its take's
 * chunk lands.
 */
export function StageSkeleton() {
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
