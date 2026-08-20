"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";

import { MarketingBoard } from "./MarketingBoard";
import { ACT } from "./copy";
import { Director, TakeError } from "./director";

export type OnerPhase = "idle" | "playing" | "done" | "failed";

/**
 * The workday oner's stage — the camera wrapper, the synthesized pointer and
 * the mounted board, inside the frame `WindowAct` owns. Dynamically imported
 * (`ssr: false`, `lg`+ only), so the board's chunk — motion included — never
 * reaches a phone or the landing's initial JS.
 *
 * Honesty rules, inherited from the lab stage the take was chosen in:
 *   · the children are REAL mounted components. Nothing here screenshots or
 *     redraws a surface, and the board stays interactive under the take —
 *     drag a card mid-take and the board answers you, not the script;
 *   · the pointer presses controls FOR REAL (`Director.click` dispatches the
 *     events and calls the element's own `click()`), so the take cannot make
 *     the product appear to do anything a visitor's hand could not;
 *   · a replay REMOUNTS this stage (the parent keys it by run), so a take
 *     that mutated real state starts over from the product's own initial
 *     state, never from a rewound recording.
 *
 * The clock is pausable in three ways that compose (`director.paused`): the
 * user's pause control, the frame leaving the viewport (nothing may finish
 * unwatched — the same guarantee the scrubbed act made by construction), and
 * a backgrounded tab (rAF stops ticking, which is the same freeze for free).
 */

/** How much of the frame must be on screen for the clock to run. The same
 *  0.35 the closing act uses for its play trigger, for the same reason: low
 *  enough that a reader parked with the frame half-entered still gets the
 *  take, high enough that it cannot burn its opening beats as a sliver. */
const RUN_THRESHOLD = 0.35;

/** The tallest day bar in the momentum panel — the fixture's heavy evening.
 *  Chosen by measurement, not by index, so a fixture reshuffle cannot make
 *  the take click an empty day. */
function tallestDayBar(d: Director): HTMLElement | null {
  const bars = Array.from(
    d
      .find('[data-testid="pulse-detail"]')
      .querySelectorAll<HTMLElement>('button[aria-label$="show these on the board"]'),
  );
  let best: HTMLElement | null = null;
  for (const bar of bars) {
    if (!best || bar.clientHeight > best.clientHeight) best = bar;
  }
  return best;
}

/** The oner. Every `say` line is `ACT.narration`, in order — the unit gate
 *  holds the two in sync, so the script cannot drift from the copy. */
const take = async (d: Director) => {
  await d.waitFor(() => d.query('button[aria-label^="Open "]'), 12000, "the board");
  await d.fitAll(0);
  d.say(ACT.narration[0]);
  await d.hold(1600);

  d.enterCursor();
  const pulseTrigger = () => d.query('button[aria-controls="pulse-detail"]');
  await d.moveTo(pulseTrigger);
  d.say(ACT.narration[1]);
  await d.click(pulseTrigger);
  await d.waitFor(() => d.query('[data-testid="pulse-detail"]'), 5000, "the pulse panel");
  await d.hold(900);

  d.say(ACT.narration[2]);
  await d.click(() => tallestDayBar(d));
  d.say(ACT.narration[3]);
  // One beat of the board's own glide, then the camera FOLLOWS the collapse
  // rather than reacting to it: the filter empties most of the stage in
  // ~200ms, and a camera that sat out a long hold left the shrunken board
  // floating in the frame's void for two seconds at tall viewports
  // (measured at 1024x1120 on the production build). `punchTo`, never an
  // authored scale: the survivors are what must fill the frame, and how much
  // scale that takes depends on the frame and on how far the board just
  // shrank — see the director's docblock for the production screenshot the
  // authored `zoomTo(…, 1)` earned here.
  await d.hold(220);
  await d.punchTo(() => d.find('[data-testid="worklist-pane"]'), 1500);
  await d.hold(1900);

  const kestrel = () => d.query('button[aria-label^="Open Kestrel Dynamics"]');
  await d.click(kestrel);
  await d.waitFor(() => d.query('[data-testid="application-detail"]'), 6000, "the detail pane");
  d.say(ACT.narration[4]);
  // Top-aligned: the pane is taller than most frames, and the beat's line
  // names its head — the assessment, its deadline — not its middle.
  await d.punchTo(() => d.find('[data-testid="application-detail"]'), 1600, 0.85, "top");
  await d.hold(2600);

  const clear = () => d.query('[data-testid="pulse-filter-band"] button');
  await d.moveTo(clear);
  d.say(ACT.narration[5]);
  await d.click(clear);
  await d.fitAll(1600);
  d.say(ACT.narration[6]);
  await d.hold(1000);
  d.hideCursor();
};

