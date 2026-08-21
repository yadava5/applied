"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BoardStill } from "./BoardStill";
import { ChangedRow } from "./ChangedRow";
import { OFFER_EMAIL } from "./verdictEmailData";
import { StageSkeleton } from "./LandingBoard";
import { NEW_TAB } from "./chrome";
import { useWideViewport } from "./scrub";
import { ACT, BOARD } from "./copy";
import type { OnerPhase } from "./OnerStage";

/**
 * The landing's first act: the workday oner — the owner's 01a pick
 * (2026-08-19), replacing the scroll-scrubbed offer choreography.
 *
 * ONE CONTINUOUS TAKE through a real working session, on the real board: the
 * synthesized pointer opens the pulse's momentum panel, presses the shipped
 * filed-on-a-date day bar (no control in the take is drawn for the camera),
 * the board narrows with its own glide, Kestrel's row opens, the pane docks
 * with the mail trail, the filter clears, and the camera returns home. The
 * camera follows the READING — it frames where the story goes next, the
 * survivors, then the pane — rather than chasing the click that caused it.
 * The script and its narration live in `OnerStage` / `ACT.narration`.
 *
 * MECHANISM — PIN AND PLAY, the closing act's mechanism at the page's other
 * bookend (both are the owner's call: the close "should PLAY, smooth and
 * flowing, once it is in view", and a director-driven take is that grammar
 * by construction — real clicks on real components cannot be scrubbed,
 * because the product's own state machines are not reversible functions of
 * a scroll offset). The window pins below the nav through a runway and the
 * take plays on its own PAUSABLE clock:
 *
 *   · the clock only runs while the frame is meaningfully on screen
 *     (`OnerStage`'s observer) — nothing can finish unwatched, which is the
 *     guarantee the scrubbed act made by construction and this act keeps by
 *     freezing;
 *   · the visitor outranks the clock: Pause/Replay in the frame's own
 *     chrome (WCAG 2.2.2 — a >5s autoplaying surface owes its viewer a
 *     pause), and their hand outranks the pointer — the board underneath
 *     stays the real, interactive product throughout;
 *   · the runway exists only when the take can run: it GROWS client-side
 *     (the closing act's pattern) so reduced motion and no-JS visitors get
 *     a content-height section instead of screens of pinned stillness. The
 *     growth adds height below the frame's fold-edge, so nothing a visitor
 *     is looking at moves.
 *
 * REDUCED MOTION disarms the take entirely: no director, no pointer, no
 * camera — the resting board, which is the live product and therefore the
 * legible resting state, with the narration strip saying so (`ACT.resting`).
 *
 * GEOMETRY. The frame's total height is unchanged from the scrubbed act —
 * caption strip (1.875rem) + chrome (2.4375rem) + stage — with the stage box
 * at `calc(100dvh - 11rem)` carrying its own `p-4 lg:p-5`, which is the old
 * `13.5rem` budget restated with the padding inside the clip (the director's
 * frame must BE the clipping box). The fold budget the hero's docblock
 * derives is therefore untouched: the board is on screen before anyone
 * scrolls at 1024×600. Below `lg` the act collapses to the still with the
 * receipt card in flow beneath it, exactly as before.
 */
const OnerStage = dynamic(() => import("./OnerStage").then((m) => m.OnerStage), {
  ssr: false,
  loading: () => (
    <div className="h-full p-4 lg:p-5">
      <StageSkeleton />
    </div>
  ),
});

