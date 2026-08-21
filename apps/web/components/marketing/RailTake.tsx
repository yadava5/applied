"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ACT } from "./copy";
import { TakeClock, TakeError } from "./director";

/** One beat of a rail take: what the exhibit does, what the line says, and
 *  how long it dwells at AUTHORED tempo. The take is a list of these rather
 *  than an opaque script so the rail can know its own total length (the
 *  governor steers by it) and can compose its ending in one pass when a
 *  visitor outruns even the compressed take — see `compose`. */
export interface RailBeat {
  /** Put the exhibit in this beat's state — a pure state write, idempotent,
   *  so replaying or composing the list is always legal. */
  enter: () => void;
  /** The narration for this beat. */
  line: string;
  /** The beat's dwell at rate 1, ms. */
  hold: number;
}

/**
 * A pinned rail running a TAKE — the lab's grammar (`demo/motion-lab`'s
 * `TakeStage`), recomposed for a rail's frame rather than transplanted as a
 * full-width plate. What survives the recomposition is everything the owner
 * chose the treatments for: a pausable clock, a narration line that names
 * each beat, autoplay, and a Pause/Replay transport (WCAG 2.2.2 — an
 * autoplaying sequence owes its viewer a pause). What does not survive is
 * the plate's window chrome: the exhibits these rails carry draw their own
 * cards, and a frame around a frame is furniture. So the rail keeps the
 * page's own rail grammar — a `label-caps` strip on top (the honesty line,
 * with the transport at its right, the window act's arrangement), the
 * narration as a quiet line beneath it, height-reserved so a longer beat
 * cannot shove the pinned exhibit, then the exhibit.
 *
 * The 02b/08c picks carry NO camera and NO pointer — "the object itself
 * travels", the lab's own words — so the clock (`TakeClock`) is all this
 * mounts; a rail that needs the full director must say why.
 *
 * THE BAND IS A BUDGET, NOT A COINCIDENCE (2026-08-20, the owner's report).
 * The first cut ran the clock on visibility alone, which left where a beat
 * LANDS a pure function of the visitor's scroll speed: measured at
 * 1440x900, the take armed 488px before the pin, the dissolve beat rendered
 * 246px past release at 250px/s (his screenshot — the rail riding out of
 * frame with the next phase already underneath), and at ≥300px/s the last
 * two beats were not late but UNREACHABLE — the clock froze below the
 * visibility threshold and never resumed. The take stays a take — narrated,
 * autoplaying, pausable, never a scrub (his explicit direction, twice) —
 * but its relationship to the band is now a contract with three clauses:
 *
 *   · the clock STARTS AT THE PIN, not at 0.35 visibility, so the opening
 *     beats play pinned instead of burning on the approach;
 *   · a GOVERNOR couples the clock's rate to pin progress (`TakeClock.rate`,
 *     floor 1): a parked reader gets the authored tempo, a moving reader's
 *     take compresses just enough to complete before release — aimed at
 *     `LEAD` of the remaining band, so the story ends while the rail still
 *     holds;
 *   · a visitor who outruns even the compressed take (past `RATE_MAX`, a
 *     hard flick) finds the exhibit COMPOSED at its final beat when the
 *     rail leaves below — the closing act's own grammar: scrolled past
 *     means found finished, never frozen mid-sentence. Leaving above still
 *     freezes: the visitor is coming back down through the band.
 *
 * THE EXHIBIT'S STATE LIVES WITH THE CALLER. The beats own it: the first
 * beat must put the exhibit at its opening state, because the resting state
 * IS the initial render — SSR, no-JS and reduced motion all land on the
 * exhibit's most demonstrative still, and only a running take winds it back
 * to act it out. Replay re-runs the beats at rate 1 (the governor rebases,
 * so a parked replay never races to catch up with scroll that already
 * happened); every beat is a pure state walk, so a remount would reset
 * nothing the first beat does not.
 *
 * The clock still freezes whenever the rail leaves the viewport mid-band
 * (nothing may finish unwatched — the window act's guarantee) and whenever
 * the visitor pauses; a backgrounded tab freezes for free, because rAF
 * stops ticking.
 */