export function OnerStage({
  frameRef,
  disarmed,
  paused,
  onCaption,
  onPhase,
}: {
  /** The clipping stage box `WindowAct` renders — the director's frame. */
  frameRef: RefObject<HTMLDivElement | null>;
  /** Reduced motion: mount the resting board, never construct a director.
   *  The surface stays the live product — that is the resting state. */
  disarmed: boolean;
  /** The visitor's pause control (WCAG 2.2.2 — the parent renders it). */
  paused: boolean;
  onCaption: (line: string) => void;
  onPhase: (phase: OnerPhase) => void;
}) {
  const cameraRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const directorRef = useRef<Director | null>(null);
  const offscreenRef = useRef(true);
  const startedOnce = useRef(false);
  /** Whether the SCRIPT currently owns the director — false once it has
   *  finished, failed, or been stood down by the visitor's own hand. */
  const takeActiveRef = useRef(false);

  const pausedRef = useRef(paused);
  useEffect(() => {
    pausedRef.current = paused;
    const d = directorRef.current;
    if (d) d.paused = paused || offscreenRef.current;
  }, [paused]);

  const start = useCallback(() => {
    const frame = frameRef.current;
    const camera = cameraRef.current;
    const stage = stageRef.current;
    const cursor = cursorRef.current;
    if (!frame || !camera || !stage || !cursor) return;
    directorRef.current?.cancel();
    cursor.style.opacity = "0";
    const d = new Director(frame, camera, stage, cursor, onCaption);
    directorRef.current = d;
    takeActiveRef.current = true;
    d.paused = pausedRef.current || offscreenRef.current;
    onPhase("playing");
    void take(d)
      .then(() => {
        if (directorRef.current !== d) return;
        takeActiveRef.current = false;
        onPhase("done");
      })
      .catch((err: unknown) => {
        if (directorRef.current !== d) return;
        takeActiveRef.current = false;
        if (err instanceof TakeError && err.message === "cancelled") return;
        // A take that cannot find its target must say so, not half-play.
        console.warn("[window-act] take failed:", err);
        onCaption(ACT.failed);
        onPhase("failed");
        // And it must not strand the camera mid-shot: whatever beat it died
        // on, the frame glides home to the whole board — the same resting
        // composition the visitor's own hand buys. A failed take may not
        // leave a crop, or a void, as its last word.
        takeActiveRef.current = false;
        void d.fitAll(600).catch(() => {
          // Cancelled by a replay remount — nothing to recover.
        });
      });
  }, [frameRef, onCaption, onPhase]);

  /**
   * The visitor's hand outranks the script. A REAL press on the stage — the
   * director's own events are `isTrusted: false`, which is what tells the
   * two hands apart — cancels the take mid-line and glides the camera home,
   * where the whole board, and any pane the visitor then opens, is inside
   * the frame. This is the new act's answer to the defect the scrubbed act
   * solved with its camera release (the pane whose × the crop held
   * off-screen, closeable only with Escape): the moment the page stops
   * narrating, the frame stops cropping.
   */
  useEffect(() => {
    if (disarmed) return;
    const stage = stageRef.current;
    if (!stage) return;
    const takeOver = (event: Event) => {
      if (!event.isTrusted || !takeActiveRef.current) return;
      const frame = frameRef.current;
      const camera = cameraRef.current;
      const cursor = cursorRef.current;
      if (!frame || !camera || !cursor) return;
      takeActiveRef.current = false;
      directorRef.current?.cancel();
      const home = new Director(frame, camera, stage, cursor, onCaption);
      directorRef.current = home;
      home.hideCursor();
      onCaption(ACT.yours);
      onPhase("done");
      void home.fitAll(600).catch(() => {
        // Cancelled by a replay remount — nothing to recover.
      });
    };
    stage.addEventListener("pointerdown", takeOver, true);
    stage.addEventListener("keydown", takeOver, true);
    return () => {
      stage.removeEventListener("pointerdown", takeOver, true);
      stage.removeEventListener("keydown", takeOver, true);
    };
  }, [disarmed, frameRef, onCaption, onPhase]);

  // Auto-play once in view; freeze whenever the frame leaves the viewport.
  useEffect(() => {
    if (disarmed) return;
    const frame = frameRef.current;
    if (!frame || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        offscreenRef.current = entry.intersectionRatio < RUN_THRESHOLD;
        const d = directorRef.current;
        if (d) d.paused = pausedRef.current || offscreenRef.current;
        if (!offscreenRef.current && !startedOnce.current) {
          startedOnce.current = true;
          start();
        }
      },
      { threshold: RUN_THRESHOLD },
    );
    io.observe(frame);
    return () => io.disconnect();
  }, [disarmed, frameRef, start]);

  useEffect(() => () => directorRef.current?.cancel(), []);

  if (disarmed) {
    return (
      <div className="p-4 lg:p-5">
        <MarketingBoard />
      </div>
    );
  }

  return (
    <>
      <div ref={cameraRef} style={{ transformOrigin: "0 0" }}>
        <div ref={stageRef} className="p-4 lg:p-5">
          <MarketingBoard />
        </div>
      </div>
      {/* The synthesized pointer. `pointer-events-none`, so the visitor's
          own hand always wins over the page's. */}
      <div
        ref={cursorRef}
        aria-hidden
        className="pointer-events-none absolute left-0 top-0 z-20 opacity-0 transition-opacity duration-300"
      >
        <svg
          width="19"
          height="22"
          viewBox="0 0 19 22"
          className="-translate-x-[3px] -translate-y-[2px] drop-shadow-[0_1px_2px_rgb(0_0_0/0.5)]"
        >
          <path
            d="M3 1 L3 17.5 L7.2 13.9 L9.9 20.2 L12.7 19 L9.9 12.8 L15.4 12.3 Z"
            fill="#fff"
            stroke="#111"
            strokeWidth="1.1"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </>
  );
}