export function WindowAct() {
  const wide = useWideViewport();
  const frameRef = useRef<HTMLDivElement>(null);

  /** `null` until the media query is read — treated as "not yet armed", so
   *  the server render and the first client paint agree. */
  const [reduced, setReduced] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const armed = wide && reduced === false;

  /** The pinned runway, grown once the take is armed and never collapsed —
   *  the height is what the pin is defined against (ClosingAct's rule). */
  const [runway, setRunway] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const raf = requestAnimationFrame(() => setRunway(true));
    return () => cancelAnimationFrame(raf);
  }, [armed]);

  const [caption, setCaption] = useState<string>(ACT.opening);
  const [phase, setPhase] = useState<OnerPhase>("idle");
  const [userPaused, setUserPaused] = useState(false);
  /** Remount key: a replay restarts the take from the product's own initial
   *  state (fresh board fixture), never from a rewound recording. */
  const [runId, setRunId] = useState(0);

  const onCaption = useCallback((line: string) => setCaption(line), []);
  const onPhase = useCallback((next: OnerPhase) => setPhase(next), []);

  const replay = () => {
    setUserPaused(false);
    setCaption(ACT.opening);
    setPhase("idle");
    setRunId((n) => n + 1);
  };

  const playing = phase === "playing" && !userPaused;
  const strip = reduced ? ACT.resting : caption;

  return (
    <section aria-label="The board, live" className={cn("relative", runway && "lg:h-[260vh]")}>
      {/* ---- the window, pinned through the act -------------------------- */}
      <div className="lg:sticky lg:top-[4.5rem]">
        {/* The act's narration: one pinned line above the frame, swapped as
            the director reaches each beat. Fixed height, so the frame below
            never moves; polite, so a screen reader hears the story at its
            own pace rather than mid-word. */}
        {/* On the landing's 85rem gutter (`app/page.tsx`), like every other
            surface of the page: the frame IS the page's widest exhibit, and
            it was the one box already argued full-width. At 1024 nothing
            moves; the stage's height budget is untouched either way. */}
        <div className="mx-auto w-full max-w-[85rem] px-4 pb-1.5 sm:px-6">
          <p aria-live="polite" className="min-h-6 truncate text-[0.9375rem] leading-6 text-muted">
            {strip}
          </p>
        </div>
        <div className="mx-auto w-full max-w-[85rem] px-4 sm:px-6">
          <div className="overflow-clip rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-2 sm:px-5">
              <span className="label-caps flex min-w-0 items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-live" aria-hidden />
                <span className="truncate">{armed ? BOARD.take : BOARD.live}</span>
              </span>
              <span className="flex shrink-0 items-center gap-x-4">
                {/* The transport a long autoplaying take owes its viewer —
                    the clip frames' grammar (label-caps text, py for the
                    target), in the strip the act already carries. */}
                {armed && (
                  <>
                    {phase === "playing" && (
                      <button
                        type="button"
                        onClick={() => setUserPaused((v) => !v)}
                        className="label-caps py-1.5 transition-colors hover:text-strong"
                      >
                        {playing ? ACT.pause : ACT.play}
                      </button>
                    )}
                    {phase !== "idle" && (
                      <button
                        type="button"
                        onClick={replay}
                        className="label-caps py-1.5 transition-colors hover:text-strong"
                      >
                        {ACT.replay}
                      </button>
                    )}
                  </>
                )}
                <a
                  href="/demo"
                  {...NEW_TAB}
                  className="label-caps text-muted transition-colors hover:text-strong"
                >
                  {BOARD.open} →
                </a>
              </span>
            </div>
            {/* ---- the stage (`lg`+): the director's frame ----------------

                `bg-surface`, NOT `bg-background`, and it is the other half of
                #392. The stage used to reset the shell's surface back to the
                page's own paint, so the moment a filter shrank the board
                (the stage lens, or the take's own day-bar beat) the unused
                canvas below the rows was pixel-identical to the page behind
                the window — measured at 1512×949, the assessment lens left
                54.2% of the frame reading as bare page, i.e. as a hole, not
                as an empty board. A real app viewport paints its own ground
                to its own edge whatever its content weighs; one ladder step
                up gives the window that ground, and makes the whole exhibit
                one continuous pane — chrome strip and stage on the same
                material — the way the shadow and border always claimed it
                was. The camera pans content OVER this ground (it sits on the
                clipping box, not the camera), which is how a viewport
                behaves under scroll; no geometry moves, so the pan gates and
                the fold budget are untouched.

                The dot grid is the half that actually carries. At rest on a
                1512×949 screen the frame's foot is below the page fold, so
                the ladder step has no visible edge to read against — and a
                one-step luminance difference on near-black is invisible
                without one. A surface has to be self-evidently a surface at
                any crop: the grid is that, set in the existing `--line`
                token (so both themes inherit it), 1px dots on a 24px pitch —
                the bench the board's plates sit on, quiet enough that a full
                board buries it in its gutters. On the frame, not the camera:
                one paint site covers the armed, disarmed and skeleton paths,
                and a viewport's canvas holds still while content glides. */}
            <div
              ref={frameRef}
              className="relative hidden overflow-clip bg-surface bg-[radial-gradient(var(--line)_1px,transparent_1px)] [background-size:24px_24px] lg:block"
              style={{ height: "calc(100dvh - 11rem)" }}
            >
              {wide ? (
                <OnerStage
                  key={runId}
                  frameRef={frameRef}
                  disarmed={reduced !== false}
                  paused={userPaused}
                  onCaption={onCaption}
                  onPhase={onPhase}
                />
              ) : (
                <div className="h-full p-4 lg:p-5">
                  <StageSkeleton />
                </div>
              )}
            </div>
            {/* ---- below `lg`: the still, in the same frame --------------- */}
            <div className="bg-background p-4 lg:hidden">
              <BoardStill />
            </div>
          </div>
        </div>
      </div>

      {/* ---- below `lg`: the receipt in flow under the still. The offer
              mail with the bridge line, because the exhibit the descent
              opens on below is the other mail (the invitation). ---------- */}
      <div className="mx-auto mt-5 w-full max-w-[85rem] px-4 sm:px-6 lg:hidden">
        <ChangedRow email={OFFER_EMAIL} foot="bridge" />
      </div>
    </section>
  );
}
