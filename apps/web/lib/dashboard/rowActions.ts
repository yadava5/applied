/**
 * The decisions behind a pipeline row's actions — kept out of the component so
 * they can be asserted directly, the same discipline `review.ts` follows (JSX
 * cannot load under Node's built-in type stripping, and the repo has no
 * component-test framework, so any logic worth testing lives in a plain `.ts`
 * module and the component takes its behaviour from here and nowhere else).
 *
 * Three things live here:
 *
 *  1. The request descriptors. Which endpoint a row action hits is a
 *     correctness question — "Not an application" MUST hit the recoverable
 *     `dismiss` (the row and its emails stay on disk, `dismissed_at` is set and
 *     `POST /applications/{id}/restore` can put it back), and only the
 *     explicitly-confirmed action may hit `DELETE`, which erases both.
 *  2. The undo window for the recoverable removal. The request is not sent
 *     until the window expires, so "Undo" is a `clearTimeout` and nothing
 *     reaches the server — no dismissal to reverse, and no training example
 *     written and then re-written by the reversal.
 *  3. The row-menu keyboard model: which key means what, and which item that
 *     lands on. Plus the one-menu-at-a-time registry.
 *
 * No imports, no React: `node --test` loads this file directly.
 */

// --- Requests ---------------------------------------------------------------

export interface ProxyRequest {
  /** Same-origin proxy path; the Supabase JWT is attached server-side. */
  path: string;
  method: "PATCH" | "PUT" | "POST" | "DELETE";
  body?: Record<string, unknown>;
}

/** PATCH the row's stage. Sticky + trains; also restores a dismissed row. */
export function statusChangeRequest(id: number, status: string): ProxyRequest {
  return { path: `/api/applications/${id}`, method: "PATCH", body: { status } };
}

/**
 * PUT the row's deadline; `null` clears it. Any write through this endpoint
 * makes `due_source` `"user"`, which a later sync never overwrites — only
 * mail-extracted dates are the sync's to move.
 */
export function deadlineChangeRequest(id: number, dueAt: string | null): ProxyRequest {
  return { path: `/api/applications/${id}/deadline`, method: "PUT", body: { due_at: dueAt } };
}

/**
 * PUT the role a human typed; `null` clears it (issue #72).
 *
 * Its own endpoint, deliberately, rather than a field added to the status
 * PATCH: `ApplicationStatusUpdate` does not set `extra="forbid"`, so an unknown
 * key posted there is silently dropped and the UI would report a save the
 * server never made. A write here marks `position_source: "user"`, which the
 * sync never overwrites — and it never overwrites it because the sync can never
 * produce a role for these rows in the first place.
 */
export function roleChangeRequest(id: number, role: string | null): ProxyRequest {
  return { path: `/api/applications/${id}/role`, method: "PUT", body: { role } };
}

/**
 * "Not an application" — RECOVERABLE. Dismisses the row (off the board, off the
 * summary) and trains the classifier that the mail was misfiled. Nothing is
 * erased: the backend keeps the row under `?dismissed=true` and restores it on
 * demand.
 */
export function removeFromBoardRequest(id: number): ProxyRequest {
  return { path: `/api/applications/${id}/dismiss`, method: "POST" };
}

/**
 * Hard delete — NOT recoverable at any layer: the row and every linked email
 * are erased, so there is nothing left to undo. This is the one row action that
 * must be confirmed before it is sent.
 */
export function permanentDeleteRequest(id: number): ProxyRequest {
  return { path: `/api/applications/${id}`, method: "DELETE" };
}

// --- Undo window ------------------------------------------------------------

/**
 * Seconds a removal stays cancellable in the card before it is sent.
 *
 * Long enough to notice a misclick and reach the button, short enough that the
 * board is not lying about its contents for an age. The card is not sent
 * anywhere during the window: leaving the page cancels it, which is the safe
 * direction for a destructive action (worst case the row survives).
 */
export const UNDO_WINDOW_SECONDS = 6;

export const UNDO_LABEL = "Undo";

/** What the tombstone that replaces the row says while the window is open. */
export function removalPendingMessage(company: string, secondsLeft: number): string {
  return `${rowName(company)} removed from the board · undo within ${Math.max(0, secondsLeft)}s`;
}

/**
 * The two committed outcomes, which must never read alike: one took the row off
 * the board and left it on disk, the other erased it. Saying "removed" for both
 * would undo, in the copy, the whole distinction this change exists to draw.
 */
export function removedMessage(company: string): string {
  return `${rowName(company)} removed from the board · not deleted`;
}

export function deletedMessage(company: string): string {
  return `${rowName(company)} deleted permanently`;
}

