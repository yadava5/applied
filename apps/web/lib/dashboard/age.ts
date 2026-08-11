/**
 * Pure age/momentum math for the dashboard's honest signals. Everything here
 * is a function of calendar-day strings — the same "read the characters, never
 * construct a local Date" rule as `dates.ts` (see its header for the timezone
 * bug that rule exists to prevent). `todayISO()` is the one clock read, and it
 * is UTC on both server and client, so hydration can only disagree across the
 * instant of UTC midnight itself.
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

/** Today's calendar day, UTC — identical on server and client. */
export function todayISO(now: number = Date.now()): string {
  return new Date(now).toISOString().slice(0, 10);
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
