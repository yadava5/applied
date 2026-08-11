/**
 * Pure deadline math + copy for `due_at` — the assessment/take-home due dates
 * the backend carries on every application (`null` = no deadline known).
 *
 * Same discipline as `age.ts`: everything is a function of calendar-day
 * strings, never a locally-constructed `Date`, so the server and the browser
 * cannot disagree about how far away a deadline is (the hydration bug class
 * `dates.ts` documents). Kept import-free (`CALENDAR_PREFIX` and the day math
 * are duplicated from `age.ts` on purpose) so `node --test` can load it under
 * type stripping, same as `board.ts` and `rowActions.ts`.
 *
 * Honesty rules, shared by the card tag, the detail sheet and the pulse cell:
 *
 *  - a row without `due_at` produces NOTHING — no state, no placeholder, no
 *    inferred urgency. The absence of a date is itself the honest answer;
 *  - the granularity is the calendar day. `due_at` may carry a real instant,
 *    but every surface renders and buckets the day it STATES ("due today"
 *    until UTC midnight, overdue after) — the one reading that is identical
 *    on server and client in every timezone, and the same rule every other
 *    date on the board already follows;
 *  - the words are arithmetic, never inference: "due in 2d" is a subtraction,
 *    and no phrasing here claims more than the mail or the user stated.
 */

const DAY_MS = 24 * 60 * 60 * 1000;

/** Leading `YYYY-MM-DD` of an ISO date or timestamp; anything after it is ignored. */
const CALENDAR_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)/;

/**
 * Due within this many days (today included) = the amber "soon" state. Two
 * days because the product's founding failure is the 48-hour assessment
 * window ("its 48-hour deadline passes unseen" — the landing's own PROBLEM
 * line): inside that window the deadline is a today-or-tomorrow task, not a
 * calendar entry. The pulse cell's "due ≤2d" copy derives from this constant
 * so the two can never drift.
 */
export const DUE_SOON_DAYS = 2;

export type DueState = "overdue" | "soon" | "ahead";

export interface DueInfo {
  state: DueState;
  /** Whole calendar days until the due day; 0 = due today, negative = overdue. */
  daysLeft: number;
}

/** UTC-midnight epoch of a calendar-day prefix, or `null` if unparsable. */
function utcDay(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const match = CALENDAR_PREFIX.exec(value.trim());
  if (!match) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return Date.UTC(Number(match[1]), month - 1, day);
}

/**
 * The row's deadline state, or `null` when there is no usable deadline —
 * absent, malformed, whatever. `null` means render nothing, and every caller
 * honours that instead of substituting a guess.
 */
export function dueInfo(dueAt: string | null | undefined, today: string): DueInfo | null {
  const due = utcDay(dueAt);
  const now = utcDay(today);
  if (due === null || now === null) return null;
  const daysLeft = Math.round((due - now) / DAY_MS);
  const state: DueState = daysLeft < 0 ? "overdue" : daysLeft <= DUE_SOON_DAYS ? "soon" : "ahead";
  return { state, daysLeft };
}

/**
 * What the deadline control PUTs for a picked calendar day: the END of that
 * day, UTC. "Due Aug 15" means "by the end of Aug 15" — start-of-day would
 * read as overdue for the whole day it is due — and the calendar prefix
 * round-trips exactly, so the card renders back the day the user picked.
 * `null` for anything that is not a real calendar day.
 */
export function dueDayISO(day: string): string | null {
  const match = CALENDAR_PREFIX.exec(day.trim());
  if (!match) return null;
  const month = Number(match[2]);
  const dayOfMonth = Number(match[3]);
  if (month < 1 || month > 12 || dayOfMonth < 1 || dayOfMonth > 31) return null;
  return `${match[1]}-${match[2]}-${match[3]}T23:59:59Z`;
}

/**
 * The one phrase every surface uses for a deadline's distance: "overdue 3d",
 * "due today", "due in 2d". Arithmetic in the data voice — the calendar day
 * itself is rendered beside it by the caller (`shortDate`).
 */
export function duePhrase(daysLeft: number): string {
  if (daysLeft < 0) return `overdue ${-daysLeft}d`;
  if (daysLeft === 0) return "due today";
  return `due in ${daysLeft}d`;
}

/**
 * The provenance qualifier — two different claims, never interchangeable:
 * "from your mail" is an extraction from an explicit statement in a message,
 * "set by you" is the user's own word (and sync never overwrites it). `null`
 * for anything else, so no unknown source is ever dressed up as either.
 */
export function dueSourceLabel(source: string | null | undefined): string | null {
  if (source === "user") return "set by you";
  if (source === "mail") return "from your mail";
  return null;
}

// --- Copy (kept here so the component can never drift from what is tested) --

export const DEADLINE_ADD_LABEL = "Add a deadline";
export const DEADLINE_SAVE_LABEL = "Save deadline";
export const DEADLINE_CHANGE_LABEL = "Change";
export const DEADLINE_CLEAR_LABEL = "Clear";
/** Clearing is not a delete and must never read like one. */
export const DEADLINE_CLEAR_HINT = "removes the date only — nothing else about the row changes";
export const DEADLINE_SAVE_FAILED = "Couldn't save the deadline — nothing changed.";
export const DEADLINE_CLEAR_FAILED = "Couldn't clear the deadline — it is still set.";
export const DEADLINE_PICK_FIRST = "Pick a date first — the deadline is unchanged.";

// --- The pulse strip's derivation --------------------------------------------

export interface DeadlinePulse {
  overdue: number;
  /** Due within {@link DUE_SOON_DAYS} days, today included. */
  soon: number;
  /** Due further out than the soon window. */
  later: number;
  /** Rows carrying any usable deadline at all. */
  total: number;
  /** The single most urgent tracked row (smallest days-left), or `null`. */
  urgent: { company: string; daysLeft: number } | null;
}

/**
 * Bucket the loaded rows' deadlines for the pulse cell. Rows without a usable
 * `due_at` simply don't count — the cell describes tracked deadlines only and
 * says "nothing due" when there are none, never a guess. Structurally typed so
 * this module stays free of the generated API schema.
 */
export function deadlinePulse(
  rows: { company: string; due_at?: string | null }[],
  today: string,
): DeadlinePulse {
  const pulse: DeadlinePulse = { overdue: 0, soon: 0, later: 0, total: 0, urgent: null };
  for (const row of rows) {
    const due = dueInfo(row.due_at, today);
    if (due === null) continue;
    pulse.total += 1;
    if (due.state === "overdue") pulse.overdue += 1;
    else if (due.state === "soon") pulse.soon += 1;
    else pulse.later += 1;
    if (pulse.urgent === null || due.daysLeft < pulse.urgent.daysLeft) {
      pulse.urgent = { company: row.company, daysLeft: due.daysLeft };
    }
  }
  return pulse;
}
