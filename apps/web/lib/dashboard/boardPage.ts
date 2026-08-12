/**
 * Upper bound on rows pulled for the board in one page. Large enough that a
 * typical account sees its whole board, capped so a pathological account never
 * ships thousands of rows to the client — the subtitle stays exact regardless
 * via the counts-only summary endpoint.
 *
 * Shared by the dashboard page and the shell rail's pulse loader
 * (`lib/shell/rail.ts`), and the SAME number on purpose, twice over: the two
 * fetches carry identical URLs, so React's request memoization collapses them
 * into one backend read when the shell wraps /dashboard — and the rail's
 * derived signals describe exactly the slice the board is showing, never a
 * private one that could disagree with it.
 */
export const BOARD_PAGE_SIZE = 200;
