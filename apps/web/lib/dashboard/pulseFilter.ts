/**
 * The pulse's worklist filters — the vocabulary that turns the band's three
 * derived charts (#156/#158/#159) into a work surface instead of a poster.
 * Clicking a day, an age bin or a provenance group in the pulse detail panel
 * produces one of these; `PipelineBoard` holds it as state and narrows the
 * worklist with {@link matchesPulseFilter}, exactly the way the company
 * filter already narrows it.
 *
 * Pure and presentation-free on purpose, and the predicate reads the SAME
 * derivations the charts draw from (`filedAt`, `daysBetween`, `isOpenStage`,
 * `QUIET_AFTER_DAYS`) — so the rows a click reveals can never disagree with
 * the bar that was clicked. Relative `.ts` imports, same as `summary.ts`, so
 * `node --test` can load it under type stripping.
 */
import { QUIET_AFTER_DAYS, daysBetween } from "./age.ts";
import { filedAt, shortDate } from "./dates.ts";
import { isOpenStage, type PulseRow } from "./summary.ts";

export type PulseFilter =
  /** Rows filed on one calendar day; `openOnly` when an AGE bin was clicked —
   *  the ageing chart counts open rows only, and the rows a click reveals
   *  must be the rows the bar counted. */
  | { kind: "day"; date: string; openOnly?: boolean }
  /** The amber share: open rows ≥ {@link QUIET_AFTER_DAYS} days old. */
  | { kind: "quiet" }
  /** Provenance: rows that arrived from Gmail, or were typed in by hand. */
  | { kind: "source"; source: "mail" | "hand" };

/** Does this row belong to the filtered view? `today` is the same clock read
 *  the board renders with (`useLocalToday`), so age math matches the cards. */
export function matchesPulseFilter(app: PulseRow, filter: PulseFilter, today: string): boolean {
  switch (filter.kind) {
    case "day": {
      if (filter.openOnly && !isOpenStage(app.status)) return false;
      return daysBetween(filedAt(app), filter.date) === 0;
    }
    case "quiet": {
      if (!isOpenStage(app.status)) return false;
      const age = daysBetween(filedAt(app), today);
      return age !== null && age >= QUIET_AFTER_DAYS;
    }
    case "source":
      return filter.source === "mail" ? app.source === "gmail" : app.source !== "gmail";
  }
}

/**
 * The filter, said in the board's own words — the text the filter band shows
 * and the clear control's accessible name quotes ("Stop filtering by …").
 */
export function pulseFilterLabel(filter: PulseFilter): string {
  switch (filter.kind) {
    case "day":
      return filter.openOnly ? `open, filed ${shortDate(filter.date)}` : `filed ${shortDate(filter.date)}`;
    case "quiet":
      return "quiet — open 2 wk+";
    case "source":
      return filter.source === "mail" ? "from your mail" : "filed by hand";
  }
}
