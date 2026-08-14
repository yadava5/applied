/**
 * The decision half of "refresh when the reader comes back" — the rule that
 * makes a multi-minute router cache safe (`experimental.staleTimes.dynamic`
 * in `next.config.ts`, which carries the full reasoning).
 *
 * It is a pure function with an injected clock, deliberately: the whole
 * feature is a THRESHOLD, and a threshold asserted by hiding a real tab and
 * counting seconds is a test that measures the machine. Both halves have to
 * be executable — a refresh that always fires is a polling loop with extra
 * steps, and one that never fires is the stale-data bug the longer window
 * would otherwise introduce. `tests/unit/away-refresh.test.mjs` holds both,
 * plus the boundary.
 *
 * Dependency-free so `node --test` can load it without a bundler, the same
 * shape as `lib/shell/ambient-bus.ts`.
 */

/**
 * How long the tab must have been away before returning to it costs a
 * refetch. 60 s.
 *
 * The discriminating constraint is `threshold < staleTimes.dynamic` (60 <
 * 300). Past the stale window the next navigation refetches on its own, so
 * this rule only does work in the band BETWEEN the two — return after 90 s
 * and the cache would still serve a payload that is now the second-oldest
 * thing on screen. Set the threshold equal to the window and the feature is
 * near-inert; set it near zero and every glance at another window costs the
 * ~1.1 s the cache exists to avoid. Do not "simplify" the two numbers to one.
 *
 * 60 s is above any plausible glance — checking a calendar, pasting from
 * another app, reading a notification — and below the 15-minute cadence of
 * the scheduled sync (`crons` in the repo-root `vercel.json`, #284), which is
 * the only thing that changes this app's data with nobody looking.
 */
export const AWAY_REFRESH_THRESHOLD_MS = 60_000;

/**
 * Should returning to the tab invalidate the router cache?
 *
 * `awayAt` is the timestamp the tab was last hidden or blurred, or `null` if
 * it never left — the never-hidden case is a no-op, not a refresh. A negative
 * elapsed time (a clock that moved backwards, or a system wake that reordered
 * the two reads) falls out as `false` from the same comparison rather than
 * being special-cased into a refresh.
 */
export function shouldRefreshOnReturn(
  awayAt: number | null,
  now: number,
  thresholdMs: number = AWAY_REFRESH_THRESHOLD_MS,
): boolean {
  if (awayAt === null) return false;
  const awayMs = now - awayAt;
  if (!Number.isFinite(awayMs)) return false;
  return awayMs >= thresholdMs;
}
