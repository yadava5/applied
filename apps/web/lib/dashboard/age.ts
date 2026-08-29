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
 * "quiet" — the amber signal on cards and in the pulse. One threshold,
 * used everywhere, so the card tag and the strip's count can never disagree.
 */
export const QUIET_AFTER_DAYS = 14;

/**
 * How many day-buckets the momentum strip renders. Days, not weeks, and that
 * is the owner's measured complaint (#156): the real account filed its whole
 * board inside four weeks, so 8 weekly buckets rendered a 41-application
 * burst as 7 flat dashes and one filled tick. Filing happens in daily bursts
 * ("9 on Tuesday, nothing Thursday") — the shape weekly bucketing destroys is
 * exactly the one worth drawing.
 */
export const MOMENTUM_DAYS = 30;

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

/** The three age buckets the pulse draws for open applications. */
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
 * Filed-per-day counts for the momentum bars, oldest day first (index
 * `days - 1` is today). Dates outside the window — or unparsable — simply
 * don't count; the bars claim only what they can see.
 */
export function dailyCounts(
  filedDates: (string | null | undefined)[],
  today: string,
  days: number = MOMENTUM_DAYS,
): number[] {
  const counts = new Array<number>(days).fill(0);
  for (const filed of filedDates) {
    const age = daysBetween(filed, today);
    if (age === null || age < 0 || age >= days) continue;
    counts[days - 1 - age] += 1;
  }
  return counts;
}

/**
 * How many days of THIS CALENDAR WEEK have happened, counting today: 1 on a
 * Monday … 7 on a Sunday. Falls back to a full 7 for an unparsable day, which
 * is the reading that degrades to the old trailing window rather than to zero.
 */
export function daysElapsedThisWeek(today: string): number {
  const weekday = weekdayOf(today);
  return weekday === null ? 7 : weekday + 1;
}

/**
 * The Monday that begins `today`'s week, as `YYYY-MM-DD`. THE boundary — the
 * backend's `_week_start` (`backend/jobtracker/cloud/applications.py`) computes
 * the same date with `date.weekday()`, and `tests/unit/week-boundary.test.mjs`
 * and `backend/tests/test_this_week_is_a_calendar_week.py` assert the same
 * table of days on both sides so the two cannot drift.
 */
export function weekStartOf(today: string): string | null {
  const weekday = weekdayOf(today);
  if (weekday === null) return null;
  return isoDaysAgo(today, weekday);
}

export interface WeekOverWeek {
  /** Filed since this week's Monday, inclusive of today. */
  thisWeek: number;
  /** Filed in ALL SEVEN days of the previous calendar week. */
  lastWeek: number;
  /** Filed in the previous week's FIRST {@link daysElapsed} days. */
  lastWeekToDate: number;
  /** 1 on a Monday … 7 on a Sunday. */
  daysElapsed: number;
}

/**
 * The momentum comparison the delta line states — a REAL CALENDAR WEEK, from
 * the same buckets the bars draw, so the arrow can never contradict the
 * picture.
 *
 * IT WAS A TRAILING SEVEN DAYS, and the owner reported that as wrong: "the
 * week counter should be actual real life week data, but real calendar". A
 * rolling window answers "how much in any seven days", which nobody plans by;
 * a week is the unit people actually apply in, and on a Monday it is supposed
 * to start over.
 *
 * MONDAY, and that is read off the product rather than chosen: `PulseDetail`
 * already draws a gap before every `weekdayOf(date) === 0` bar, so the strip
 * this caption sits under visibly breaks the week at Monday. A Sunday-start
 * count would have disagreed with the picture beside it. Python's
 * `date.weekday()` uses the same convention, so the backend agrees by
 * construction rather than by coincidence.
 *
 * WHOSE MONDAY, stated because this function is given whatever day its caller
 * holds and the callers do not all hold the same one:
 *
 *  - `PipelinePulse` passes `useLocalToday()` — the READER's day. "How many
 *    have I filed this week" is a question about the week the reader is
 *    living in, and the bars beside the caption are bucketed on that same day,
 *    so the panel is internally consistent.
 *  - the signed-in HEADER does not come through here at all: it is
 *    `GET /applications/summary`, counted in the database. It used to be the
 *    UTC week and nothing else, so for a reader west of UTC there was a window
 *    each week — Sunday 20:00 to midnight in Eastern, the size of their offset
 *    — where the header had rolled over and this caption had not. Since #518
 *    the endpoint takes the reader's Monday as `?week_start=` and says which
 *    Monday it counted; `lib/dashboard/readerWeek.ts` decides when to ask and
 *    `BoardSubtitle` does the asking, after hydration, on the same
 *    server-value-then-client-value pattern `useLocalToday` is built on.
 *  - `summarize()` still defaults to `Date.now()` and buckets on `todayISO` —
 *    the UTC day. TWO surfaces call it, and only one of them can show the
 *    split:
 *      · `DemoDashboard.tsx` renders `buildSubtitle(summary, notifications.weekly)`,
 *        so with the weekly pref on, /demo's header and its momentum caption
 *        can still disagree in exactly the window described above. The fix is
 *        one line (pass the `useLocalToday()` value the twin already holds),
 *        but it moves numbers the `demo-utc-minus-10` / `demo-utc-plus-14`
 *        Playwright projects measure, so it is not smuggled in here.
 *      · `MarketingBoard.tsx` renders `buildSubtitle(summarize(apps), false)`.
 *        `weekly` is a hard `false` there, and `buildSubtitle` omits the whole
 *        ` · +N this wk` segment when it is — so the landing board computes a
 *        UTC `thisWeek` and never prints it. Named here anyway, because "this
 *        call site cannot show the bug today" is a property of one argument
 *        that a future edit can flip without anyone remembering this note
 *        existed.
 *
 * The split was never new. Under a trailing window it moved a single day's
 * filings and nobody could see it; a calendar boundary made it a whole week's
 * worth, which is what got it filed rather than rediscovered.
 *
 * TWO BASELINES, because a partial week cannot honestly be compared with a
 * whole one. On a Monday `thisWeek` covers one day and `lastWeek` covers
 * seven, so a caption comparing them would report a collapse every Monday and
 * Tuesday, for a board that had not changed. {@link lastWeekToDate} is the
 * same number of days a week earlier — the like-for-like baseline the caption
 * renders — and {@link lastWeek} stays for the detail panel, which has room to
 * say which is which.
 */
