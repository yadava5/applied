"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { BoardStill } from "./BoardStill";
import { NEW_TAB } from "./chrome";
import { BOARD } from "./copy";

/**
 * The landing's board embed: the REAL product, mounted the only safe way.
 *
 * Three constraints shaped this component, all verified rather than assumed:
 *
 *  1. TRANSPORT. `PipelineBoard`'s `transport` prop DEFAULTS to the live
 *     transport, which PATCHes /api/applications/* — on localhost, against a
 *     signed-in owner's real production data. So this embed never mounts the
 *     board directly: it mounts `DemoDashboard`, the /demo twin whose
 *     in-memory transports are the whole point of its existence, and
 *     `tests/unit/landing-variants.test.mjs` asserts no other path exists
 *     from the landing pages to the board.
 *
 *  2. DATES. The demo fixtures are dated RELATIVE to today; prerendering them
 *     bakes the build day in and React #418 fires from three days after
 *     build (measured — see app/demo/page.tsx). /demo pays for that with
 *     `force-dynamic`; a marketing page must not (700–1150 ms origin TTFB).
 *     So the board is mounted CLIENT-SIDE only, on approach
 *     (IntersectionObserver, 600px early) and only at `lg`+ — the server
 *     renders a skeleton into reserved geometry instead.
 *
 *  3. GEOMETRY. The stage has a fixed height and `overflow-clip`, so mounting
 *     the board moves nothing: CLS stays zero by construction, and there is
 *     no nested scroller — the crop is visual, with the fade below saying
 *     "this continues". `clip`, not `hidden`: `hidden` would make the stage a
 *     scroll container and break the flow board's sticky spine.
 *
 * Below `lg` the embed is `BoardStill` — a designed capture, not a broken
 * layout. The live board keeps rendering (CSS-hidden) once mounted so a
 * resize never resets a visitor's drags.
 */
const DemoDashboard = dynamic(
  () => import("@/components/demo/DemoDashboard").then((m) => m.DemoDashboard),
  { ssr: false },
);

const LG = "(min-width: 1024px)";

export function LandingBoard({
  height = "min(72vh, 680px)",
  className,
  caption = true,
}: {
  /** The stage's fixed height — the reservation that keeps CLS at zero. */
  height?: string;
  className?: string;
  /** Off when the caller's frame carries the provenance line itself (B). */
  caption?: boolean;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  const [wide, setWide] = useState(false);

  // `lg`+ is a mount condition, not just a display one: a phone should never
  // download the dashboard bundle for a board it will not show. Tracked live
  // so rotating a tablet mounts the board when it becomes usable.
  useEffect(() => {
    const mq = window.matchMedia(LG);
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      const id = setTimeout(() => setNear(true), 0);
      return () => clearTimeout(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          io.disconnect();
        }
      },
      // Mount well before arrival so the product is running by the time the
      // visitor's eyes get there — the hero embeds are in view at load.
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const live = near && wide;

  return (
    <div className={className}>
      {/* ---- the stage (`lg`+) ------------------------------------------- */}
      <div ref={stageRef} className="relative hidden lg:block" style={{ height }}>
        <div className="absolute inset-0 overflow-clip">
          {live ? <DemoDashboard variant="flow" /> : <StageSkeleton />}
        </div>
        {/* The crop edge: the board continues below this line, and the fade
            says so. Decoration only — it must never intercept the board. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-background"
        />
      </div>
      <div
        className={cn(
          "mt-3 hidden flex-wrap items-center justify-between gap-2",
          caption && "lg:flex",
        )}
      >
        <span className="inline-flex items-center gap-2 text-xs text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          {BOARD.live}
        </span>
        <a
          href="/demo"
          {...NEW_TAB}
          className="text-xs text-muted underline-offset-4 hover:text-strong hover:underline"
        >
          {BOARD.open} →
        </a>
      </div>

      {/* ---- the still (below `lg`) -------------------------------------- */}
      <div className="lg:hidden">
        <BoardStill />
      </div>
    </div>
  );
}

/**
 * What the server renders into the reservation: the board's silhouette.
 * Pulses only for visitors who have not asked motion to stop.
 */
function StageSkeleton() {
  return (
    <div aria-hidden className="flex h-full flex-col gap-4 motion-safe:animate-pulse">
      <div className="flex items-center justify-between gap-4">
        <div className="h-9 w-56 rounded-lg bg-surface-2" />
        <div className="h-9 w-40 rounded-lg bg-surface-2" />
      </div>
      <div className="flex min-h-0 flex-1 gap-5">
        <div className="hidden w-56 shrink-0 rounded-xl bg-surface lg:block" />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-20 rounded-xl border border-line-soft bg-surface" />
          ))}
        </div>
      </div>
    </div>
  );
}
