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
 *    but every surface renders and buckets the day it STATES — the same rule
 *    every other date on the board already follows. Which day "today" IS is
 *    the caller's one decision, and it is not free: bucketing against the UTC
 *    day made a New York evening read `overdue 1d` on a deadline the reader
 *    still had hours of. So callers hand this the READER's day
 *    (`useLocalToday`), and `due today` therefore lasts until the reader's own
 *    midnight, not UTC's;
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
 *
 * That round-trip promise only actually held once the card started bucketing
 * against the reader's day. The date input hands back a LOCAL day, so a New
 * York user picking today at 21:00 got a row that read `overdue 1d` the instant
 * they saved it — the stored day was right, the day it was compared against was
 * not. The storage shape here is unchanged and is the correct half; see
 * `useLocalToday`.
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

// --- The pulse's derivation --------------------------------------------

/** One tracked deadline, as every pulse surface reads it. */
export interface DeadlineRow {
  company: string;
  /** Whole calendar days until the due day; 0 = due today, negative = overdue. */
  daysLeft: number;
}

export interface DeadlinePulse {
  overdue: number;
  /** Due within {@link DUE_SOON_DAYS} days, today included. */
  soon: number;
  /** Due further out than the soon window. */
  later: number;
  /** Rows carrying any usable deadline at all. */
  total: number;
  /**
   * Every tracked row, soonest first. The detail panel's runway and its named
   * list both derive from THIS array rather than re-walking the board, so a
   * panel can never count a row the caption above it did not.
   */
  rows: DeadlineRow[];
  /** The single most urgent tracked row (smallest days-left), or `null`. */
  urgent: DeadlineRow | null;
}

/**
 * Bucket the loaded rows' deadlines for the pulse cell. Rows without a usable
 * `due_at` simply don't count — the cell describes tracked deadlines only and
 * says "nothing due" when there are none, never a guess. Structurally typed so
 * this module stays free of the generated API schema.
 *
 * `urgent` is `rows[0]` and the sort is ascending and STABLE (V8's is), so ties
 * still resolve to the row the board listed first — the behaviour before the
 * list existed, kept deliberately rather than left to the sort.
 */
export function deadlinePulse(
  rows: { company: string; due_at?: string | null }[],
  today: string,
): DeadlinePulse {
  const tracked: DeadlineRow[] = [];
  const pulse: DeadlinePulse = {
    overdue: 0,
    soon: 0,
    later: 0,
    total: 0,
    rows: tracked,
    urgent: null,
  };
  for (const row of rows) {
    const due = dueInfo(row.due_at, today);
    if (due === null) continue;
    pulse.total += 1;
    if (due.state === "overdue") pulse.overdue += 1;
    else if (due.state === "soon") pulse.soon += 1;
    else pulse.later += 1;
    tracked.push({ company: row.company, daysLeft: due.daysLeft });
  }
  tracked.sort((a, b) => a.daysLeft - b.daysLeft);
  pulse.urgent = tracked[0] ?? null;
  return pulse;
}

/**
 * The runway — the detail panel's drawn element, and the only chart in the
 * pulse that looks FORWARD. One bin per position on the way to a deadline:
 * what is already late, then each day of the {@link DUE_SOON_DAYS} window by
 * itself, then everything beyond it.
 *
 * Why these bins and not a day-by-day axis: every bin here maps to exactly one
 * worklist filter, so the rows a click reveals are precisely the rows the bin
 * counted (`pulseFilter.ts` holds the other half of that contract). A 14-day
 * axis would have needed an overflow bin no filter could express honestly.
 */
export type DeadlineBin =
  | { kind: "overdue"; count: number }
  | { kind: "day"; days: number; count: number }
  | { kind: "later"; count: number };

export function deadlineRunway(rows: DeadlineRow[]): DeadlineBin[] {
  const days: DeadlineBin[] = [];
  for (let day = 0; day <= DUE_SOON_DAYS; day += 1) {
    days.push({ kind: "day", days: day, count: rows.filter((row) => row.daysLeft === day).length });
  }
  return [
    { kind: "overdue", count: rows.filter((row) => row.daysLeft < 0).length },
    ...days,
    { kind: "later", count: rows.filter((row) => row.daysLeft > DUE_SOON_DAYS).length },
  ];
}

