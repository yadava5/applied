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
 *     reaches the server — there is no dismissal to reverse.
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

/**
 * PATCH the row's stage. Sticky (the row is tagged user-owned, so a later sync
 * never overwrites it); also restores a dismissed row.
 *
 * It trains nothing and labels no mail — `record_status_correction`
 * (`backend/jobtracker/cloud/applications.py:2251`) deliberately writes no
 * `training_data` example, because "what stage is this APPLICATION at?" is not
 * an answer to "what is this MESSAGE?".
 */
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
 * sync never overwrites — and #543 is why that mark carries weight rather than
 * being redundant: the sync CAN produce a role for these rows, so the mark is
 * the only thing standing between a typed title and the next extraction.
 */
export function roleChangeRequest(id: number, role: string | null): ProxyRequest {
  return { path: `/api/applications/${id}/role`, method: "PUT", body: { role } };
}

/**
 * "Not an application" — RECOVERABLE. Dismisses the row (off the board, off the
 * summary). Nothing is erased: the backend keeps the row under `?dismissed=true`
 * and restores it on demand.
 *
 * It trains nothing, and it records no training example either. `dismiss_application`
 * (`backend/jobtracker/cloud/applications.py:2378`) deliberately writes NO
 * per-message row — labelling every linked email `other` while leaving each one's
 * stored `classified_as` alone made the corpus disagree with the database. What it
 * does write is `dismissed_reason = "user"`, and a later sync honours that
 * (`applications.py:1521`) instead of putting the row back. That stickiness is the
 * only thing the hint may claim.
 */
export function removeFromBoardRequest(id: number): ProxyRequest {
  return { path: `/api/applications/${id}/dismiss`, method: "POST" };
}

/**
 * The way back from {@link removeFromBoardRequest} — the row returns to the
 * board with its mail intact.
 *
 * It REVERSES a dismissal the server already made, which is a different job
 * from the in-card window above: that one CANCELS a dismissal nothing has been
 * told about yet. The board itself no longer sends this (#903 — the row's own
 * cell carries the whole undo, and it cancels rather than reverses); the
 * caller left is the scan receipt's per-row `restore`, which is answering for
 * rows the SYNC removed, where there was never a window to cancel.
 *
 * `dismissed_reason = "user"` is why the reversal has to be explicit rather
 * than left to the next sync: the backend honours that flag
 * (`applications.py:1521`) and deliberately does not put the row back on its
 * own.
 */
