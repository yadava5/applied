"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";

import { MarketingBoard } from "./MarketingBoard";
import { ACT } from "./copy";
import { COVER_MAX, Director, TakeError } from "./director";

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

/**
 * The scale the day filter's collapse will demand, predicted from what is
 * measurable BEFORE the press — the brace's one input (see `Director.brace`
 * for why the press is the beat the camera must anticipate rather than
 * follow).
 *
 * The filtered stage is the pane it keeps, reassembled: the same chrome
 * above (plus the filter band that will mount), the pane's own head and
 * tail, and the surviving rows — which KEEP their stage headers, so the
 * present pane's average row pitch (headers amortised in) is the honest
 * pitch for them too. Probed at 1440x900, production build, 2026-08-20:
 * true filtered stage 417, this prediction 403 — 3.6% under, which is the
 * right side to miss on: an under-prediction over-covers, never voids, and
 * the resolver keeps being re-evaluated after the collapse, where its
 * terms are the REAL filtered pane and the live-cover floor takes over —
 * so the shot settles onto the true bound by itself and the punch confirms
 * it. The one term with no pre-press measurement is the filter band, and
 * it borrows the pulse strip's own cell height — the same strip family,
 * measured live, and smaller than the band it stands in for (56 vs 76 at
 * 1440).
 *
 * Nothing here is a frame-size or fixture constant: every term re-measures
 * live, so the prediction moves with the frame the page actually renders
 * (the gutter is about to widen — the arithmetic must not care). If any
 * term is unreadable — a relabelled bar, a reshaped pane — the resolver
 * degrades to the LIVE cover of the current stage: the brace becomes a
 * hold, the armed floor catches the collapse exactly as it did before the
 * brace existed, and the brace gate is what goes red rather than the frame
 * going void.
 */
const filteredCover = (d: Director, bar: () => HTMLElement | null) => () => {
  const f = d.frameRect();
  const live = f.height / Math.max(1, d.stageHeight());
  const degraded = Math.max(live, d.renderedScale);
  const pane = d.query('[data-testid="worklist-pane"]');
  const label = bar()?.getAttribute("aria-label") ?? "";
  const count = Number(/(\d+)\s+filed/.exec(label)?.[1]);
  if (!pane || !Number.isFinite(count) || count < 1) return degraded;
  const rows = d.queryAll('button[aria-label^="Open "]').filter((el) => el.offsetParent !== null);
  const first = rows[0]?.getBoundingClientRect();
  const last = rows[rows.length - 1]?.getBoundingClientRect();
  if (!first || !last || rows.length < 2) return degraded;
  const s = d.renderedScale;
  const paneR = pane.getBoundingClientRect();
  const paneTop = (paneR.top - d.stageRect().top) / s;
  const head = Math.max(0, (first.top - paneR.top) / s);
  const tail = Math.max(0, (paneR.bottom - last.bottom) / s);
  const pitch = (last.bottom - first.top) / s / rows.length;
  const strip = d.query('button[aria-controls="pulse-detail"]');
  const band = strip ? strip.getBoundingClientRect().height / s : 0;
  if (paneTop <= 0 || pitch <= 0) return degraded;
  const predicted = paneTop + band + head + count * pitch + tail;
  return Math.min(Math.max(f.height / predicted, live), COVER_MAX);
};

/** The oner. Every `say` line is `ACT.narration`, in order — the unit gate
 *  holds the two in sync, so the script cannot drift from the copy. */
const take = async (d: Director) => {
  await d.waitFor(() => d.query('button[aria-label^="Open "]'), 12000, "the board");
  // Arrive, never cut: the constructor seeded the establishing composition
  // before first paint, so this is usually a no-op glide — and when the
  // board landed a breath ago and the camera is still absorbing the
  // skeleton's fit, it completes the arrival on the authored ease.
  await d.fitAll(700);
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
  // THE PRESS IS ANTICIPATED, NOT FOLLOWED. The filter removes rows in a
  // single layout pass (measured: stage 783 → 417 between two frames 8ms
  // apart), so no floor, tween or observer can carry a camera across it
  // continuously from the establishing shot — at the collapse instant a
  // full frame simply requires the post-collapse cover scale, and anything
  // arriving later is either a cut or a void. Two earlier cuts proved both
  // halves: `zoomTo(…, 1)` earned the owner's 47%-void screenshot, and the
  // armed-floor-only version killed the void by snapping — "it just cuts
  // there", his words, at exactly this beat. So the camera now pushes in
  // WHILE the pointer travels to the bar (`brace` — top-anchored, at the
  // predicted post-collapse cover, floor armed as the backstop), the press
  // lands inside a frame every pixel of which survives the filter, the rows
  // file out as the product's own answer under a motionless camera, and the
  // punch relaxes onto the survivors as the reveal.
  const bar = () => tallestDayBar(d);
  await Promise.all([d.brace(filteredCover(d, bar)), d.moveTo(bar)]);
  await d.click(bar);
  d.say(ACT.narration[3]);
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

  const onCaptionRef = useRef(onCaption);
  useEffect(() => {
    onCaptionRef.current = onCaption;
  }, [onCaption]);

  /**
   * The director exists from MOUNT, not from the take's first beat — and in
   * a LAYOUT effect, deliberately: its constructor seeds the establishing
   * composition synchronously, so the seed is on the camera before the
   * stage's first paint. Production opened with ~500ms of the mounting
   * board at natural scale and then a hard snap to the establishing fit
   * (measured 2026-08-20), because the camera was only born at the take's
   * first beat; now there is no frame it could show untransformed, and any
   * stage growth between mount and take start (the skeleton giving way to
   * the board) is absorbed by the director's own reframe as a move.
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
        // on, the frame glides home to the whole board — the same resting
        // composition the visitor's own hand buys. A failed take may not
        // leave a crop, or a void, as its last word.
        takeActiveRef.current = false;
        void d.fitAll(600).catch(() => {
          // Cancelled by a replay remount — nothing to recover.
        });
      });
  }, [onCaption, onPhase]);

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