export function weekOverWeek(counts: number[], today: string): WeekOverWeek {
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  const daysElapsed = daysElapsedThisWeek(today);
  const n = counts.length;
  // Clamped rather than left to `slice`'s negative-index behaviour, which
  // would silently count from the END of the window and read the WRONG days
  // if a caller ever passes fewer than 14 buckets.
  const thisWeekStart = Math.max(0, n - daysElapsed);
  const lastWeekStart = Math.max(0, n - daysElapsed - 7);
  return {
    thisWeek: sum(counts.slice(thisWeekStart)),
    lastWeek: sum(counts.slice(lastWeekStart, thisWeekStart)),
    // Bounded by `thisWeekStart` as well as by its own width. Without that
    // second bound a clamped `lastWeekStart` lets the baseline run FORWARD
    // into this week and count the very days it is supposed to be compared
    // against — measured on a 3-bucket array, where it returned 3 against a
    // last week that holds nothing at all.
    lastWeekToDate: sum(
      counts.slice(lastWeekStart, Math.min(thisWeekStart, lastWeekStart + daysElapsed)),
    ),
    daysElapsed,
  };
}

/**
 * The window's heaviest day, as an offset from today (`daysAgo: 0` = today).
 * Ties go to the most recent day — "your best day" should name the freshest
 * proof, not the stalest. `null` when nothing in the window was filed at all.
 */
export function bestDay(counts: number[]): { daysAgo: number; count: number } | null {
  let best: { daysAgo: number; count: number } | null = null;
  for (let i = counts.length - 1; i >= 0; i -= 1) {
    if (counts[i] > (best?.count ?? 0)) best = { daysAgo: counts.length - 1 - i, count: counts[i] };
  }
  return best;
}

/**
 * Consecutive filing days ending at today — or at yesterday when today is
 * still empty, because "your streak died at midnight" is not something to
 * tell someone who simply hasn't opened their mail yet.
 */
export function currentStreak(counts: number[]): number {
  let i = counts.length - 1;
  if (counts[i] === 0) i -= 1; // today may still be in progress
  let streak = 0;
  for (; i >= 0 && counts[i] > 0; i -= 1) streak += 1;
  return streak;
}

/**
 * The calendar day `daysAgo` days before `today`, as `YYYY-MM-DD` — the
 * inverse of {@link daysBetween}, for turning a bar index back into the date
 * it counts. Pure UTC day arithmetic on the calendar prefix; `toISOString`
 * here renders a UTC-midnight instant we constructed ourselves, so it cannot
 * exhibit the local-midnight drift `localTodayISO` exists to avoid.
 */
export function isoDaysAgo(today: string, daysAgo: number): string | null {
  const day = utcDay(today);
  if (day === null) return null;
  return new Date(day - daysAgo * DAY_MS).toISOString().slice(0, 10);
}

/**
 * Weekday of a calendar day, Monday = 0 … Sunday = 6 (or `null` if
 * unparsable). Day 0 of the UTC epoch was a Thursday, hence the +3.
 */
export function weekdayOf(iso: string): number | null {
  const day = utcDay(iso);
  if (day === null) return null;
  return (day / DAY_MS + 3) % 7;
}

/**
 * Open rows per day of age: index `0` = filed today … index `cap - 1`, with
 * a final overflow bin at index `cap` holding everything at least `cap` days
 * old — the same ≥{@link QUIET_AFTER_DAYS} share `bucketAges` calls quiet.
 * Unknown/future ages are dropped, not guessed, matching `bucketAges`.
 */
export function ageHistogram(
  ages: (number | null)[],
  cap: number = QUIET_AFTER_DAYS,
): number[] {
  const bins = new Array<number>(cap + 1).fill(0);
  for (const age of ages) {
    if (age === null || age < 0) continue;
    bins[Math.min(age, cap)] += 1;
  }
  return bins;
}