/** How much of the exhibit must be on screen for the clock to RUN — the
 *  freeze threshold, unchanged. Starting is stricter than running: the
 *  start also waits for the pin (see `maybeStart`), but once playing, this
 *  is the only visibility the clock needs to keep advancing. */
const RUN_THRESHOLD = 0.35;

/** The share of the remaining band the take aims to complete within, so the
 *  last beat lands with pin still to spare — the governor's lag (it pursues,
 *  never leads) eats into the reserve instead of past the release. */
const LEAD = 0.8;

/** How fast the governor closes a deficit, ms of take-time per unit rate
 *  above 1. Small = tight pursuit; the sustained-rate lag this produces at
 *  a given scroll speed is deficit ≈ (rate − 1) · CATCHUP_MS. */
const CATCHUP_MS = 350;

/** The compression ceiling. Past it a take is a blur, not a story — a
 *  visitor moving faster than this can carry gets the composed ending at
 *  exit instead (`compose`). */
const RATE_MAX = 8;

export function RailTake({
  beats,
  label,
  opening,
  resting,
  children,
}: {
  /** The take, in order. The rail derives its total length from the holds. */
  beats: readonly RailBeat[];
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
  /** Pin progress at the take's start (or last rebase) — the governor's
   *  origin, so only scroll SINCE the take began creates a deficit. */
  const startPinRef = useRef<number | null>(null);

  const [caption, setCaption] = useState(opening);
  const [phase, setPhase] = useState<"idle" | "playing" | "done">("idle");
  const phaseRef = useRef(phase);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);
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

  const beatsRef = useRef(beats);
  useEffect(() => {
    beatsRef.current = beats;
  }, [beats]);

  /** The sticky box this rail pins by — found once, walking up from the
   *  rail's own root, because the pin is the caller's markup (`sticky` on
   *  an ancestor) and the rail must not hard-code its own container. `null`
   *  means the rail is not pinned (a future restaging): the governor and
   *  the pin gate stand down and the take arms on visibility alone — the
   *  old contract, degraded loudly by the pinned-beats gate rather than by
   *  a broken page. */
  const stickyRef = useRef<HTMLElement | null | undefined>(undefined);
  const stickyBox = useCallback((): HTMLElement | null => {
    if (stickyRef.current !== undefined) return stickyRef.current;
    let el: HTMLElement | null = boxRef.current?.parentElement ?? null;
    for (let hops = 0; el && hops < 4; hops++) {
      if (getComputedStyle(el).position === "sticky") {
        stickyRef.current = el;
        return el;
      }
      el = el.parentElement;
    }
    stickyRef.current = null;
    return null;
  }, []);

  /** Where the rail is in its own band: <0 approaching the pin, 0..1 pinned
   *  (the sticky box travelling its runway), >1 released. Every term is a
   *  live measurement — the band moves with viewport and content, and a
   *  cached geometry here would be the `--exhibit` stale-constant defect in
   *  a new coat. */
  const pinProgress = useCallback((): number | null => {
    const el = stickyBox();
    const cell = el?.parentElement;
    if (!el || !cell) return null;
    const top = parseFloat(getComputedStyle(el).top);
    if (!Number.isFinite(top)) return null;
    const runway = cell.getBoundingClientRect().height - el.offsetHeight;
    if (runway <= 0) return null;
    return (top - cell.getBoundingClientRect().top) / runway;
  }, [stickyBox]);

  const start = useCallback(() => {
    clockRef.current?.cancel();
    const clock = new TakeClock(setCaption);
    clockRef.current = clock;
    clock.paused = pausedRef.current || offscreenRef.current;
    startPinRef.current = null;
    setPhase("playing");
    void (async () => {
      for (const beat of beatsRef.current) {
        beat.enter();
        clock.say(beat.line);
        await clock.hold(beat.hold);
      }
    })()
      .then(() => {
        if (clockRef.current === clock) setPhase("done");
      })
      .catch((err: unknown) => {
        if (clockRef.current !== clock) return;
        if (err instanceof TakeError && err.message === "cancelled") return;
        // The beats are pure state walks — a throw here is a bug, not a
        // vanished target. Land on done: the exhibit is wherever the walk
        // left it, which for every beat list here is a legible state.
        console.warn("[rail-take] take failed:", err);
        setPhase("done");
      });
  }, []);

  /** The ending, composed in one pass — every beat's state in order, the
   *  last line on the strip, phase done. For the visitor who outran the
   *  take: scrolled past means found finished (the closing act's grammar),
   *  never a rail frozen mid-sentence below the fold — the measured defect
   *  was a caption stuck on beat 1 for 15 parked seconds. */
  const compose = useCallback(() => {
    clockRef.current?.cancel();
    clockRef.current = null;
    const list = beatsRef.current;
    for (const beat of list) beat.enter();
    const last = list[list.length - 1];
    if (last) setCaption(last.line);
    setPhase("done");
  }, []);

  /** Start once the rail is BOTH meaningfully visible and at its pin, so
   *  the opening beats play pinned instead of burning on the approach (the
   *  measured 488px of pre-pin arming). An unpinned rail (no sticky
   *  ancestor) starts on visibility alone. */
  const maybeStart = useCallback(() => {
    if (startedOnce.current || offscreenRef.current) return;
    const p = pinProgress();
    if (p !== null && p < 0) return;
    startedOnce.current = true;
    start();
  }, [pinProgress, start]);

  // Visibility: freeze whenever the rail leaves the viewport mid-band, and
  // compose the ending when it leaves BELOW with the band already spent.
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
        if (offscreenRef.current && phaseRef.current === "playing") {
          const p = pinProgress();
          if (p !== null && p >= 1) compose();
        }
        maybeStart();
      },
      { threshold: RUN_THRESHOLD },
    );
    io.observe(box);
    return () => io.disconnect();
  }, [armed, compose, maybeStart, pinProgress]);

  // The pin is a scroll position, which the observer cannot see — so the
  // start condition is also re-checked as the visitor scrolls the rail onto
  // its pin. rAF-throttled, one layout read per frame at most, and it stands
  // down for good once the take has started.
  useEffect(() => {
    if (!armed) return;
    let frame = 0;
    const check = () => {
      frame = 0;
      maybeStart();
    };
    const schedule = () => {
      if (!frame && !startedOnce.current) frame = requestAnimationFrame(check);
    };
    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [armed, maybeStart]);

  // THE GOVERNOR. While the take plays, its clock pursues the visitor's own
  // progress through the band: the target is the share of the remaining
  // band consumed since the take started (aimed at `LEAD` of it), and the
  // rate rises above 1 only while the take is behind that target. Parked,
  // the deficit drains and the rate settles back to 1 — the authored tempo
  // is the resting speed, acceleration is borrowed, never kept. Rebased
  // after every pause or freeze, so scroll that happened while the clock
  // was stopped is forgiven rather than crammed into the next second.
  useEffect(() => {
    if (!armed || phase !== "playing") return;
    const total = beatsRef.current.reduce((ms, beat) => ms + beat.hold, 0);
    if (total <= 0) return;
    let raf = 0;
    let wasStopped = true; // treat the first frame as a resume: it rebases
    const tick = () => {
      const clock = clockRef.current;
      if (!clock) return;
      const p = pinProgress();
      if (p !== null) {
        if (clock.paused) {
          wasStopped = true;
        } else {
          const pinned = Math.min(1, Math.max(0, p));
          if (wasStopped || startPinRef.current === null) {
            // Rebase: choose the origin so the current position maps to the
            // take-time already elapsed — zero deficit at this instant.
            const g = Math.min(1, clock.elapsed / total) * LEAD;
            startPinRef.current = g >= 1 ? pinned : Math.min(pinned, Math.max(0, (pinned - g) / (1 - g)));
            wasStopped = false;
          }
          const origin = startPinRef.current;
          const span = 1 - origin;
          const target =
            span > 0.001 ? Math.min(1, Math.max(0, (pinned - origin) / (LEAD * span))) : 1;
          const deficit = target * total - clock.elapsed;
          clock.rate = Math.min(RATE_MAX, Math.max(1, 1 + deficit / CATCHUP_MS));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [armed, phase, pinProgress]);

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
    <div ref={boxRef} data-take-phase={phase}>
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
