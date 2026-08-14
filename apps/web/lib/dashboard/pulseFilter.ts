/**
 * The pulse's worklist filters — the vocabulary that turns the band's four
 * derived panels (#156/#158/#159, and the deadline panel the owner asked for
 * on 2026-08-13) into a work surface instead of a poster. Clicking a day, an
 * age bin, a provenance group or a runway bin in the pulse detail panel
 * produces one of these; `PipelineBoard` holds it as state and narrows the
 * worklist with {@link matchesPulseFilter}, exactly the way the company
 * filter already narrows it.
 *
 * Pure and presentation-free on purpose, and the predicate reads the SAME
 * derivations the charts draw from (`filedAt`, `daysBetween`, `isOpenStage`,
 * `QUIET_AFTER_DAYS`, `dueInfo`) — so the rows a click reveals can never
 * disagree with the bar that was clicked. Relative `.ts` imports, same as
 * `summary.ts`, so `node --test` can load it under type stripping.
 */
import { QUIET_AFTER_DAYS, daysBetween } from "./age.ts";
import { filedAt, shortDate } from "./dates.ts";
import { DUE_SOON_WORDS, dueInfo, duePhrase, type DueState } from "./deadline.ts";
import { isOpenStage, type PulseRow } from "./summary.ts";

export type PulseFilter =
  /** Rows filed on one calendar day; `openOnly` when an AGE bin was clicked —
   *  the ageing chart counts open rows only, and the rows a click reveals
   *  must be the rows the bar counted. */
  | { kind: "day"; date: string; openOnly?: boolean }
  /** The amber share: open rows ≥ {@link QUIET_AFTER_DAYS} days old. */
  | { kind: "quiet" }
  /** Provenance: rows that arrived from Gmail, or were typed in by hand. */
  | { kind: "source"; source: "mail" | "hand" }
  /** A deadline bucket, named by the state the card tags already ink. */
  | { kind: "due"; state: DueState }
  /** Rows due exactly this many days out — negative is overdue by that much.
   *  Days-left, not a date, because days-left is what the runway BINS on: a
   *  date-shaped filter would have to redo the calendar-day maths and could
   *  land a day off the bar the reader clicked. */
  | { kind: "dueIn"; days: number };

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
    case "due": {
      const due = dueInfo(app.due_at, today);
      return due !== null && due.state === filter.state;
    }
    case "dueIn": {
      const due = dueInfo(app.due_at, today);
      return due !== null && due.daysLeft === filter.days;
    }
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
    case "due":
      // The bucket's own words, the same ones the caption uses — a filter band
      // reading "due within 2 days" and a caption reading "due ≤2d" would be
      // two names for one set.
      return filter.state === "overdue"
        ? "overdue"
        : filter.state === "soon"
          ? `due within ${DUE_SOON_WORDS}`
          : `due after ${DUE_SOON_WORDS}`;
    case "dueIn":
      // `duePhrase` is the phrase every deadline surface already speaks in
      // ("due today", "due in 2d", "overdue 3d"), so the band quotes the card.
      return duePhrase(filter.days);
  }
}
