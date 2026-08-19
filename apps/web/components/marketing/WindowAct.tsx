"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useMotionValueEvent, useReducedMotion, useScroll, useTransform } from "motion/react";

import { cn } from "@/lib/utils";
import { ChangedRow, ReceiptStrip } from "./ChangedRow";
import { OFFER_EMAIL } from "./verdictEmailData";
import { LandingBoard } from "./LandingBoard";
import { NEW_TAB } from "./chrome";
import { latch, useWideViewport } from "./scrub";
import { ACT_DEADBAND, ACT_MARKS } from "./tempo";
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
 *      (`ReceiptStrip`) rises into the frame's foot and ANNOUNCES the move,
 *      and only then does the row travel to `offered` by the board's own
 *      layout animation, at the act's slowed tempo (tempo.ts) — announce,
 *      then move, so there is something to watch and a reason to watch it;
 *   2  the mail behind it — the camera HOLDS at the foot as the detail pane
 *      docks open on the moved row (after the row has LANDED — see
 *      MarketingBoard), so the row and the mail that moved it share one
 *      frame: the composition the owner approved (worklist beside the open
 *      pane, trail, gate meter), plus the row it is about.
 *
 * MECHANISM — and this is the part that was rebuilt. The act used to be an
 * IntersectionObserver sentinel firing a ~3s timeline that then ran on its
 * own clock, which is why it could finish while the reader was still
 * arriving, or still be running once they had gone. There is ONE signal now:
 * `scrollYProgress` across the runway. The camera's pan and the receipt's
 * rise are interpolated straight off it — scrubbed, so they move exactly as
 * far as the reader scrolls — and the two state changes are latched at a
 * mark and UNLATCHED on the way back up. Every piece of what the visitor
 * sees is a function of where they are:
 *
 *   · stopping halfway holds the act halfway;
 *   · scrolling back up un-does the verdict and closes the pane, so the move
 *     can be replayed by anyone who missed it;
 *   · nothing can complete off-screen, because there is no clock to complete
 *     against.
 *
 * The one thing that is still a duration is the row's glide between stage
 * groups: that is `PipelineBoard`'s own shared-layout animation between two
 * positions this layer never measures, and scrubbing it would mean a manual
 * FLIP against a component the landing does not own, through a camera
 * transform that corrupts the rect delta. It is a 1.4s event that now fires
 * AT a scroll position rather than 1.8s after a sentinel — so the reader is
 * looking at the frame when it happens, which is what "it can hardly be seen"
 * was actually about.
 *
 * NARRATION. Every scene carries one pinned caption above the frame (`ACT`),
 * swapped as the scene changes. Scene 0 is the load-bearing one: it used to
 * be two thirds of a viewport of a resting board with nothing to read, and a
 * visitor who does not yet know the product's grammar cannot see what the
 * fixture is foreshadowing (Larkspur, nineteen days quiet, the amber age
 * tag). The caption is what makes that scene a scene. It no longer needs a
 * second line for the way back up: the board's state reverses with the
 * scroll now, so scene 0 revisited IS scene 0, and the caption that narrated
 * a permanently settled board described a latch that no longer exists.
 *
 * GEOMETRY. The runway's height and the sticky window are `lg`-only: below
 * `lg` the board is `BoardStill` (LandingBoard's rule), so the act collapses
 * to B's static frame with the receipt card in flow beneath it — and the
 * scroll binding is gated on the same signal (`useWideViewport`), because
 * `useScroll` would otherwise report progress against a section that has no
 * runway at all. Everything at `lg`+ is height-reserved — sticky + transform
 * inside the stage's clip — so the choreography cannot shift the page: CLS
 * zero by construction.
 *
 * WHY THE PROGRESS MAPPING IS EXACT. Writing the runway as H (viewport
 * heights), the viewport as `vh` and the pin offset as p = 4.5rem, the sticky
 * child measures `vh − 105` (caption strip + frame chrome + the stage's
 * `calc(100dvh − 13.5rem)` + padding), so:
 *
 *   pin engages   at  −p            relative to `start start`
 *   pin releases  at  H·vh − vh + 33 relative to `start start`
 *   `end end`     at  H·vh − vh
 *
 * The scrubbed window [0, 1] therefore sits strictly inside the pinned
 * window — 72px in at the head, 33px short at the foot — at EVERY viewport
 * height, because the residue is a difference of constants, not of ratios.
 * The marks themselves and the runway arithmetic live in tempo.ts.
 *
 * REDUCED MOTION. State still follows the scroll, so every position composes
 * fully; what stands down is the interpolation. The camera and the receipt
 * step at their marks instead of scrubbing, and `PipelineBoard` neutralises
 * the row's glide itself.
 */

export function WindowAct() {
  const runwayRef = useRef<HTMLElement>(null);
  const wide = useWideViewport();
  const reduce = useReducedMotion() === true;

  // ONE signal. `start start` → `end end` is the section's own traversal,
  // which the block comment above shows lands inside the pinned window at
  // every viewport height.
  const { scrollYProgress } = useScroll({
    target: runwayRef,
    offset: ["start start", "end end"],
  });

  /** The camera, 0 (board's head) → 1 (board's foot), and the receipt's rise,
   *  0 (below the frame) → 1 (docked). A degenerate input range under reduced
   *  motion turns each scrub into a step at its own mark. */
  const camera = useTransform(
    scrollYProgress,
    reduce ? [ACT_MARKS.pan[1], ACT_MARKS.pan[1] + 0.001] : [...ACT_MARKS.pan],
    [0, 1],
    { clamp: true },
  );
  const receipt = useTransform(
    scrollYProgress,
    reduce ? [ACT_MARKS.receipt[1], ACT_MARKS.receipt[1] + 0.001] : [...ACT_MARKS.receipt],
    [0, 1],
    { clamp: true },
  );
  // The announcement's own entrance, decoupled from anything it announces: it
  // is legible for the last three quarters of its rise rather than reaching
  // full opacity only once it has stopped.
  const receiptOpacity = useTransform(receipt, [0, 0.25], [0, 1], { clamp: true });
  const receiptY = useTransform(receipt, [0, 1], [18, 0]);

  // --- the latched state: which caption, and what the board is doing -------
  //
  // All three reverse. `scene` is the narration's index; `verdict` and
  // `docked` are the board's, handed to `MarketingBoard` as plain booleans so
  // the whole act is a pure function of position (see its own doc comment for
  // what stays one-way, and why).
  const [scene, setScene] = useState(0);
  const [verdict, setVerdict] = useState(false);
  const [docked, setDocked] = useState(false);

  const readProgress = useCallback((progress: number) => {
    setScene((prev) =>
      latch(progress, ACT_MARKS.docked, prev >= 2, ACT_DEADBAND)
        ? 2
        : latch(progress, ACT_MARKS.scene, prev >= 1, ACT_DEADBAND)
          ? 1
          : 0,
    );
    setVerdict((prev) => latch(progress, ACT_MARKS.verdict, prev, ACT_DEADBAND));
    setDocked((prev) => latch(progress, ACT_MARKS.docked, prev, ACT_DEADBAND));
  }, []);

  useMotionValueEvent(scrollYProgress, "change", (progress) => {
    if (wide) readProgress(progress);
  });

  // The mount read, and the narrowing read. `useMotionValueEvent` only fires
  // on CHANGE, so a reader who reloads mid-runway — or who was below `lg` and
  // widened the window — would otherwise sit on scene 0 over a board the
  // scroll position says is three scenes in. Deferred a frame so the effect
  // body never sets state synchronously (react-hooks/set-state-in-effect).
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      readProgress(wide ? scrollYProgress.get() : 0);
    });
    return () => cancelAnimationFrame(raf);
  }, [wide, readProgress, scrollYProgress]);

  return (
    <section ref={runwayRef} aria-label="The board, live" className="relative lg:h-[400vh]">
      {/* ---- the window, pinned through the act -------------------------- */}
      <div className="lg:sticky lg:top-[4.5rem]">
        {/* The act's narration. One line per scene, crossfaded in place: every
            line shares one grid cell, so the strip's height is fixed and the
            frame below it never moves. Below `lg` there are no scenes, so the
            strip rests on the first line and captions the still. */}
        <div className="mx-auto w-full max-w-6xl px-4 pb-1.5 sm:px-6">
          <div className="grid min-h-6 items-start">
            {ACT.captions.map((line, index) => (
              <p
                key={line}
                aria-hidden={index !== scene}
                className={cn(
                  "col-start-1 row-start-1 text-[0.9375rem] leading-6 text-muted transition-opacity duration-500 motion-reduce:transition-none",
                  index === scene ? "opacity-100" : "opacity-0",
                )}
              >
                {line}
              </p>
            ))}
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
                camera={camera}
                verdict={verdict}
                docked={docked}
                // The receipt docks over the frame's foot as a strip of window
                // chrome (see LandingBoard), and the camera's `room` keeps the
                // last row clear of it. It rises with the reader's own scroll
                // rather than on a reveal timer, and it is mounted for the
                // whole act — mounting it per scene is what left it stranded
                // mid-scroll between the composed frames — so its own opacity
                // is what says whether it has arrived.
                //
                // This is only the ARRIVAL. Standing the bar down when the
                // visitor takes the frame back is LandingBoard's `released`,
                // which multiplies this opacity — the same fold the camera and
                // the crop fades use, and the reason it is not a branch here.
                overlay={
                  <motion.div style={{ opacity: receiptOpacity, y: receiptY }}>
                    <ReceiptStrip />
                  </motion.div>
                }
              />
            </div>
          </div>
        </div>
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
