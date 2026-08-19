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

/**
 * A number that changes without a render.
 *
 * The landing's scrubs write transforms and opacities on every scroll frame,
 * which is not a reason for React to re-render — and it is the only thing
 * `motion`'s `MotionValue` was doing here. Keeping the library for it cost the
 * page 47 KB compressed of first-load JS: `WindowAct`, `LandingBoard` and
 * `ClaimsDescent` all import from the landing's initial chunk, so a PHONE paid
 * for it too, and below `lg` the board is `BoardStill` and none of this
 * choreography ever runs. The board's own chunk still uses `motion` for the
 * product's shared-layout animations, where it earns its size.
 */
export interface Signal {
  get(): number;
  set(next: number): void;
  /** Fires immediately with the current value, then on every change. */
  subscribe(listener: (value: number) => void): () => void;
}

export function createSignal(initial = 0): Signal {
  let value = initial;
  const listeners = new Set<(value: number) => void>();
  return {
    get: () => value,
    set(next) {
      if (next === value) return;
      value = next;
      for (const listener of listeners) listener(next);
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(value);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/**
 * The window a target's scroll progress is measured over, as viewport shares:
 * progress is 0 when the target's TOP edge sits `from` of the way down the
 * viewport, and 1 when its BOTTOM edge sits `to` of the way down.
 *
 * The three the landing uses, and what each buys:
 *
 *   `{ from: 0, to: 1 }`      the act — the target's own traversal, which for
 *                             a tall pinned section is the pinned runway;
 *   `{ from: 0.5, to: 0.5 }`  the descent — a claim becomes "the claim" as it
 *                             crosses the viewport's middle, whichever way the
 *                             reader scrolls;
 *   `{ from: 1, to: 1 }`      the closing band — its entrance, from touching
 *                             the fold to fully in frame. That upper bound is
 *                             the one that is GUARANTEED reachable for a
 *                             section at the page's foot.
 */
export interface ProgressWindow {
  from: number;
  to: number;
}

/**
 * Report `el`'s progress through `window`, clamped to [0, 1], on every scroll
 * and resize — rAF-throttled, so one layout read per frame at most.
 *
 * The arithmetic is the one `useScroll` performs, verified against it to three
 * decimals before the dependency was dropped: with `rect = el.getBoundingClientRect()`
 * and `vh = innerHeight`, progress 0 is at `rect.top === from * vh` and
 * progress 1 at `rect.bottom === to * vh`, so
 *
 *     progress = (from * vh - rect.top) / (rect.height - to * vh + from * vh)
 *
 * The denominator is independent of scroll, which is why this needs no cached
 * document offsets and stays correct when the page above the target grows.
 *
 * The first read is scheduled rather than taken inline: a caller subscribing
 * from an effect must not set state synchronously (react-hooks/set-state-in-effect),
 * and a layout read during commit is the wrong time to take one anyway.
 */
export function trackProgress(
  el: HTMLElement,
  window_: ProgressWindow,
  onProgress: (progress: number) => void,
): () => void {
  let frame = 0;
  const read = () => {
    frame = 0;
    const viewport = window.innerHeight;
    const rect = el.getBoundingClientRect();
    const span = rect.height - window_.to * viewport + window_.from * viewport;
    if (span <= 0) {
      onProgress(0);
      return;
    }
    onProgress(Math.min(1, Math.max(0, (window_.from * viewport - rect.top) / span)));
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(read);
  };
  schedule();
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  return () => {
    if (frame) cancelAnimationFrame(frame);
    window.removeEventListener("scroll", schedule);
    window.removeEventListener("resize", schedule);
  };
}
