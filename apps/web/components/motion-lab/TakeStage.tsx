"use client";

import { Pause, Play, RotateCcw } from "lucide-react";
import { LayoutGroup } from "motion/react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Director, TakeError } from "./director";

export type TakeScript = (d: Director) => Promise<void>;

/**
 * The shared stage every take plays on: a framed viewport holding a camera
 * wrapper, a synthesized pointer overlay, a narration line, and the controls
 * a long autoplaying take owes its viewer — pause, resume, replay.
 *
 * Honesty rules the frame enforces:
 *   - the children are REAL mounted components. The stage never screenshots
 *     or redraws them, and they stay interactive under the take — drag a
 *     card mid-take and the board answers you, not the script;
 *   - replay REMOUNTS the children (key bump), so a take that mutated real
 *     state — a sync that filed rows, a pane that opened — starts over from
 *     the product's own initial state, never from a rewound recording;
 *   - `prefers-reduced-motion` disarms the take entirely: the surface
 *     renders at rest and the caption says so. The plate's own prose still
 *     argues the treatment, so motion is never the only carrier.
 *
 * The take auto-plays once when the frame scrolls into view, freezes while
 * it is out of view (the director's clock pauses, so nothing ever finishes
 * unwatched), and then waits for an explicit replay.
 */
export function TakeStage({
  take,
  children,
  height = 560,
  frameLabel = "live take — real components, a synthesized pointer",
  opening,
}: {
  take: TakeScript;
  children: React.ReactNode;
  /** The viewport's height in px. The camera crops; nothing is resized. */
  height?: number;
  /** The header strip's honesty line. */
  frameLabel?: string;
  /** The caption before the take starts (and its reduced-motion text base). */
  opening: string;
}) {
  // Namespaces every descendant `layoutId` (motion's `useLayoutId` prefixes
  // with the nearest LayoutGroup id, and nested groups inherit it). Without
  // this, five board mounts on one page share `app-N` ids and motion's
  // shared-layout system treats them as ONE element that "moved" between
  // plates — it promotes the last mount and freezes the rest at opacity 0
  // mid-crossfade. Measured on this page before the fix: rows carrying
  // `opacity: 0; translate3d(…, 8173px, …); pointer-events: none`.
  const groupId = useId();
  const frameRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const directorRef = useRef<Director | null>(null);

  const [runId, setRunId] = useState(0);
  const [caption, setCaption] = useState(opening);
  const [phase, setPhase] = useState<"idle" | "playing" | "done" | "failed">("idle");
  const [userPaused, setUserPaused] = useState(false);
  const userPausedRef = useRef(false);
  const offscreenRef = useRef(true);
  const startedOnce = useRef(false);
  const [reduced, setReduced] = useState<boolean | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  // The script in a ref, refreshed by effect, so `start` stays stable and
  // the autoplay observer is not rebuilt on every caption re-render.
  const takeRef = useRef(take);
  useEffect(() => {
    takeRef.current = take;
  }, [take]);

  const start = useCallback(() => {
    const frame = frameRef.current;
    const camera = cameraRef.current;
    const stage = stageRef.current;
    const cursor = cursorRef.current;
    if (!frame || !camera || !stage || !cursor) return;
    directorRef.current?.cancel();
    cursor.style.opacity = "0";
    const d = new Director(frame, camera, stage, cursor, setCaption);
    directorRef.current = d;
    d.paused = userPausedRef.current || offscreenRef.current;
    setPhase("playing");
    void takeRef.current(d)
      .then(() => {
        if (directorRef.current === d) setPhase("done");
      })
      .catch((err: unknown) => {
        if (directorRef.current !== d) return;
        if (err instanceof TakeError && err.message === "cancelled") return;
        // A take that cannot find its target must say so, not half-play.
        console.warn("[motion-lab] take failed:", err);
        setCaption("The take could not finish here — replay to run it again.");
        setPhase("failed");
      });
  }, []);

  // Auto-play once in view; freeze whenever the frame leaves the viewport.
  useEffect(() => {
    if (reduced !== false) return;
    const frame = frameRef.current;
    if (!frame) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        offscreenRef.current = !entry.isIntersecting;
        const d = directorRef.current;
        if (d) d.paused = userPausedRef.current || offscreenRef.current;
        if (entry.isIntersecting && !startedOnce.current) {
          startedOnce.current = true;
          start();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(frame);
    return () => io.disconnect();
  }, [reduced, start]);

  // Replay = remount the children (fresh product state), then re-run.
  const wantsRestart = useRef(false);
  useEffect(() => {
    if (!wantsRestart.current) return;
    wantsRestart.current = false;
    // Two frames so the remounted subtree has committed and laid out; the
    // script's own waitFor covers dynamic chunks beyond that.
    const id = requestAnimationFrame(() => requestAnimationFrame(start));
    return () => cancelAnimationFrame(id);
  }, [runId, start]);

  const replay = () => {
    directorRef.current?.cancel();
    directorRef.current = null;
    setUserPaused(false);
    userPausedRef.current = false;
    setCaption(opening);
    setPhase("idle");
    wantsRestart.current = true;
    setRunId((n) => n + 1);
  };

  const togglePause = () => {
    if (phase !== "playing") {
      if (phase === "idle" && !startedOnce.current) {
        startedOnce.current = true;
        start();
      } else replay();
      return;
    }
    const next = !userPaused;
    setUserPaused(next);
    userPausedRef.current = next;
    const d = directorRef.current;
    if (d) d.paused = next || offscreenRef.current;
  };

  useEffect(() => () => directorRef.current?.cancel(), []);

  const playing = phase === "playing" && !userPaused;

  return (
    <figure className="m-0">
      <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
        <div className="flex items-center gap-2 border-b border-line-soft px-4 py-2">
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-viz-rules" />
          <span className="label-caps min-w-0 flex-1 truncate">{frameLabel}</span>
          {reduced === false && (
            <span className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={togglePause}
                aria-label={playing ? "Pause the take" : "Play the take"}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-strong"
              >
                {playing ? (
                  <Pause className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <Play className="h-3.5 w-3.5" aria-hidden />
                )}
              </button>
              <button
                type="button"
                onClick={replay}
                aria-label="Replay the take from the start"
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-strong"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              </button>
            </span>
          )}
        </div>

        <div
          ref={frameRef}
          className="relative overflow-hidden bg-background"
          style={{ height }}
        >
          <div key={runId} ref={cameraRef} style={{ transformOrigin: "0 0" }}>
            <div ref={stageRef} className="p-4">
              <LayoutGroup id={groupId}>{children}</LayoutGroup>
            </div>
          </div>
          {/* The synthesized pointer. `pointer-events-none`, so the visitor's
              own hand always wins over the page's. */}
          <div
            ref={cursorRef}
            aria-hidden
            className="absolute left-0 top-0 z-20 opacity-0 transition-opacity duration-300"
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
        </div>

        <figcaption
          aria-live="polite"
          className="min-h-[3.25rem] border-t border-line-soft px-4 py-3 text-sm leading-relaxed text-muted"
        >
          {reduced
            ? "Motion is off — your reduced-motion setting is respected, and the surface above is the live product at rest."
            : caption}
        </figcaption>
      </div>
    </figure>
  );
}

/** The lab's 1024 rule, stated where a wide-only stage cannot mount. */
export function NarrowNote({ what }: { what: string }) {
  return (
    <p className="rounded-xl border border-dashed border-line-soft px-4 py-6 text-sm text-dim">
      {what} needs the wide board — view this plate at 1024px or above.
    </p>
  );
}
