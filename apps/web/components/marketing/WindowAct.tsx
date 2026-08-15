"use client";

import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/landing/Reveal";
import { cn } from "@/lib/utils";
import { ChangedRow } from "./ChangedRow";
import { LandingBoard } from "./LandingBoard";
import { NEW_TAB } from "./chrome";
import { ACT, BOARD } from "./copy";

/**
 * The merged landing's first act: B's specimen window, driven by C's scroll.
 *
 * The window — the framed, running app — pins below the nav while the page
 * scrolls through a tall runway, and the visitor's descent advances the scene
 * INSIDE it (the direction the owner set: the page scroll drives the board,
 * never a nested scroller — the `locked` variant's inner scroll region stays
 * banned on flowing pages). Three scenes, one idea each:
 *
 *   0  the board as the product left it — Larkspur still filed, 19 days
 *      quiet; the visitor can already drag rows and open cards;
 *   1  the verdict lands — the camera pans to the board's foot and the row
 *      travels to `closed` by the board's own layout animation; the receipt
 *      card (`ChangedRow`) floats in over the foot, pointing at the descent;
 *   2  the mail behind it — the camera returns to the head as the detail
 *      pane docks open on the moved row: the composition the owner approved
 *      (worklist beside the open pane, trail, gate meter).
 *
 * MECHANISM. IntersectionObserver over three sentinel zones against a centre
 * band — `ClaimsDescent`'s idiom exactly: the page scrolls normally and the
 * window only ever responds. The scene index follows the scroll in BOTH
 * directions (the camera may return); the mutations it triggers fire once
 * and persist (a verdict does not un-happen — see MarketingBoard). Under
 * reduced motion every scene still composes fully; only the travel between
 * them is cut rather than played.
 *
 * NARRATION. Every scene carries one pinned caption above the frame (`ACT`),
 * swapped as the beat changes. Scene 0 is the load-bearing one: it used to be
 * two thirds of a viewport of a resting board with nothing to read, and a
 * visitor who does not yet know the product's grammar cannot see what the
 * fixture is foreshadowing (Larkspur, nineteen days quiet, the amber age tag).
 * The caption is what makes that scene a scene — and scene 0 has a second
 * line for the way back up, because the camera returns and the verdict does
 * not (`ACT.settled`).
 *
 * GEOMETRY. The runway's height and the sticky window are `lg`-only: below
 * `lg` the board is `BoardStill` (LandingBoard's rule), so the act collapses
 * to B's static frame with the receipt card in flow beneath it. Everything
 * at `lg`+ is height-reserved — sticky + transform inside the stage's clip —
 * so the choreography cannot shift the page: CLS zero by construction.
 *
 * The runway and the sentinel shares below are DERIVED, not chosen. Writing
 * the runway as H (in viewport heights), the shares as h0/h1/h2, and the pin
 * offset as p = 4.5rem/vh, the observer's centre band puts the events at:
 *
 *   window pins        T = p                    (T = section top, in vh)
 *   beat 1 fires       T = 0.55 − h0·H
 *   beat 2 fires       T = 0.55 − (h0+h1)·H
 *   window unpins      T ≈ 0.96 − H             (the frame fills the viewport)
 *
 * so each scene's PINNED dwell is D0 = h0·H − (0.55 − p), D1 = h1·H, and
 * D2 = h2·H − 0.41. Two consequences drove the split:
 *
 *   · h0·H > 0.55 − p is a hard constraint, not a preference. Below it beat 1
 *     fires while the window is still travelling: the verdict lands on an
 *     unpinned board. p is smallest on the tallest viewport (72/900 ≈ 0.08),
 *     so the floor is h0·H > 0.47vh — 47% of a viewport of runway that buys
 *     no dwell at all. That is why beat 0 cannot be 18–20% of a runway short
 *     enough to be worth shortening; the gate holds the inequality directly.
 *   · D0 does not need to be long once the scene has words. The board is
 *     already on screen and captioned through ~0.9vh of approach before it
 *     pins, so 0.19vh of pinned stillness is a beat, not dead air.
 *
 * Solving for D0 ≈ 0.19vh, D1 ≈ 0.97vh (the beat-1 choreography is ~1.5s: a
 * 700ms pan, then the 750ms breath before the row travels) and D2 ≈ 0.67vh
 * gives H = 2.7 and 24/36/40 — 30vh shorter than the 300vh/30-35-35 it
 * replaces, with beat 0's zone down from 90vh to 65vh and its dead air from
 * 45vh to 19vh.
 */

