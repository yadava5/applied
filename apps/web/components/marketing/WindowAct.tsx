"use client";

import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/landing/Reveal";
import { cn } from "@/lib/utils";
import { ChangedRow, ReceiptStrip } from "./ChangedRow";
import { OFFER_EMAIL } from "./verdictEmailData";
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
 *   1  the offer lands — the camera pans to the board's foot, the receipt
 *      (`ReceiptStrip`) docks to the frame's foot and ANNOUNCES the move,
 *      and only then does the row travel to `offered` by the board's own
 *      layout animation, at the act's slowed tempo (tempo.ts) — announce,
 *      then move, so there is something to watch and a reason to watch it;
 *   2  the mail behind it — the camera HOLDS at the foot as the detail pane
 *      docks open on the moved row (after the row has LANDED — see
 *      MarketingBoard), so the row and the mail that moved it share one
 *      frame: the composition the owner approved (worklist beside the open
 *      pane, trail, gate meter), plus the row it is about.
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
 * Solving for D0 ≈ 0.19vh, D1 ≈ 0.97vh and D2 ≈ 0.67vh gives H = 2.7 and
 * 24/36/40 — 30vh shorter than the 300vh/30-35-35 it replaces, with beat 0's
 * zone down from 90vh to 65vh and its dead air from 45vh to 19vh.
 *
 * The beat-1 choreography has since been retimed for legibility (tempo.ts:
 * pan, announce, breathe, then a 1.4s glide — ~3.9s end to end), which is
 * LONGER than D1's dwell buys a steady scroller. That is deliberate and
 * safe: beat 2 holds the same foot framing, so a reader who scrolls on mid-
 * glide watches the row land in the very frame the pane then opens in — and
 * the pane itself waits for the landing (MarketingBoard's `landedAtRef`),
 * whichever zone the reader is in when it completes.
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
        <div className="mx-auto w-full max-w-6xl px-4 pb-1.5 sm:px-6">
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
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line-soft px-4 py-2 sm:px-5">
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
                // Beats 1 and 2: the receipt docks over the frame's foot as a
                // strip of window chrome (see LandingBoard), and the camera's
                // `room` keeps the last row clear of it. It rides through
                // beat 2 because it covers no rows there and its "the email
                // that did it ↓" is the line that hands off to the descent —
                // and because mounting per-beat is what left the receipt
                // stranded mid-scroll between the composed frames.
                overlay={
                  beat >= 1 ? (
                    <Reveal>
                      <ReceiptStrip />
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

      {/* ---- below `lg`: the receipt in flow under the still. The ACT's
              receipt — the offer — with the bridge line, because the exhibit
              the descent opens on below is the other mail (the invitation),
              not this one. ------------------------------------------------ */}
      <div className="mx-auto mt-5 w-full max-w-6xl px-4 sm:px-6 lg:hidden">
        <ChangedRow email={OFFER_EMAIL} foot="bridge" />
      </div>
    </section>
  );
}