/** A day count in words. Takes a `number`, not the literal type of the
 *  constant below, so the plural arm stays live code if the window is ever
 *  retuned to one day. */
function dayWords(days: number): string {
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** The soon window in words, derived from the constant so copy cannot drift. */
export const DUE_SOON_WORDS = dayWords(DUE_SOON_DAYS);

/** Which ink a claim wears: the states the card tags already ink, plus the
 *  calm ramp for a board with nothing urgent on it. */
export type DeadlineTone = "overdue" | "soon" | "calm" | "empty";

/** One claim of the caption: at most one figure, and the words that own it. */
export interface DeadlineClaim {
  /** Words BEFORE the figure ("all"), where the count is a share of the whole. */
  lead?: string;
  /** The figure, or `null` for a claim that legitimately counts nothing. */
  count: number | null;
  /** The words the figure is bound forward to — never a bare unit. */
  words: string;
  tone: DeadlineTone;
}

/**
 * The deadline cell's caption, in the band's caption grammar (Ayush, twice:
 * `6 <1 wk · 5 1–2 wk · 3 quiet` — "these text are still there, they are lot
 * confusing!" — and then, of this cell, "it has the same issue with text that
 * we fixed for other"). What shipped here was the same defect one cell over:
 * `2 overdue · 1 due ≤2d · 5 later` recited every bucket, put `1` against the
 * unit `≤2d` with nothing binding them, and ended on `5 later`, a count of the
 * rows there is by definition nothing to do about today.
 *
 * So: ONE claim, two at most, ordered by what the reader must act on —
 * overdue outranks the window, the window outranks everything ahead of it —
 * and each figure bound forward by the words that own it. The `later` bucket
 * never gets a claim of its own while something is overdue or due soon; it
 * speaks only on a board where nothing is urgent, and then as the bound they
 * all clear ("all 5 due after 2 days"), which is the shape the ageing caption
 * settled on ("all 14 under 2 wk").
 *
 * NO SHARE OF A TOTAL here, unlike ageing's `6 of 14 quiet`, and the
 * difference is real: ageing's denominator is every open application — a whole
 * the reader recognises — while this one would be "rows that happen to carry a
 * due date", an arbitrary subset whose size makes no claim better. `2 of 8
 * overdue` would read as a reassurance the data cannot support. The tracked
 * total is context, and context is what the panel is for.
 */
export function deadlineCaption(pulse: DeadlinePulse): DeadlineClaim[] {
  if (pulse.total === 0) {
    // The state most boards are in, most of the time — never a nag, never
    // counts drawn at zero, and it says where a deadline comes from.
    return [
      { count: null, words: "nothing due", tone: "empty" },
      { count: null, words: "set one in a card", tone: "empty" },
    ];
  }
  const claims: DeadlineClaim[] = [];
  if (pulse.overdue > 0) claims.push({ count: pulse.overdue, words: "overdue", tone: "overdue" });
  if (pulse.soon > 0) {
    claims.push({ count: pulse.soon, words: `due within ${DUE_SOON_WORDS}`, tone: "soon" });
  }
  if (claims.length > 0) return claims;
  // Nothing overdue, nothing inside the window: the honest single claim is the
  // bound every tracked deadline clears. "all" only where there is a plurality
  // to quantify — "all 1 due after 2 days" is not English.
  return [
    {
      lead: pulse.total > 1 ? "all" : undefined,
      count: pulse.total,
      words: `due after ${DUE_SOON_WORDS}`,
      tone: "calm",
    },
  ];
}

/** The caption as one string — what the cell reads out, and what the unit
 *  tests assert, so the words can never be tested apart from how they join. */
export function deadlineCaptionText(pulse: DeadlinePulse): string {
  return deadlineCaption(pulse)
    .map((claim) =>
      [claim.lead, claim.count === null ? null : String(claim.count), claim.words]
        .filter((part) => part !== null && part !== undefined)
        .join(" "),
    )
    .join(" · ");
}