export function restoreToBoardRequest(id: number): ProxyRequest {
  return { path: `/api/applications/${id}/restore`, method: "POST" };
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
 * Seconds a removal stays cancellable in the card before it is sent — and, as
 * of #903, the WHOLE undoable life of a removal rather than the first half of
 * it.
 *
 * It used to be six, followed by a corner toast carrying a second Undo for
 * `DURATIONS.undo` more. Measured on /demo at 1024: that toast landed at
 * focusable index 0 of 69 (its Undo at index 1) while painted bottom-right, so
 * from where the reader was left — index 33 — it was 32 Shift+Tabs backwards,
 * and it covered the stage select and the menu trigger of the row beneath it.
 * A second window nobody could reach by keyboard is not eight extra seconds of
 * recovery; it is eight seconds of the board saying something is reachable
 * when it is not. So it is gone, and this window absorbs what it was for.
 *
 * TEN, AND BOUNDED IN BOTH DIRECTIONS. Downward by what the window is for: a
 * reader has to notice, look away from whatever they were doing and press one
 * button, and six was chosen when a second chance existed behind it. Upward by
 * what the window COSTS: the dismissal is not sent until it closes, so this is
 * also how long a removal fails to persist — a reader who navigates away at
 * nine seconds has silently cancelled their own removal, and widening that gap
 * to make the number feel generous would be trading a real guarantee for a
 * cosmetic one. Ten is also the ceiling `tests/unit/row-actions.test.mjs`
 * already sanctions, which is the band this decision has to live inside.
 */
export const UNDO_WINDOW_SECONDS = 10;

/**
 * WHEN THE WINDOW CLOSES, NOT HOW LONG IT IS (#902, and #750 before it).
 *
 * The row used to hold `secondsLeft` in state and take one off it inside a
 * `setTimeout(…, 1000)`. That makes the window's real length a count of
 * RENDERS rather than a length of time: every step costs a wakeup, so a thread
 * that is busy when the timer comes due does not shorten the next step, it adds
 * to the total. Measured on /demo at 1024 on `fd803c79`, with a sampler running
 * inside the page — 6 steps of ~1.00s, window 6.02s — and again with an
 * observer taking a snapshot of the page every 500ms, which is what the reading
 * instrument in #902 was doing: 6 steps of ~2.00s, window 11.5s. Same build,
 * same fixtures; the only variable was who else wanted the main thread.
 *
 * A deadline cannot drift that way. The label is recomputed from it against the
 * clock ({@link undoSecondsLeft}) and the commit is armed against it, so a
 * stalled tab, a slow machine or a re-render mid-window costs at most a repaint
 * of the number — never a second of the window.
 */
export function undoWindowEndsAt(now: number): number {
  return now + UNDO_WINDOW_SECONDS * 1000;
}

/**
 * The number the tombstone shows at `now`. Rounded UP, so a window with any
 * time left in it never reads `0s`, and clamped so an overdue deadline reads
 * `0s` rather than a negative.
 */
export function undoSecondsLeft(endsAt: number, now: number): number {
  return Math.max(0, Math.ceil((endsAt - now) / 1000));
}

export const UNDO_LABEL = "Undo";

/**
 * EACH OUTCOME LINE IS A NAME PLUS A TAIL, AND THE SPLIT IS THE FIX (#424).
 *
 * `company` on a synced row is whatever an applicant-tracking system put in a
 * display name — attacker-chosen end to end, and the extraction path that
 * produces it (`_clean_sender_display_name`, `_valid_company_token`) rejects
 * stopwords, requisition codes and digits but applies no character class at
 * all. So the employer name can carry a bidi override, and these three
 * functions used to hand the row ONE composed string with the name already
 * inside it. A string cannot hold an element, so nothing could be neutralised
 * at the render site and the whole sentence drew raw: an unterminated U+202E in
 * the name reverses the text that FOLLOWS it, which on the pending tombstone is
 * the countdown the reader is deciding against ("… undo within 6s" swapped
 * ahead of the employer, measured on the real `<p role="status">`).
 *
 * Isolation does not fix that and was measured not to: the paragraph's computed
 * `unicode-bidi` is already `isolate` (Chromium blockifies the flex child) and
 * the reversal still happened, because isolation contains a run OUTWARD and the
 * defect is inside the paragraph, where the name has no element of its own.
 * Giving it one is the fix, so the name is handed back separately and
 * `ApplicationRow` draws it through `MailText`.
 *
 * The composed forms are kept — several callers only ever want a string — and
 * they are DEFINED from the same two parts, so the sentence a row draws and the
 * sentence a caller reads can never drift apart.
 */
export function rowName(company: string): string {
  return company.trim() || "This row";
}

/** What the tombstone that replaces the row says while the window is open. */
export function removalPendingTail(secondsLeft: number): string {
  return ` removed from the board · undo within ${Math.max(0, secondsLeft)}s`;
}

/**
 * The two committed outcomes, which must never read alike: one took the row off
 * the board and left it on disk, the other erased it. Saying "removed" for both
 * would undo, in the copy, the whole distinction this change exists to draw.
 */
const OFF_THE_BOARD = " removed from the board";

/**
 * UNCHANGED BY #921, and deliberately. "not deleted" was always true and was
 * never the problem — the problem was that it named no place. The place is now
 * a BUTTON beside this sentence (`ApplicationRow`'s committed tombstone), not
 * a third segment inside it: a string cannot be pressed, and a tombstone whose
 * text claimed a destination the reader could not reach from it would be the
 * same defect this issue is about, one clause shorter.
 */
export const REMOVED_TAIL = `${OFF_THE_BOARD} · not deleted`;

export const DELETED_TAIL = " deleted permanently";

export function removalPendingMessage(company: string, secondsLeft: number): string {
  return `${rowName(company)}${removalPendingTail(secondsLeft)}`;
}

export function removedMessage(company: string): string {
  return `${rowName(company)}${REMOVED_TAIL}`;
}

export function deletedMessage(company: string): string {
  return `${rowName(company)}${DELETED_TAIL}`;
}

// --- Copy -------------------------------------------------------------------

export const REMOVE_LABEL = "Not an application";
/**
 * "undoable" is gone from these hints: on a removal action it reads equally as
 * "can be undone" and "cannot be done". The window is stated in seconds, and
 * derived from the constant so the copy can never drift from the timer.
 *
 * AND IT SAYS WHAT HAPPENS AFTER THE SECONDS RUN OUT (#921). It used to end at
 * the number, which left the one thing the reader needs unstated — and the
 * honest completion of that sentence, before this issue, was "and then it is
 * gone for good", because no surface in the product listed a removed row. The
 * surface exists now, so the hint names it, at the only moment the naming is
 * cheap: before the act, in the menu the act is chosen from. Same two words as
 * the panel's title and the board menu's item; a reader who reads this and
 * then goes looking is looking for a string that exists.
 *
 * The third segment is a PLACE, not a second reassurance. "you can undo this"
 * said twice is not twice as recoverable; "then it waits in Removed rows" is
 * the fact the ten seconds do not cover.
 */
export const REMOVE_HINT = `takes it off the board · ${UNDO_WINDOW_SECONDS} s to undo · then it waits in Removed rows`;
/**
 * The synced-row variant. It used to end "· trains the model", which was false
 * twice over: no deployed path trains on anything, and this action does not even
 * record a training example. The sync stickiness it names instead is the one thing
 * that genuinely differs for a Gmail row — see {@link removeFromBoardRequest}.
 *
 * REWORDED, because the old tail now reads as a contradiction of the segment
 * before it: "a later sync won't bring it back" beside "it waits in Removed
 * rows" asks the reader to decide which of the two is true. Both are — the
 * distinction is the ACTOR, and that is what this says instead. A sync will
 * never re-file this row (`dismissed_reason = "user"`, honoured at
 * `applications.py:1521`); the reader can, by hand, from the panel the
 * previous segment named. That is precisely the asymmetry #921 asked to be
 * decided out loud: a hand dismissal stays final against the machine and stops
 * being final against the person who made it.
 */
export const REMOVE_STICKY_HINT = `${REMOVE_HINT} · no sync re-files it`;
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
