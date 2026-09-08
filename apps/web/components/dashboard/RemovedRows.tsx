"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { MailText } from "@/components/mail/MailText";
import { Dialog } from "@/components/ui/Dialog";
import {
  REMOVED_DESCRIPTION,
  REMOVED_EMPTY,
  REMOVED_EMPTY_BODY,
  REMOVED_LOAD_FAILED,
  REMOVED_TITLE,
  RESTORED_LABEL,
  RESTORE_FAILED,
  RESTORE_LABEL,
  RESTORING_LABEL,
  RETRY_LABEL,
  pageCount,
  removalActor,
  removedRange,
} from "@/lib/applications/removed";
import { shortDate } from "@/lib/dashboard/dates";
import { onRemovedRequest } from "@/lib/dashboard/removed-bus";
import type { Application } from "@/lib/dashboard/summary";
import type { BoardTransport } from "@/lib/dashboard/transport";
import { safeText } from "@/lib/security/hostileText";

/**
 * WHY THIS IS A MODAL OVER THE BOARD AND NOT ONE OF THE THREE THINGS #921
 * NAMES.
 *
 * The issue leaves the shape open — a board filter, a settings page, or a
 * section of the export — and the constraint that decides it is that this is a
 * RECOVERY surface, not a second board: it must not compete with the worklist,
 * and "removed" must never read as a status a row can live in. A board filter
 * fails that outright. Filters on this board are stages and lenses; adding one
 * more puts removed rows in the same container, under the same stage spine, as
 * live ones, and every affordance around them then implies a row can sit there
 * as an ordinary state. A settings page fails the other constraint: Settings is
 * where account-level, deliberate, cold things live (export your data, delete
 * your account), it is a route away from the board, and nobody who has just
 * removed the wrong row goes there — a surface you cannot find while panicking
 * is the same as no surface. A section of the export is not a UI at all; it
 * already ships (`lib/applications/export.ts` walks both sets and counts them
 * separately), and the removal is still unrecoverable without a JSON file and a
 * text editor. So: a dialog. It is transient, which is what a recovery surface
 * should be; it keeps the reader on the board and hands focus back to whatever
 * opened it; and it borrows the geometry of the one modal this app already has
 * rather than inventing a place.
 *
 * `variant="center"`, deliberately not the `sheet` the detail pane uses. The
 * sheet is where a row's own content lives, pinned to the edge for as long as
 * you want it — exactly the "somewhere rows live" reading this must not have.
 *
 * FOUR DOORS, ONE NAME. Discoverability is the whole feature, so the words
 * "Removed rows" appear at every moment a reader could need them: in the row
 * menu's hint BEFORE the act (`REMOVE_HINT`), on the tombstone's button in the
 * instant AFTER it, on the board's nothing-matched line when a search cannot
 * find a row, and permanently in the command row's `⋯` menu. `removed-bus.ts`
 * is how three different subtrees reach this one mount.
 *
 * WHAT IT LOOKS LIKE, and why it borrows rather than invents: the list is
 * drawn inside a DASHED hairline frame, which is already this product's mark
 * for a row that is not on the board — the pending-removal cell and the
 * committed tombstone both wear it. So the panel reads as "these are off the
 * board" before a word is read, using vocabulary the reader has already been
 * taught, and it introduces no new visual identity. Restoring a row swaps its
 * action for one line of live green, the system's own "confident/live" ink: the
 * row is on the board again, and the frame it is still drawn in is now wrong
 * about it, which is the point. Density is the discriminator, not colour — two
 * lines per row, identity above provenance — because a column of rows that
 * differ only in a company name is the thing that reads as all-the-same.
 *
 * WHAT IT DOES NOT FIX, said plainly. `GET /applications` orders by
 * `created_at desc` whatever the `dismissed` flag says, so this list is in
 * FILED order, not removal order: the row you took off the board a moment ago
 * is first only if it was also the most recently filed. On a handful of
 * removals the pager covers it; on an account with hundreds of rebuild-purged
 * rows it does not, and the fix is a backend `order_by` on `dismissed_at` for
 * this predicate, which is a change to the endpoint and not to this view. The
 * copy here therefore never claims an order.
 */
