/**
 * What the inbox workbench says when **filing fails** — one sentence that is
 * true at every point the file action can stop.
 *
 * THE SENTENCE THIS REPLACES WAS FALSE (#604). The file bar used to render
 * "Couldn't file these (500) — nothing was changed." and, on a thrown fetch,
 * "Couldn't reach the server — nothing was filed." Neither claim is the
 * backend's to keep: `POST /gmail/sync` persists the mail INSIDE the merge —
 * `sync_gmail_pipeline_additive` commits, and `upsert_applications_for_user`
 * commits again inside it — and only then stamps the cursor with
 * `record_gmail_sync_success`. Everything after that first commit is a window
 * in which the mail is filed and the request still ends in a failure.
 *
 * The trigger that surfaced it is the migrate/deploy window an additive
 * revision opens (`alembic/versions/a3f7d21c60be_sync_scan_ledger.py` writes it
 * down): a returning user's sync commits the filed mail, then selects a
 * `sync_state` column the database does not have yet and raises. The mail IS
 * filed, the cursor is NOT advanced, the user gets a 500 — and was told nothing
 * changed. But the window is only the trigger. A stamp deadlock, a dropped
 * connection or a function killed on its ceiling all land in the same window,
 * and the network branch needs no schema drift at all: a request whose response
 * never arrives may have filed everything.
 *
 * SAME DECISION AS `components/dashboard/SyncBar.tsx`, which corrected this
 * exact class of false sentence first — say the one thing that is TRUE on every
 * path and at every failure point, and let the button beside it carry the
 * action. There is no "try again" in this copy for the same reason: the File
 * button stays enabled through the error state and is the retry.
 *
 * NARROWER THAN SYNCBAR'S BY ONE CLAUSE, deliberately. SyncBar says "filed or
 * removed", because Re-sync reaches `purge_and_rebuild_gmail_pipeline`, which
 * flushes the purge before it re-files. This surface always sends
 * `mode: "additive"` and the backend 400s a client-relayed rebuild
 * structurally, so nothing here can remove a row and "removed" would be a
 * possibility the reader does not have.
 */

/** How the file round trip ended, when it did not end well. */
export type FileFailure =
  /** The backend refused before it read or merged anything — see below. */
  | { kind: "not-connected" }
  /**
   * A non-OK status came back.
   *
   * `detail` is the backend's own sentence when it sent one (#852) — APPENDED
   * to the clause below, never replacing it. The valence has to survive: a
   * reader shown "3 filed and 1 queued of 4 scanned" with the failure lead
   * removed has been told a 500 was a success, which is the collapse #643
   * names. `proxySyncDetail` decides whether a body may be quoted at all.
   */
  | { kind: "status"; status: number; detail?: string | null }
  /** The request threw: no response at all, so no outcome is knowable. */
  | { kind: "unreachable" };

/**
 * The clause that survives every failure point.
 *
 * Vacuously true when nothing got as far as the merge, and literally true when
 * the merge committed and the stamp did not — which is the case the old copy
 * denied. It is also the right sentence for the response that was simply lost:
 * a run that finished and could not say so filed everything "before the
 * failure".
 */
const KEPT = "anything filed before the failure stays that way";

/** The failure note, verbatim, for the file bar. */
export function fileFailureNote(failure: FileFailure): string {
  switch (failure.kind) {
    /**
     * THIS BRANCH KEEPS ITS STRONGER CLAIM, and may — the same exemption
     * SyncBar's comment grants its own 409.
     *
     * 409 is spoken for on this endpoint: it means "Gmail is not connected"
     * (`SyncAlreadyRunning` took 429 rather than reuse it). The only place
     * `POST /gmail/sync` raises it is the first page of a SERVER-SIDE scan
     * coming back empty — before a single message is classified and before
     * either merge function is called, so nothing can have been filed.
     *
     * Stronger still here: this surface always relays its own `items`, and the
     * relay branch takes no Gmail read at all, so it cannot reach that raise.
     * The claim holds on both readings. Do not "fix" it to match the two
     * below.
     */
    case "not-connected":
      return "Gmail isn't connected — nothing was filed.";
    case "unreachable":
      return `Couldn't reach the server — ${KEPT}.`;
    default: {
      // The detail is a TAIL. The lead names the failure and the status, the
      // middle clause says what survived, and only then does the backend get
      // to be specific. Reordering these hands the reader a success sentence.
      const detail = failure.detail?.trim();
      const tail = detail ? ` · ${detail}` : "";
      return `Couldn't file these (${failure.status}) — ${KEPT}.${tail}`;
    }
  }
}
