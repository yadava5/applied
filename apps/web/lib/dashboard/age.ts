/**
 * Pure age/momentum math for the dashboard's honest signals. Everything here
 * is a function of calendar-day strings — the same "read the characters, never
 * construct a local Date" rule as `dates.ts` (see its header for the timezone
 * bug that rule exists to prevent).
 *
 * There are TWO clock reads here, and the difference between them is load-
 * bearing rather than incidental:
 *
 *  - {@link todayISO} is the UTC day. It is identical on the server and in the
 *    browser, which is the only reason server-rendered HTML can be hydrated
 *    without a text mismatch (React #418 — `dates.ts` documents the incident).
 *    It is the SSR/first-paint read, not a claim about the reader's day.
 *  - {@link localTodayISO} is the day the READER is living in. It is the only
 *    honest answer to "how long until this deadline?", and it is necessarily
 *    zone-dependent, so it can only be adopted AFTER hydration — see
 *    `useLocalToday.ts`, which owns that swap.
 *
 * Bucketing a deadline against the UTC day told a New York user at 21:00 that
 * an assessment due by the end of their own Aug 11 was already `overdue 1d`;
 * a user in Tokyo saw a deadline whose local day had passed still read
 * `due today`. The affected window each day is the size of the UTC offset.
 *
 * Kept import-free (the `CALENDAR_PREFIX` regex is duplicated from `dates.ts`
 * on purpose) so `node --test` can load it under type stripping, same as
 * `board.ts`.
 */

const DAY_MS = 24 * 60 * 60 * 1000;

/** Leading `YYYY-MM-DD` of an ISO date or timestamp; anything after it is ignored. */
const CALENDAR_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)/;

/**
 * An applied-stage application this many days old with no stage change is
 * "quiet" — the amber signal on cards and in the pulse strip. One threshold,
 * used everywhere, so the card tag and the strip's count can never disagree.
 */
export const QUIET_AFTER_DAYS = 14;

/** How many week-buckets the momentum strip renders. */
export const MOMENTUM_WEEKS = 8;

/**
 * Today's calendar day, UTC — identical on server and client, and therefore
 * the read every server render and first client render must use. It is NOT the
 * reader's day: use {@link localTodayISO} (via `useLocalToday`) for anything
 * that claims how much time someone has left.
 */
export function todayISO(now: number = Date.now()): string {
  return new Date(now).toISOString().slice(0, 10);
}

/**
 * Today's calendar day in the RUNTIME's own zone — the day the person reading
 * the screen would call today, and the same day their `<input type="date">`
 * offers when they pick "today".
 *
 * Deliberately assembled from the LOCAL calendar accessors. `toISOString()` is
 * what produced the bug this function exists to fix: it renders the UTC
 * instant, so between local midnight and UTC midnight it names a day the reader
 * is not in yet (or has already left). Nothing here may reach for it.
 */
export function localTodayISO(now: number = Date.now()): string {
  const date = new Date(now);
  const year = String(date.getFullYear()).padStart(4, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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

/** Whole calendar days from `fromISO` to `toISO` (negative = future). */
export function daysBetween(
  fromISO: string | null | undefined,
  toISO: string,
): number | null {
  const from = utcDay(fromISO);
  const to = utcDay(toISO);
  if (from === null || to === null) return null;
  return Math.round((to - from) / DAY_MS);
}

/** The three age buckets the pulse strip draws for open applications. */
export interface AgeBuckets {
  /** under one week old */
  fresh: number;
  /** one to two weeks — waiting, not yet worrying */
  waiting: number;
  /** ≥ {@link QUIET_AFTER_DAYS} days — the amber share */
  quiet: number;
}

/** Bucket a list of ages (in days); unknown/future ages are dropped, not guessed. */
export function bucketAges(ages: (number | null)[]): AgeBuckets {
  const buckets: AgeBuckets = { fresh: 0, waiting: 0, quiet: 0 };
  for (const age of ages) {
    if (age === null || age < 0) continue;
    if (age < 7) buckets.fresh += 1;
    else if (age < QUIET_AFTER_DAYS) buckets.waiting += 1;
    else buckets.quiet += 1;
  }
  return buckets;
}

/**
 * Filed-per-week counts for the momentum bars, oldest week first (index
 * `weeks - 1` is the current, still-running week). Dates outside the window —
 * or unparsable — simply don't count; the bars claim only what they can see.
 */
export function weeklyCounts(
  filedDates: (string | null | undefined)[],
  today: string,
  weeks: number = MOMENTUM_WEEKS,
): number[] {
  const counts = new Array<number>(weeks).fill(0);
  for (const filed of filedDates) {
    const age = daysBetween(filed, today);
    if (age === null || age < 0 || age >= weeks * 7) continue;
    counts[weeks - 1 - Math.floor(age / 7)] += 1;
  }
  return counts;
}

/**
 * The momentum comparison the delta line states: the last 4 full-ish weeks
 * against the 4 before them, from the same buckets the bars draw — one
 * derivation, so the arrow can never contradict the picture.
 */
export function momentumDelta(counts: number[]): { recent: number; prior: number } {
  const half = Math.floor(counts.length / 2);
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  return { recent: sum(counts.slice(half)), prior: sum(counts.slice(0, half)) };
}
