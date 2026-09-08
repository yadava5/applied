/**
 * Everything about reading the removed-rows list that is not I/O.
 *
 * Split out for the reason `export.ts` was: the two halves of this feature sit
 * on opposite sides of a boundary `node --test` cannot cross. The proxy route
 * needs the Next runtime and a Supabase cookie jar; the panel needs a DOM. What
 * BOTH need — the query that makes the backend answer with removed rows rather
 * than the board, the page the client asks for, the phrase that names who took
 * a row off — is pure, and lives here so it can be executed by a test.
 *
 * `removedPageQuery` is the load-bearing one. `dismissed` is the single flag
 * separating "the list an undo surface reads" from "the board", the backend
 * filters `dismissed_at` EXCLUSIVELY on it
 * (`backend/jobtracker/cloud/applications.py:4994`), and a `false` there
 * returns a perfectly plausible page of live rows — a recovery surface showing
 * the board back to the reader, with a "Put it back" button beside rows that
 * never left. Nothing downstream could tell: same shape, same status codes, a
 * list that renders. So the flag is asserted directly
 * (`tests/unit/removed-rows.test.mjs`), because the browser-level test cannot
 * reach it — /demo runs a fixture transport and never issues this request.
 *
 * No imports, no React, no `@/` alias: `node --test` loads this file directly.
 */

/**
 * Rows per page in the panel.
 *
 * TEN, and small on purpose. This is a modal over the board, not a second
 * board: it holds one screenful the reader can scan without scrolling a
 * scroller inside a scroller, and the pager states its own scale ("1–10 of
 * 47") so a long list never pretends to be short. The backend's own ceiling is
 * `MAX_PAGE_SIZE = 500` and its default is 100 — both are list-endpoint sizes
 * chosen for a whole board in one response, which is exactly what this surface
 * must not be.
 */
export const REMOVED_PAGE_SIZE = 10;

/**
 * The backend query for one page of removed rows.
 *
 * `dismissed: true` is the whole reason this function exists rather than an
 * object literal at the call site — see the module note.
 */
export function removedPageQuery(page: number): {
  page: number;
  page_size: number;
  dismissed: boolean;
} {
  return { page: clampPage(page), page_size: REMOVED_PAGE_SIZE, dismissed: true };
}

/** The same-origin path the panel fetches. The JWT is attached server-side. */
export function removedPagePath(page: number): string {
  return `/api/applications/removed?page=${clampPage(page)}`;
}

/**
 * A page number from anywhere untrusted — a query string, a stale bit of
 * client state — clamped to something the backend will accept (`ge=1`).
 *
 * The backend 422s a zero or a negative, and a 422 rendered in a recovery
 * surface reads as "your removed rows are gone". Clamping is the honest
 * answer: page 1 is what a reader asking for page 0 meant.
 */
export function clampPage(page: unknown): number {
  const n = typeof page === "number" ? page : Number(page);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
}

/** How many pages `total` rows make. Zero rows is still one (empty) page. */
export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / REMOVED_PAGE_SIZE));
}

/**
 * "1–10 of 47" — the pager's own scale, so a page is never mistaken for the
 * whole set. `count` is what this page actually returned rather than the page
 * size: the last page is short, and claiming ten rows where four are drawn is
 * the class of number this repo keeps finding wrong.
 */
export function removedRange(page: number, count: number, total: number): string {
  if (total <= 0 || count <= 0) return "";
  const first = (clampPage(page) - 1) * REMOVED_PAGE_SIZE + 1;
  return `${first}–${first + count - 1} of ${total}`;
}

/**
 * WHO took the row off the board, in the product's own words.
 *
 * The list has two authors and the panel may not blur them. `dismissed=true`
 * returns the user's own removals AND everything a rebuild purged — the
 * backend's query parameter says so outright, and `dismissed_reason` is the
 * only thing that tells them apart. A panel that said "you removed these"
 * would be wrong for every resync row, and a panel that said nothing would
 * leave a reader unable to explain rows they have no memory of touching.
 *
 * "rebuild" rather than "sync": that is the word `ScanReceipt` uses for the run
 * that removes things, and the plain `Sync` button never removes anything at
 * all. An unknown reason claims nothing about an actor — the row is off the
 * board, which is all the data supports.
 */
export function removalActor(reason: string | null | undefined): string {
  if (reason === "user") return "you removed this";
  if (reason === "resync") return "a rebuild removed this";
  return "off the board";
}

// --- Copy -------------------------------------------------------------------

/**
 * ONE NAME, EVERYWHERE (the vocabulary rule): this exact string is the panel's
 * title, the board menu's item, the phrase in the row menu's removal hint and
 * the word on the tombstone's button. A reader who read the hint at the moment
 * of the act is looking for these two words and finds them unchanged.
 */
export const REMOVED_TITLE = "Removed rows";

/** The panel's subtitle: what this list is, and what can be done with it. */
export const REMOVED_DESCRIPTION = "Off the board, not deleted. Put any of them back.";

/**
 * Empty, and it is the GOOD state — so it reassures rather than invites. Every
 * other empty screen in this product asks for an action ("connect your mail",
 * "file an application"); the only action this one could ask for is removing a
 * row, which is the opposite of what this surface is for.
 */
export const REMOVED_EMPTY = "Nothing is off the board.";
export const REMOVED_EMPTY_BODY =
  "Rows you take off the board wait here until you put them back.";

/** The action, named for what it does — and named the same in the confirmation. */
export const RESTORE_LABEL = "Put it back";
export const RESTORING_LABEL = "putting it back…";
export const RESTORED_LABEL = "back on the board";

/**
 * The failure. Same sentence as the scan receipt's per-row restore
 * (`SyncBar.tsx`), deliberately: it is the same act failing the same way, and
 * two wordings for one outcome is how a product stops sounding like itself.
 */
export const RESTORE_FAILED = "couldn't restore — still removed";

/** The list itself could not be read. Says what is intact, then what to do. */
export const REMOVED_LOAD_FAILED = "Couldn't read your removed rows — nothing was lost.";
export const RETRY_LABEL = "Try again";
