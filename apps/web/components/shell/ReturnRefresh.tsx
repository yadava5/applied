"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { AWAY_REFRESH_THRESHOLD_MS, shouldRefreshOnReturn } from "@/lib/shell/awayRefresh";

/**
 * The event half of "refresh when the reader comes back". Renders nothing.
 *
 * WHY IT EXISTS. `experimental.staleTimes.dynamic` is 300 s, so in-app rail
 * navigation inside a working session serves the payload the tab already has
 * instead of re-paying the ~1.1 s of origin time (`next.config.ts` carries
 * the measurements and the trade). The bound that makes a five-minute window
 * safe is this: data that changed server-side while nobody was looking is
 * picked up the moment somebody looks again. Since #284 that is a real case
 * and not a hypothetical — the scheduled sync writes every 15 minutes with no
 * tab involved.
 *
 * MOUNTED ONCE, BY `AppShell`, ON PURPOSE. `AppShell` is the SIGNED-IN
 * wrapper, and there is exactly one mount of it: `app/(app)/layout.tsx`, on the
 * branch where a user exists — which now covers the authenticated `/import` and
 * `/privacy` too, since those routes stopped mounting shells of their own.
 * `/demo/shell` mounts `AppShellFrame` instead, one
 * level down, so the fixture twin cannot reach this listener at all. That is
 * structural, not a pathname check: there is no server behind the demo to
 * refresh from, and a `pathname.startsWith("/demo")` guard would be one
 * refactor away from being wrong. Per-route or per-component mounts would
 * also multiply the handler, and `router.refresh()` is global.
 *
 * WHY `blur`/`focus` AND NOT JUST `visibilitychange`. Switching applications
 * (Cmd-Tab to Slack) usually leaves the tab `visible` — `document.hidden`
 * only flips when the tab is backgrounded or the window minimised. The
 * away-for-ten-minutes case this rule is FOR is mostly the former, so the
 * clock starts on whichever of the two fires first and stops on whichever
 * comes back first.
 *
 * WHY `awayAt` IS CLEARED BEFORE THE DECISION IS ACTED ON. Returning to a
 * backgrounded tab fires `visibilitychange` AND `focus`. Reading and clearing
 * the ref in one step means the second arrival sees `null` — the never-left
 * state — and declines, so a return issues exactly one refresh rather than
 * two RSC requests that look like a bug.
 *
 * WHAT A REFRESH COSTS AND TOUCHES. One `router.refresh()`: it bumps Next's
 * global segment-cache version, so it invalidates EVERY route's entry, not
 * just the one on screen (this is why the threshold is 60 s and not, say,
 * 5 s), and it re-runs the `(app)` layout — the Supabase Auth round-trip plus
 * the rail's backend probe. That is the ~1.1 s, paid once on return instead
 * of once per navigation. It is event-driven by construction: there is no
 * interval here and there must not be one.
 */
export function ReturnRefresh() {
  const router = useRouter();
  /** When the tab left, or `null` if it is here and always has been. */
  const awayAt = useRef<number | null>(null);

  useEffect(() => {
    const leave = () => {
      // First departure wins: a blur followed by a hide is one absence, and
      // restamping it would forgive the time already spent away.
      if (awayAt.current === null) awayAt.current = Date.now();
    };

    const arrive = () => {
      const left = awayAt.current;
      awayAt.current = null;
      if (shouldRefreshOnReturn(left, Date.now(), AWAY_REFRESH_THRESHOLD_MS)) {
        router.refresh();
      }
    };

    const onVisibility = () => {
      if (document.hidden) leave();
      else arrive();
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", leave);
    window.addEventListener("focus", arrive);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", leave);
      window.removeEventListener("focus", arrive);
    };
  }, [router]);

  return null;
}
