"use client";

import { useEffect, useState } from "react";

import { buildSubtitle } from "@/lib/dashboard/boardPrefs";
import { summaryUrlFor, summaryWeekCorrection } from "@/lib/dashboard/readerWeek";
import type { PipelineSummary } from "@/lib/dashboard/summary";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";

/**
 * The board's one line of state — `50 filed · +7 this wk · 32 open · 1 offer` —
 * counted in the READER's week rather than the server's (#518).
 *
 * The line itself is still `buildSubtitle`, unchanged and shared with the demo
 * twin. What this component adds is the one number in it that depends on whose
 * calendar day it is.
 *
 * THE SPLIT IT CLOSES. `this wk` arrives from `GET /applications/summary`,
 * counted server-side from a UTC Monday, while the momentum caption a few
 * hundred pixels below counts the reader's Monday (`PipelinePulse` →
 * `useLocalToday`), because the bars beside that caption bucket on the
 * reader's day. West of UTC that leaves a window each week the size of the
 * offset — Sunday 20:00 to midnight in Eastern — where the header had rolled
 * into the new week and the caption had not: the header read ~0 above a
 * picture showing a full week of filings.
 *
 * SERVER FIRST, THEN THE READER, and in that order for the reason
 * `useLocalToday` exists: the server has no zone to render, so the first paint
 * and the hydrating pass are the UTC answer the page was rendered with —
 * byte-identical, no text mismatch. Only afterwards, and only when the
 * reader's Monday actually differs from the Monday the endpoint says it
 * counted, does this ask again.
 *
 * SO IT COSTS NOTHING ALMOST ALWAYS. Outside that window the two Mondays are
 * the same string, `summaryWeekCorrection` returns null, no request is made
 * and this renders exactly what a Server Component would have.
 *
 * WHAT IT LOOKS LIKE WHEN IT DOES FIRE. `buildSubtitle` omits the whole
 * ` · +N this wk` segment when the count is zero, so inside the window the
 * correction does not change a digit — it makes a segment APPEAR, and the line
 * gets about thirteen characters longer one tick after hydration. That is the
 * true number arriving, not a flash of a wrong one (the UTC count was a real
 * count of a real week), but it is a width change: `SyncBar`'s row holds it on
 * one line at 1024 because the subtitle is `shrink-0` in a row whose middle
 * slot is the flexible one. Verified at 1024 rather than assumed.
 *
 * GATED ON THE `weekly` PREF, because that is what decides whether the segment
 * is rendered at all. Asking the backend for a number this line has already
 * been told not to print would be a network round trip nobody can see.
 */
export function BoardSubtitle({
  summary,
  weekly,
  servedWeekStart,
}: {
  /** The summary as the server rendered it — `thisWeek` counted from `servedWeekStart`. */
  summary: PipelineSummary;
  /** The "weekly digest" notification pref: does this line carry `+N this wk` at all? */
  weekly: boolean;
  /** The Monday the endpoint says it counted (`week_start` in its response). */
  servedWeekStart: string;
}) {
  const readerToday = useLocalToday();
  // `null` on the server, through hydration, and for every reader whose Monday
  // is the one already counted — which is the common case and costs a string
  // comparison.
  const wanted = weekly ? summaryWeekCorrection(readerToday, servedWeekStart) : null;
  const [corrected, setCorrected] = useState<{ weekStart: string; thisWeek: number } | null>(
    null,
  );

  useEffect(() => {
    if (wanted === null) return;
    const controller = new AbortController();

    // Every failure path keeps the number already on screen. A refused
    // parameter (the backend 422s a non-Monday or a week no reader can be in),
    // an unreachable backend, a signed-out session: none of them is a reason to
    // blank or guess a count the page has already rendered honestly.
    void (async () => {
      try {
        const res = await fetch(summaryUrlFor(wanted), {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const body: unknown = await res.json();
        if (typeof body !== "object" || body === null) return;
        const { this_week: count, week_start: countedFrom } = body as {
          this_week?: unknown;
          week_start?: unknown;
        };
        // The answer has to say it counted the week we asked about. Without
        // this the header would adopt a number from some other Monday the
        // moment anything in the path — a cache, a retry that crossed
        // midnight — answered a different question than the one asked.
        if (typeof count !== "number" || countedFrom !== wanted) return;
        setCorrected({ weekStart: wanted, thisWeek: count });
      } catch {
        /* aborted, offline, or unparsable — the served answer stands */
      }
    })();

    return () => controller.abort();
  }, [wanted]);

  const thisWeek =
    corrected !== null && corrected.weekStart === wanted ? corrected.thisWeek : summary.thisWeek;

  return (
    <>{buildSubtitle(thisWeek === summary.thisWeek ? summary : { ...summary, thisWeek }, weekly)}</>
  );
}
