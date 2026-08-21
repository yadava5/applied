"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";

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
 * THE RECUT'S TWO RULES (2026-08-21, the owner's rejection of the zoomed
 * cut, re-authored from scratch rather than patched):
 *   · the take plays AT NATURAL SIZE, start to finish — the board at the
 *     browser zoom a person actually keeps, the director's camera locked at
 *     scale 1 and moving only the way a reader's own scroll does. No
 *     establishing fit, no close-ups, no push-ins: the cinematic zoom this
 *     page does spend lives on the descent's rail boxes, not here;
 *   · THE CAMERA FRAMES WHAT THE POINTER PRESSES, BEFORE IT PRESSES IT.
 *     Every beat pans first (`panTo`, awaited alongside the pointer's own
 *     travel) and clicks second, so no press can land outside the frame —
 *     the invariant all three of the owner's complaints about the previous
 *     cut violated, and the one the e2e press gate now measures.
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
 *  holds the two in sync, so the script cannot drift from the copy.
 *
 *  Beat grammar, uniform on purpose: frame the control (`panTo`, riding with
 *  the pointer's glide), press it, then let the camera follow the READING —
 *  the panel that opened, the survivors, the pane's head — as its own move.
 *  The pans are scroll-into-view, so a control already in frame costs no
 *  motion at all: at tall frames the whole board fits at natural size and
 *  the camera never stirs, which is correct, not a degenerate case. */
const take = async (d: Director) => {
  await d.waitFor(() => d.query('button[aria-label^="Open "]'), 12000, "the board");
  d.say(ACT.narration[0]);
  await d.hold(1600);

  d.enterCursor();
  // The momentum cell BY NAME — `aria-controls="pulse-detail"` is shared by
  // every pulse cell, and the first match once sent the previous cut toward
  // the wrong card. The name is the cell's own accessible label.
  const pulseTrigger = () => d.query('button[aria-label="Momentum detail"]');
  await Promise.all([d.panTo(pulseTrigger), d.moveTo(pulseTrigger)]);
  d.say(ACT.narration[1]);
  await d.click(pulseTrigger);
  await d.waitFor(() => d.query('[data-testid="pulse-detail"]'), 5000, "the pulse panel");
  // The press's answer is the shot now: bring the opened panel into frame
  // whole, so the bar the next beat presses is never cropped mid-story.
  await d.panTo(() => d.query('[data-testid="pulse-detail"]'));
  await d.hold(900);

  d.say(ACT.narration[2]);
  const bar = () => tallestDayBar(d);
  await Promise.all([d.panTo(bar), d.moveTo(bar)]);
  await d.click(bar);
  d.say(ACT.narration[3]);
  // The filter collapses the board in one layout pass; the camera's own
  // reframe absorbs whatever that leaves out of clamp, and this pan seats
  // the survivors' head — the filter band and the rows that answered.
  await d.panTo(() => d.find('[data-testid="worklist-pane"]'), "top");
  await d.hold(1900);

  const kestrel = () => d.query('button[aria-label^="Open Kestrel Dynamics"]');
  await Promise.all([d.panTo(kestrel), d.moveTo(kestrel)]);
  await d.click(kestrel);
  await d.waitFor(() => d.query('[data-testid="application-detail"]'), 6000, "the detail pane");
  d.say(ACT.narration[4]);
  // Top-aligned: the pane is taller than most frames, and the beat's line
  // names its head — the assessment, its deadline — not its middle.
  await d.panTo(() => d.find('[data-testid="application-detail"]'), "top");
  await d.hold(2600);

  const clear = () => d.query('[data-testid="pulse-filter-band"] button');
  await Promise.all([d.panTo(clear), d.moveTo(clear)]);
  d.say(ACT.narration[5]);
  await d.click(clear);
  await d.panHome(1100);
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

  const onCaptionRef = useRef(onCaption);
  useEffect(() => {
    onCaptionRef.current = onCaption;
  }, [onCaption]);

  /**
   * The director exists from MOUNT, not from the take's first beat — and in
   * a LAYOUT effect, deliberately: its constructor seeds the resting shot
   * (the board's own top, natural size) synchronously, so the seed is on
   * the camera before the stage's first paint. Production opened with
   * ~500ms of an untransformed camera and then a hard snap when the take's
   * first write landed (measured 2026-08-20); now there is no frame it
   * could show untransformed, and any stage growth between mount and take
   * start (the skeleton giving way to the board) is absorbed by the
   * director's own reframe as a move.
   */
  useLayoutEffect(() => {
    if (disarmed) return;
    const frame = frameRef.current;
    const camera = cameraRef.current;
    const stage = stageRef.current;
    const cursor = cursorRef.current;
    if (!frame || !camera || !stage || !cursor) return;
    const d = new Director(frame, camera, stage, cursor, (line) => onCaptionRef.current(line));
    directorRef.current = d;
    d.paused = pausedRef.current || offscreenRef.current;
    return () => {
      if (directorRef.current === d) directorRef.current = null;
      d.cancel();
    };
  }, [disarmed, frameRef]);

  const start = useCallback(() => {
    const d = directorRef.current;
    const cursor = cursorRef.current;
    if (!d || !cursor) return;
    cursor.style.opacity = "0";
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
        // on, the frame glides home to the board's own top — the same
        // resting composition the visitor's own hand buys. A failed take
        // may not leave a crop as its last word.
        takeActiveRef.current = false;
        void d.panHome(600).catch(() => {
          // Cancelled by a replay remount — nothing to recover.
        });
      });
  }, [onCaption, onPhase]);

  /**
   * The visitor's hand outranks the script. A REAL press on the stage — the
   * director's own events are `isTrusted: false`, which is what tells the
   * two hands apart — cancels the take mid-line and glides the camera home,
   * where the board reads from its own top and any pane the visitor then
   * opens is theirs to scroll. This is the new act's answer to the defect
   * the scrubbed act solved with its camera release (the pane whose × the
   * crop held off-screen, closeable only with Escape): the moment the page
   * stops narrating, the frame stops framing.
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
      void home.panHome(600).catch(() => {
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

  /*
   * `h-full` ON BOTH WRAPPERS, and it is a bug fix rather than a tidy-up.
   *
   * `MarketingBoard`'s own root is `flex h-full flex-col gap-4`: it is written
   * to fill whatever it is given. On this path it was given nothing. The chain
   * ran frame (a real height, `calc(100dvh - 11rem)`) → camera div (auto) →
   * this wrapper (auto), so the board's `h-full` resolved against an
   * auto-height parent and collapsed to its content.
   *
   * Nobody saw it while the board was full, because ten rows overflow the
   * frame anyway. Filter the stage lens to anything but "all" and the board
   * shrinks to its rows while the frame stays a viewport tall: measured on
   * production at 1512x893, the assessment lens left 343px of the 717px
   * camera as bare page background, 47.8% of the window, and the whole
   * composition read as broken. That is #392.
   *
   * The skeleton path three files up already passes `h-full p-4 lg:p-5` for
   * exactly this reason. The real path dropped it.
   */
  if (disarmed) {
    return (
      <div className="h-full p-4 lg:p-5">
        <MarketingBoard />
      </div>
    );
  }

  return (
    <>
      <div ref={cameraRef} className="h-full" style={{ transformOrigin: "0 0" }}>
        <div ref={stageRef} className="h-full p-4 lg:p-5">
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
