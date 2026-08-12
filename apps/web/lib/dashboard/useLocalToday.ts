"use client";

import { useSyncExternalStore } from "react";

import { localTodayISO, todayISO } from "@/lib/dashboard/age";

/**
 * The dashboard's one clock read for anything that claims TIME LEFT — the
 * hydration gate that lets a card be honest about the reader's day without
 * reintroducing a text mismatch.
 *
 * The two constraints are genuinely in tension, which is why this is a hook and
 * not a function call:
 *
 *  - the server has no idea what zone the reader is in, so server-rendered HTML
 *    can only be written in UTC. Rendering a local day on the hydrating pass
 *    would make the browser's text disagree with the server's — React #418, the
 *    exact failure `dates.ts` was written to end;
 *  - but the UTC day is the wrong day for up to the width of the reader's UTC
 *    offset, every day. Inside that window a deadline due by the end of the
 *    reader's own today rendered `overdue 1d`, and east of UTC a deadline whose
 *    day had already passed still rendered `due today`.
 *
 * So: UTC for the server snapshot and the hydrating pass — byte-identical, no
 * mismatch — then the reader's real day, once there is a reader. Every surface
 * that buckets a deadline or an age takes its day from here, so the card tag,
 * the detail sheet and the pulse strip cannot disagree about what day it is.
 *
 * `useSyncExternalStore` rather than a mounted flag in `useEffect`: this is the
 * "server value, then client value" case the API exists for, it is already the
 * house idiom for it (`AppearanceSection` reads the theme the same way), and it
 * does the swap as part of hydration instead of as a cascading setState — which
 * the `react-hooks/set-state-in-effect` rule rejects, and which would have cost
 * a visible frame of the wrong claim ("overdue 1d" flashing before it settles
 * to "due today"). The snapshot is a plain string, so React's `Object.is`
 * comparison bails out whenever the two days agree — the common case, and every
 * case under `TZ=UTC`.
 *
 * `subscribe` is a no-op: nothing pushes a day change at us. The value still
 * self-corrects across the reader's own midnight, because any later render
 * re-reads the snapshot.
 */
function subscribe(): () => void {
  return () => {};
}

export function useLocalToday(): string {
  return useSyncExternalStore(subscribe, localTodayISO, todayISO);
}