/** The narration's lines, in the order the strip stacks them: one per scene,
 *  then scene 0's revisited line. `SETTLED` is derived from the scene count
 *  rather than written as `LINES.length - 1`, so adding a fourth scene cannot
 *  quietly point the revisit at the new scene's caption instead. */
const LINES = [...ACT.captions, ACT.settled];
const SETTLED = ACT.captions.length;

export function WindowAct() {
  const [beat, setBeat] = useState(0);
  // Whether the verdict has already landed. The scene index goes back down
  // when the reader scrolls up; the board's state does not, so scene 0's
  // opening line stops being true the moment beat 1 has fired once.
  const [settled, setSettled] = useState(false);
  const sentinelsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = sentinelsRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number((entry.target as HTMLElement).dataset.beat);
          if (!Number.isInteger(index)) continue;
          setBeat(index);
          if (index >= 1) setSettled(true);
        }
      },
      // The centre band: a scene owns the window while its zone crosses the
      // viewport's middle, whichever way the reader scrolls.
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );
    for (const el of root.querySelectorAll("[data-beat]")) io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section aria-label="The board, live" className="relative lg:h-[270vh]">
      {/* ---- the window, pinned through the act -------------------------- */}
      <div className="lg:sticky lg:top-[4.5rem]">
        {/* The act's narration. One line per scene, crossfaded in place: every
            line shares one grid cell, so the strip's height is fixed and the
            frame below it never moves. Below `lg` there are no scenes, so the
            strip rests on the first line and captions the still. */}
        <div className="mx-auto w-full max-w-6xl px-4 pb-2 sm:px-6">
          <div className="grid min-h-6 items-start">
            {LINES.map((line, index) => {
              const active = index === (beat === 0 && settled ? SETTLED : beat);
              return (
                <p
                  key={line}
                  aria-hidden={!active}
                  className={cn(
                    "col-start-1 row-start-1 text-[0.9375rem] leading-6 text-muted transition-opacity duration-500 motion-reduce:transition-none",
                    active ? "opacity-100" : "opacity-0",
                  )}
                >
                  {line}
                </p>
              );
            })}
          </div>
        </div>
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
          <div className="overflow-clip rounded-2xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgb(0_0_0/0.55)]">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-2.5 sm:px-5">
              <span className="label-caps flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
                {BOARD.live}
              </span>
              <a
                href="/demo"
                {...NEW_TAB}
                className="label-caps text-muted transition-colors hover:text-strong"
              >
                {BOARD.open} →
              </a>
            </div>
            <div className="bg-background p-4 lg:p-5">
              <LandingBoard
                // 13.5rem, not 11.5: nav + pin offset + frame chrome, plus the
                // 2rem the caption strip above now takes. The frame still
                // clears the shortest viewport this act is verified at (600px)
                // by the same ~29px it always did.
                height="calc(100dvh - 13.5rem)"
                caption={false}
                beat={beat}
                // Beat 1 only: that scene pans past the board's foot and
                // clears a strip for the card (see LandingBoard). At beat 2
                // the camera is back at the head — the strip is gone and the
                // open pane carries the story, so the receipt stands down
                // rather than sit on rows it would otherwise cover.
                overlay={
                  beat === 1 ? (
                    <Reveal>
                      <ChangedRow />
                    </Reveal>
                  ) : null
                }
              />
            </div>
          </div>
        </div>
      </div>

      {/* ---- the runway's sentinel zones (`lg` only — the still below `lg`
              has no scenes to reach). Inert to the pointer so every hit
              lands on the live board beneath them. ----------------------- */}
      <div
        ref={sentinelsRef}
        aria-hidden
        className="pointer-events-none absolute inset-0 hidden lg:block"
      >
        <div data-beat={0} className="h-[24%]" />
        <div data-beat={1} className="h-[36%]" />
        <div data-beat={2} className="h-[40%]" />
      </div>

      {/* ---- below `lg`: the receipt in flow under the still -------------- */}
      <div className="mx-auto mt-5 w-full max-w-6xl px-4 sm:px-6 lg:hidden">
        <ChangedRow />
      </div>
    </section>
  );
}