export function RemovedRows({ transport }: { transport: BoardTransport }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "failed"; detail?: string }
    | { kind: "ok"; rows: Application[]; total: number }
  >({ kind: "loading" });
  /** Rows put back in this session — kept by id so the list can confirm in
   *  place rather than blinking the row out from under the pointer. */
  const [restored, setRestored] = useState<number[]>([]);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [failedId, setFailedId] = useState<number | null>(null);

  // The doors. `SyncBar`'s menu, the board's nothing-matched line and a row's
  // tombstone all raise the same signal; every one of them opens at page 1,
  // because each is somebody looking for a row they have just lost.
  useEffect(
    () =>
      onRemovedRequest(() => {
        setPage(1);
        setOpen(true);
      }),
    [],
  );

  /**
   * `alive` rather than an `AbortController`: the transport's demo half is an
   * in-memory read with no signal to give it, and what has to be prevented is
   * not the request but the WRITE — a page-2 answer arriving after the reader
   * has paged back would replace page 1's rows with rows the pager says are
   * not on screen.
   */
  const load = useCallback(
    async (which: number, alive: () => boolean) => {
      setState({ kind: "loading" });
      const result = await transport.removed(which);
      if (!alive()) return;
      setState(
        result.ok
          ? { kind: "ok", rows: result.applications, total: result.total }
          : { kind: "failed", detail: result.detail },
      );
    },
    [transport],
  );

  // Read on open and on every page change, never while closed: this is a
  // surface most sessions never touch, and a board that fetched its removed
  // rows on mount would pay for it on every load.
  //
  // Deferred into a macrotask rather than called in the effect body — the
  // house rule this codebase already follows for the demo store's re-dating
  // and the detail sheet's reset. A synchronous setState here is a cascading
  // render, and the lint rule that says so is right: nothing on screen depends
  // on the placeholder arriving in the same tick the dialog opens.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    const timer = window.setTimeout(() => void load(page, () => alive), 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [open, page, load]);

  async function restore(id: number) {
    setRestoringId(id);
    setFailedId(null);
    const result = await transport.restore(id);
    setRestoringId(null);
    if (!result.ok) {
      setFailedId(id);
      return;
    }
    setRestored((ids) => (ids.includes(id) ? ids : [...ids, id]));
    // The live board is a server render, so the row only comes back when the
    // page re-reads. On the fixture twin the transport has already committed to
    // its own store and this is a no-op — the same division `ApplicationRow`
    // works under, and the reason the panel does not try to mutate a list it
    // does not own.
    router.refresh();
  }

  const rows = state.kind === "ok" ? state.rows : [];
  const total = state.kind === "ok" ? state.total : 0;
  const pages = pageCount(total);

  return (
    <Dialog
      open={open}
      onClose={() => setOpen(false)}
      title={REMOVED_TITLE}
      description={REMOVED_DESCRIPTION}
    >
      {state.kind === "loading" ? (
        // A height-holding placeholder, not a spinner: the panel has just
        // opened over the board and a box that grows as rows arrive moves the
        // one control the reader came for.
        <p role="status" className="rounded-lg border border-dashed border-line-soft px-3 py-8 text-center text-xs text-dim">
          reading your removed rows…
        </p>
      ) : state.kind === "failed" ? (
        <div role="alert" className="rounded-lg border border-reject/40 bg-reject/10 px-3 py-4">
          <p className="text-sm text-strong">{REMOVED_LOAD_FAILED}</p>
          {state.detail ? <p className="mt-1 text-xs text-muted">{state.detail}</p> : null}
          <button
            type="button"
            onClick={() => void load(page, () => true)}
            className="mt-3 rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface"
          >
            {RETRY_LABEL}
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-line-soft px-3 py-8 text-center">
          <p className="text-sm text-strong">{REMOVED_EMPTY}</p>
          <p className="mx-auto mt-1 max-w-xs text-xs text-muted">{REMOVED_EMPTY_BODY}</p>
        </div>
      ) : (
        <ul className="max-h-[min(52vh,26rem)] divide-y divide-line-soft overflow-y-auto rounded-lg border border-dashed border-line-soft">
          {rows.map((row) => {
            const role = row.position.trim();
            const isBack = restored.includes(row.id);
            return (
              <li key={row.id} className="flex items-start gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  {/* The board's own identity line: employer anchors, role
                      discriminates. Four rows from one employer have to read
                      as four different applications here too, and both halves
                      are attacker-chosen text off a mailbox — so both draw
                      through `MailText`, exactly as a board row does. */}
                  <p className="flex min-w-0 items-baseline gap-2">
                    <span
                      title={safeText(row.company)}
                      className="max-w-[11rem] shrink-0 truncate text-sm font-medium text-strong"
                    >
                      <MailText value={row.company} />
                    </span>
                    {role ? (
                      <span
                        title={safeText(role)}
                        className="min-w-0 truncate text-[13px] text-foreground"
                      >
                        <MailText value={role} />
                      </span>
                    ) : null}
                  </p>
                  {/* Who took it off, and when. The actor is the discriminator
                      that stops this list reading as one undifferentiated
                      column — the set has two authors and the panel may not
                      blur them (see `removalActor`). The date is a machine
                      value and gets the mono face; the phrase beside it is
                      prose and does not.

                      `text-muted`, not the `text-dim` the board spends on its
                      own 11px status lines, and the difference is measured
                      rather than felt: dim on `--surface` is APCA Lc 61.1,
                      which sits ON the ramp's Lc 60 floor with nothing in
                      hand, and this line is the panel's only explanation of
                      why a row the reader may not remember touching is here.
                      Muted measures Lc 70.3 / 10.88:1 on that same ground
                      (Lc 86.9 / 7.73:1 on the paper one), and the three ranks
                      in this cell stay ordered — company Lc 102.7, role
                      Lc 82.4, this Lc 70.3. */}
                  <p className="mt-0.5 text-[11px] text-muted">
                    {removalActor(row.dismissed_reason)}
                    {row.dismissed_at ? (
                      <>
                        {" · "}
                        <time dateTime={row.dismissed_at} className="font-mono">
                          {shortDate(row.dismissed_at)}
                        </time>
                      </>
                    ) : null}
                  </p>
                </div>
                {isBack ? (
                  // The one place this panel spends colour. Green is already
                  // "live" in this system, the row IS live again, and it is
                  // said in the same words the button promised.
                  <span className="shrink-0 pt-0.5 text-xs text-live">{RESTORED_LABEL}</span>
                ) : (
                  <span className="flex shrink-0 items-center gap-2 pt-0.5">
                    {failedId === row.id ? (
                      <span role="alert" className="text-xs text-reject-ink">
                        {RESTORE_FAILED}
                      </span>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void restore(row.id)}
                      disabled={restoringId !== null}
                      aria-label={`${RESTORE_LABEL} — ${safeText(row.company)}`}
                      className="rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {restoringId === row.id ? RESTORING_LABEL : RESTORE_LABEL}
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* The pager states its own scale and nothing else. It appears only when
          there is a second page — an account with four removed rows should not
          be shown the machinery for hundreds — and it claims no ORDER, because
          the endpoint's is by filed date and not by when a row was removed. */}
      {state.kind === "ok" && pages > 1 ? (
        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="tabular font-mono text-[11px] text-dim">
            {removedRange(page, rows.length, total)}
          </span>
          <span className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded border border-line px-2 py-1 text-xs text-muted transition-colors hover:border-line-strong hover:text-strong disabled:cursor-not-allowed disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="rounded border border-line px-2 py-1 text-xs text-muted transition-colors hover:border-line-strong hover:text-strong disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </span>
        </div>
      ) : null}
    </Dialog>
  );
}
