"use client";

import { useEffect, useState } from "react";

/**
 * The two primitives the scroll-bound landing shares.
 *
 * Both exist because the landing's motion is now a function of scroll
 * POSITION rather than of elapsed time (see tempo.ts): a position signal
 * needs somewhere to put its hysteresis, and a `lg`-only choreography needs
 * to know whether it is switched on at all.
 */

/** The width at which the framed window and the sticky exhibits exist. Below
 *  it the landing is a still (`LandingBoard`'s rule) and nothing is driven. */
const LG = "(min-width: 1024px)";

/**
 * Whether the viewport is wide enough for the choreography to mean anything.
 *
 * It is a MOUNT condition, not just a display one — a phone should never
 * download the dashboard bundle for a board it will not show — and it is
 * tracked live, so rotating a tablet switches the act on when it becomes
 * usable. It is also the gate on every scroll-derived state: `useScroll`
 * happily reports progress against a section that has no `lg:h-[400vh]`
 * below `lg`, and would otherwise drive a still with garbage.
 */
export function useWideViewport(): boolean {
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(LG);
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return wide;
}

/**
 * A latch with hysteresis: `on` a little past the mark, `off` a little before
 * it, so a state bound to scroll position cannot chatter at the boundary.
 *
 * `deadband` is the HALF-width, in the same units as `progress` and `mark`
 * (shares of a runway) — see `ACT_DEADBAND` for the sizing argument.
 */
export function latch(progress: number, mark: number, current: boolean, deadband: number): boolean {
  return current ? progress > mark - deadband : progress >= mark + deadband;
}