function rowName(company: string): string {
  return company.trim() || "This row";
}

// --- Copy -------------------------------------------------------------------

export const REMOVE_LABEL = "Not an application";
/**
 * "undoable" is gone from these hints: on a removal action it reads equally as
 * "can be undone" and "cannot be done". The window is stated in seconds, and
 * derived from the constant so the copy can never drift from the timer.
 */
export const REMOVE_HINT = `takes it off the board · ${UNDO_WINDOW_SECONDS} s to undo`;
export const REMOVE_TRAINS_HINT = `takes it off the board · ${UNDO_WINDOW_SECONDS} s to undo · trains the model`;
export const DELETE_LABEL = "Delete permanently";
export const DELETE_HINT = "erases the row and its emails";
export const DELETE_CONFIRM_QUESTION =
  "Delete permanently? This erases the row and its linked emails. It cannot be undone — “Not an application” can.";
export const DELETE_CONFIRM_LABEL = "Yes, delete permanently";
export const CANCEL_LABEL = "Cancel";

export const REMOVE_FAILED = "Couldn't remove this row — it is still on your board.";
export const DELETE_FAILED = "Couldn't delete this row — it is still on your board.";

/**
 * A stage change that failed must say what it tried, what the row is now, and
 * that the visible value went back — the roll-back is otherwise indistinguishable
 * from the user's own click not registering.
 */
export function statusChangeFailure(target: string, previous: string, detail?: string): string {
  const head = `Couldn't move this to “${target}” — it is still “${previous}”.`;
  const reason = detail?.trim();
  return reason ? `${head} ${reason}` : head;
}

// --- Row menu keyboard model ------------------------------------------------

export type MenuIntent = "close" | "first" | "last" | "next" | "previous" | null;

/**
 * What a key pressed INSIDE the open menu means.
 *
 * Escape closing the menu is the item that measured as entirely absent —
 * `defaultPrevented: false` on the menu, on `activeElement`, on `document` and
 * on `window`, because no handler existed anywhere. Tab closes too: a menu that
 * stays open while focus walks off it is the stale-menu state that got the
 * wrong row's Delete clicked.
 */
export function menuKeyIntent(key: string): MenuIntent {
  switch (key) {
    case "Escape":
    case "Tab":
      return "close";
    case "ArrowDown":
      return "next";
    case "ArrowUp":
      return "previous";
    case "Home":
      return "first";
    case "End":
      return "last";
    default:
      return null;
  }
}

/** What a key pressed on the CLOSED trigger means: open, focused where? */
export function triggerKeyIntent(key: string): "first" | "last" | null {
  if (key === "ArrowDown") return "first";
  if (key === "ArrowUp") return "last";
  return null;
}

/**
 * The item an intent lands on. Wraps at both ends (the WAI-ARIA menu pattern);
 * `null`/`close`/an empty menu leave the index where it was.
 */
export function rovingIndex(current: number, count: number, intent: MenuIntent): number {
  if (count <= 0) return 0;
  const safe = Number.isInteger(current) ? Math.min(Math.max(current, 0), count - 1) : 0;
  switch (intent) {
    case "next":
      return (safe + 1) % count;
    case "previous":
      return (safe - 1 + count) % count;
    case "first":
      return 0;
    case "last":
      return count - 1;
    default:
      return safe;
  }
}

// --- One menu at a time -----------------------------------------------------

export interface MenuRegistry {
  /** Open `id`, closing whichever other menu was open. */
  open(id: string, close: () => void): void;
  /** Release `id`. A stale id (some other menu opened since) is a no-op. */
  close(id: string): void;
  /** The currently open menu, for assertions. */
  openId(): string | null;
}

/**
 * Two row menus could be open at once (`aria-expanded="true"` on both
 * triggers), so a menu left open over one row overlapped another's rows. Opening
 * one now closes the other.
 *
 * Re-opening the SAME id must not call that id's own close callback, or the
 * trigger's toggle would fight the registry and the menu would never open.
 */
export function createMenuRegistry(): MenuRegistry {
  let openId: string | null = null;
  let closeOpen: (() => void) | null = null;

  return {
    open(id, close) {
      if (openId !== null && openId !== id && closeOpen) closeOpen();
      openId = id;
      closeOpen = close;
    },
    close(id) {
      if (openId !== id) return;
      openId = null;
      closeOpen = null;
    },
    openId: () => openId,
  };
}

/**
 * The board's shared registry. Module-level state is safe here because only
 * client components touch it, and only from effects and event handlers — never
 * during a server render.
 */
export const rowMenuRegistry = createMenuRegistry();
