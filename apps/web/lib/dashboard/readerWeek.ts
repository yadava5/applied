/**
 * WHOSE WEEK the signed-in header is counting (#518).
 *
 * Two surfaces on the dashboard render "this week" and they did not share a
 * clock:
 *
 *  - the header (`50 filed · +N this wk`) is `GET /applications/summary`,
 *    counted server-side from a UTC Monday, because a counts-only endpoint
 *    rendered on the server cannot know the reader's zone at first paint;
 *  - the momentum caption beside it (`N this wk · up from M by now`) is
 *    computed in the browser from `useLocalToday()` — the reader's Monday —
 *    deliberately, because the bars it sits under bucket on the reader's day
 *    and the panel has to agree with itself (`age.ts` states why).
 *
 * For a reader west of UTC that leaves a window each week the size of their
 * offset — Sunday 20:00 to midnight in Eastern — where the header has rolled
 * into the new week and the caption has not. The header reads ~0 while the
 * caption still reports all of last week.
 *
 * THE SHAPE OF THE FIX is the one `useLocalToday` already uses for deadlines:
 * the server renders the UTC answer, and the client corrects it once there is
 * a reader with a zone. The endpoint takes the reader's Monday as
 * `?week_start=`, validates it, and reports in `week_start` which Monday it
 * actually counted — so the decision below is a comparison of two facts rather
 * than a second guess at the server's clock.
 *
 * ONLY WHEN THEY DIFFER, which is the point of comparing at all. Outside that
 * window — every hour of the week for a UTC reader, and all but a few hours a
 * week for everyone else — the reader's Monday IS the served Monday, this
 * returns `null`, and no second request is made and nothing on screen moves.
 *
 * Kept import-free apart from a relative `./age.ts`, same as `summary.ts`:
 * `node --test` strips types but cannot resolve the `@/` alias, and one value
 * import through it would make this module untestable.
 */
import { weekStartOf } from "./age.ts";

/** The same-origin proxy that carries the caller's JWT to the backend. */
export const SUMMARY_ROUTE = "/api/applications/summary";

/**
 * The Monday to re-ask the summary endpoint for, or `null` when the answer
 * already on screen counts the reader's own week.
 *
 * `readerToday` is the day the person reading the screen is living in —
 * `useLocalToday()`, which is the UTC day on the server and through hydration
 * and the reader's day after it, so on the passes where this must not move it
 * cannot. `servedWeekStart` is the endpoint's own `week_start`, i.e. the
 * Monday the number beside it was measured from.
 *
 * A `readerToday` this cannot parse yields `null` — the served answer stands.
 * Guessing a week from an unreadable day would be worse than the UTC answer it
 * would replace, which is at least a week somebody counted.
 */
export function summaryWeekCorrection(
  readerToday: string,
  servedWeekStart: string | null | undefined,
): string | null {
  const readerWeekStart = weekStartOf(readerToday);
  if (readerWeekStart === null) return null;
  return readerWeekStart === servedWeekStart ? null : readerWeekStart;
}

/** The corrected summary's URL. Encoded rather than interpolated raw: the
 *  value is a clock read, but it reaches a query string, and a route that
 *  builds one by concatenation is a habit worth not having. */
export function summaryUrlFor(weekStart: string): string {
  return `${SUMMARY_ROUTE}?week_start=${encodeURIComponent(weekStart)}`;
}
