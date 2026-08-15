"use client";

import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/landing/Reveal";
import { ChangedRow } from "./ChangedRow";
import { LandingBoard } from "./LandingBoard";
import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";

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
 * GEOMETRY. The runway's height and the sticky window are `lg`-only: below
 * `lg` the board is `BoardStill` (LandingBoard's rule), so the act collapses
 * to B's static frame with the receipt card in flow beneath it. Everything
 * at `lg`+ is height-reserved — sticky + transform inside the stage's clip —
 * so the choreography cannot shift the page: CLS zero by construction.
 */
export function WindowAct() {
  const [beat, setBeat] = useState(0);
  const sentinelsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = sentinelsRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number((entry.target as HTMLElement).dataset.beat);
          if (Number.isInteger(index)) setBeat(index);
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
    <section aria-label="The board, live" className="relative lg:h-[300vh]">
      {/* ---- the window, pinned through the act -------------------------- */}
      <div className="lg:sticky lg:top-[4.5rem]">
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
                height="calc(100dvh - 11.5rem)"
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
        <div data-beat={0} className="h-[30%]" />
        <div data-beat={1} className="h-[35%]" />
        <div data-beat={2} className="h-[35%]" />
      </div>

      {/* ---- below `lg`: the receipt in flow under the still -------------- */}
      <div className="mx-auto mt-5 w-full max-w-6xl px-4 sm:px-6 lg:hidden">
        <ChangedRow />
      </div>
    </section>
  );
}
