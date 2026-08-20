"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ACT } from "./copy";
import { TakeClock, TakeError } from "./director";

export type RailTakeScript = (clock: TakeClock) => Promise<void>;

/**
 * A pinned rail running a TAKE — the lab's grammar (`demo/motion-lab`'s
 * `TakeStage`), recomposed for a rail's frame rather than transplanted as a
 * full-width plate. What survives the recomposition is everything the owner
 * chose the treatments for: a pausable clock, a narration line that names
 * each beat, autoplay once the exhibit is in view, and a Pause/Replay
 * transport (WCAG 2.2.2 — an autoplaying sequence owes its viewer a pause).
 * What does not survive is the plate's window chrome: the exhibits these
 * rails carry draw their own cards, and a frame around a frame is furniture.
 * So the rail keeps the page's own rail grammar — a `label-caps` strip on
 * top (the honesty line, with the transport at its right, the window act's
 * arrangement), the exhibit, and the narration as a quiet line beneath it,
 * height-reserved so a longer beat cannot shove the pinned exhibit.
 *
 * The 02b/08c picks carry NO camera and NO pointer — "the object itself
 * travels", the lab's own words — so the clock (`TakeClock`) is all this
 * mounts; a rail that needs the full director must say why.
 *
 * THE EXHIBIT'S STATE LIVES WITH THE CALLER. The script owns the beats: its
 * first act must put the exhibit at its opening state, because the resting
 * state IS the initial render — SSR, no-JS and reduced motion all land on
 * the exhibit's most demonstrative still, and only a running take winds it
 * back to act it out. Replay simply re-runs the script; every script here is
 * a pure walk over component state, so a remount would reset nothing the
 * first beat does not.
 *
 * The clock freezes whenever the rail leaves the viewport (nothing may
 * finish unwatched — the window act's guarantee, kept the same way) and
 * whenever the visitor pauses; a backgrounded tab freezes for free, because
 * rAF stops ticking.
 */

/** How much of the exhibit must be on screen for the clock to run — the
 *  window act's own threshold, for the same reason: low enough that a
 *  reader parked with the rail half-entered still gets the take. */
const RUN_THRESHOLD = 0.35;

export function RailTake({
  take,
  label,
  opening,
  resting,
  children,
}: {
  take: RailTakeScript;
  /** The strip's honesty line — what this exhibit IS, stated in caps. */
  label: string;
  /** The narration line before the take starts. */
  opening: string;
  /** The reduced-motion line: the exhibit is at rest, and says so. */
  resting: string;
  children: React.ReactNode;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const clockRef = useRef<TakeClock | null>(null);
  const offscreenRef = useRef(true);
  const startedOnce = useRef(false);
  const pausedRef = useRef(false);

  const [caption, setCaption] = useState(opening);
  const [phase, setPhase] = useState<"idle" | "playing" | "done">("idle");
  const [userPaused, setUserPaused] = useState(false);

  /** `null` until read, so the server render and first paint agree. */
  const [reduced, setReduced] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  const armed = reduced === false;

  const takeRef = useRef(take);
  useEffect(() => {
    takeRef.current = take;
  }, [take]);

  const start = useCallback(() => {
    clockRef.current?.cancel();
    const clock = new TakeClock(setCaption);
    clockRef.current = clock;
    clock.paused = pausedRef.current || offscreenRef.current;
    setPhase("playing");
    void takeRef
      .current(clock)
      .then(() => {
        if (clockRef.current === clock) setPhase("done");
      })
      .catch((err: unknown) => {
        if (clockRef.current !== clock) return;
        if (err instanceof TakeError && err.message === "cancelled") return;
        // These scripts are pure state walks — a throw here is a bug, not a
        // vanished target. Land on done: the exhibit is wherever the script
        // left it, which for every script here is a legible state.
        console.warn("[rail-take] take failed:", err);
        setPhase("done");
      });
  }, []);

  // Auto-play once in view; freeze whenever the rail leaves the viewport.
  useEffect(() => {
    if (!armed) return;
    const box = boxRef.current;
    if (!box || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        offscreenRef.current = entry.intersectionRatio < RUN_THRESHOLD;
        const clock = clockRef.current;
        if (clock) clock.paused = pausedRef.current || offscreenRef.current;
        if (!offscreenRef.current && !startedOnce.current) {
          startedOnce.current = true;
          start();
        }
      },
      { threshold: RUN_THRESHOLD },
    );
    io.observe(box);
    return () => io.disconnect();
  }, [armed, start]);

  useEffect(() => () => clockRef.current?.cancel(), []);

  const replay = () => {
    setUserPaused(false);
    pausedRef.current = false;
    start();
  };

  const togglePause = () => {
    const next = !userPaused;
    setUserPaused(next);
    pausedRef.current = next;
    const clock = clockRef.current;
    if (clock) clock.paused = next || offscreenRef.current;
  };

  const playing = phase === "playing" && !userPaused;

  return (
    <div ref={boxRef}>
      {/* The strip: honesty on the left, the transport on the right — the
          window act's arrangement, in the rail's own type. */}
      <div className="mb-2 flex min-h-4 items-baseline justify-between gap-x-4">
        <p className="label-caps min-w-0 truncate">{label}</p>
        {armed && (
          <span className="flex shrink-0 items-center gap-x-3">
            {phase === "playing" && (
              <button
                type="button"
                onClick={togglePause}
                className="label-caps py-1 transition-colors hover:text-strong"
              >
                {playing ? ACT.pause : ACT.play}
              </button>
            )}
            {phase !== "idle" && (
              <button
                type="button"
                onClick={replay}
                className="label-caps py-1 transition-colors hover:text-strong"
              >
                {ACT.replay}
              </button>
            )}
          </span>
        )}
      </div>

      {/* The narration — the beat's own words, ABOVE the exhibit: the window
          act's arrangement (strip, narration, stage), and on a rail it is
          also the honest one, because at 1024x600 the exhibit's own foot is
          what the fold crops, and the story must never be. Height-reserved
          to two lines so a longer beat cannot shove the pinned exhibit;
          polite, so a screen reader hears it at its own pace. */}
      <p aria-live="polite" className="mb-3 min-h-10 text-sm leading-5 text-muted">
        {reduced ? resting : caption}
      </p>

      {children}
    </div>
  );
}
