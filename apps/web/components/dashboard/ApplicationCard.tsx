"use client";

import { ExternalLink, Loader2, TriangleAlert, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { RowActionsMenu, type RowMenuItem } from "@/components/dashboard/RowActionsMenu";
import { cardQualifier } from "@/lib/dashboard/board";
import { filedAt, shortDate } from "@/lib/dashboard/dates";
import {
  CANCEL_LABEL,
  DELETE_CONFIRM_LABEL,
  DELETE_CONFIRM_QUESTION,
  DELETE_FAILED,
  DELETE_HINT,
  DELETE_LABEL,
  REMOVE_FAILED,
  REMOVE_HINT,
  REMOVE_LABEL,
  REMOVE_TRAINS_HINT,
  UNDO_LABEL,
  UNDO_WINDOW_SECONDS,
  deletedMessage,
  removalPendingMessage,
  removedMessage,
  statusChangeFailure,
} from "@/lib/dashboard/rowActions";
import { statusOptions, statusSelectValue } from "@/lib/dashboard/status";
import { type Application, STAGES, stageOf } from "@/lib/dashboard/summary";
import { liveBoardTransport, type BoardTransport } from "@/lib/dashboard/transport";

/**
 * One pipeline row — clickable, correctable, and no longer able to lose an
 * application to a single click.
 *
 * Three behaviours here are load-bearing:
 *
 *  1. **Removal is recoverable.** "Not an application" no longer fires
 *     anything: the card becomes a tombstone with an Undo for
 *     `UNDO_WINDOW_SECONDS`, and only when that expires does it POST the
 *     backend's *soft* dismiss (row + emails stay on disk, restorable).
 *     Undo is a cancelled timer — nothing was sent, so there is nothing to
 *     reverse and no training example written and then written over. The hard
 *     `DELETE` — which erases the row and its linked mail, and which no layer
 *     can undo — is a separate item behind an inline confirm.
 *  2. **The stage control is optimistic.** The chosen stage (and the card's
 *     stage accent) change on click instead of after the round trip, with an
 *     in-flight state on the control; a failure rolls the value back visibly
 *     and says what it tried, what the row still is, and why.
 *  3. **The stage list is not written here.** It comes from
 *     `lib/dashboard/status.ts`, mirroring the API's enum, so the dropdown
 *     cannot again offer a value the API answers 422 to.
 *
 * Every mutation goes through the board transport (the live default posts to
 * the same-origin proxy, so the JWT stays server-side; `/demo` passes an
 * in-memory one so this exact component runs on fixtures) and, on success,
 * `router.refresh()` re-renders the server board from fresh data.
 */
export function ApplicationCard({
  app,
  columnLabel,
  onOpenDetail,
  sameCompanyCount = 0,
  onFilterCompany,
  dragging = false,
  onDragStart,
  onDragEnd,
  transport = liveBoardTransport,
}: {
  app: Application;
  /** The heading of the column this card is rendered in (see `board.ts`). */
  columnLabel?: string;
  /** Opens the detail sheet (the mail behind this card). */
  onOpenDetail?: (app: Application) => void;
  /**
   * How many OTHER applications share this company. A card is an application,
   * not a company — one employer can hold several — so this is a light
   * affordance ("3 more at Amazon"), never a grouping.
   */
  sameCompanyCount?: number;
  /** Filters the board to this card's company. */
  onFilterCompany?: (company: string) => void;
  /** True while this card is the one being dragged. */
  dragging?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLLIElement>) => void;
  onDragEnd?: () => void;
  /** How mutations reach data — the live proxy by default, fixtures on /demo. */
  transport?: BoardTransport;
}) {
  const router = useRouter();
  const confirmId = `confirm-delete-${useId()}`;
  const [busy, setBusy] = useState<null | "status" | "removing" | "deleting">(null);
  const [error, setError] = useState<string | null>(null);
  /** The stage the user just picked, shown before the server confirms it. */
  const [optimistic, setOptimistic] = useState<{ from: string; to: string } | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  /** Non-null while a removal is pending and still cancellable. */
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  /** How this row left the board — the two outcomes are not the same event. */
  const [removed, setRemoved] = useState<null | "dismissed" | "deleted">(null);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const undoRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const committing = useRef(false);
  const refocusTrigger = useRef(false);

  // Server data caught up (to our value or to a different one): drop the
  // overlay and show the truth. Both arms matter — without the second, a
  // backend that answered with something else would leave the card asserting a
  // stage the row is not at, forever.
  if (optimistic && (app.status === optimistic.to || app.status !== optimistic.from)) {
    setOptimistic(null);
  }

  const shownStatus = optimistic?.to ?? app.status;
  const stage = STAGES.find((s) => s.key === stageOf(shownStatus))!;
  const heading = columnLabel ?? stage.label;
  const qualifier = cardQualifier(shownStatus, heading);
  // Real received date from the mail; fall back to the row's filed date.
  const filed = filedAt(app);
  const fromGmail = app.source === "gmail" || app.source === "gmail_user";
  const removalPending = secondsLeft !== null;

  async function onStatusChange(next: string) {
    const current = statusSelectValue(app.status);
    if (next === (optimistic?.to ?? app.status)) return;
    setError(null);
    setOptimistic({ from: app.status, to: next });
    setBusy("status");
    const result = await transport.changeStatus(app.id, next);
    // Cleared on success AND on failure: the old code left `busy` latched on
    // success, so a change that did not move the card to another column (it
    // stays mounted, and `router.refresh()` preserves client state) left the
    // control disabled and the spinner turning until a full reload.
    setBusy(null);
    if (!result.ok) {
      setOptimistic(null);
      setError(statusChangeFailure(next, current, result.detail));
      return;
    }
    if (result.status && result.status !== next) {
      setOptimistic({ from: app.status, to: result.status });
    }
    router.refresh();
  }

  const commitRemoval = useCallback(async () => {
    if (committing.current) return;
    committing.current = true;
    setSecondsLeft(null);
    setBusy("removing");
    const result = await transport.dismiss(app.id);
    committing.current = false;
    setBusy(null);
    if (!result.ok) {
      setError(result.detail ? `${REMOVE_FAILED} ${result.detail}` : REMOVE_FAILED);
      return;
    }
    setRemoved("dismissed");
    router.refresh();
  }, [app.id, router, transport]);

  // The undo window. The request is sent only when it runs out, so unmounting
  // (navigation, tab close) cancels the removal rather than committing it —
  // the safe direction for a destructive action.
  useEffect(() => {
    if (secondsLeft === null) return;
    const timer = setTimeout(() => {
      // The commit happens in the timer callback, never in the effect body:
      // the countdown is a subscription to the clock, not a cascading render.
      if (secondsLeft <= 1) void commitRemoval();
      else setSecondsLeft((s) => (s === null ? null : s - 1));
    }, 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft, commitRemoval]);

  // Focus follows the row: onto Undo while the removal is cancellable, and back
  // onto the menu trigger if it is cancelled. The trigger is unmounted at the
  // moment Undo is clicked, so the return has to wait for this render.
  useEffect(() => {
    if (removalPending) {
      undoRef.current?.focus();
      return;
    }
    if (!refocusTrigger.current) return;
    refocusTrigger.current = false;
    triggerRef.current?.focus();
  }, [removalPending]);

  useEffect(() => {
    if (confirmingDelete) cancelRef.current?.focus();
  }, [confirmingDelete]);

  async function onDeleteConfirmed() {
    setConfirmingDelete(false);
    setError(null);
    setBusy("deleting");
    const result = await transport.deleteRow(app.id);
    setBusy(null);
    if (!result.ok) {
      setError(result.detail ? `${DELETE_FAILED} ${result.detail}` : DELETE_FAILED);
      return;
    }
    setRemoved("deleted");
    router.refresh();
  }

  const menuItems: RowMenuItem[] = [
    {
      key: "dismiss",
      label: REMOVE_LABEL,
      hint: fromGmail ? REMOVE_TRAINS_HINT : REMOVE_HINT,
      onSelect: () => {
        setError(null);
        setConfirmingDelete(false);
        setSecondsLeft(UNDO_WINDOW_SECONDS);
      },
    },
    {
      key: "delete",
      label: DELETE_LABEL,
      hint: DELETE_HINT,
      tone: "danger",
      onSelect: () => {
        setError(null);
        setConfirmingDelete(true);
      },
    },
  ];

  // --- Pending removal: the row is still here, and one click keeps it --------
  if (removalPending) {
    return (
      <li className="rounded-lg border border-dashed border-line bg-surface-2/60 p-3">
        <p role="status" className="font-mono text-[11px] leading-snug text-muted">
          {removalPendingMessage(app.company, secondsLeft ?? 0)}
        </p>
        <button
          ref={undoRef}
          type="button"
          onClick={() => {
            refocusTrigger.current = true;
            setSecondsLeft(null);
          }}
          className="mt-2 inline-flex items-center gap-1.5 rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface"
        >
          <Undo2 className="h-3.5 w-3.5" aria-hidden />
          {UNDO_LABEL}
        </button>
      </li>
    );
  }

  // --- Committed: an honest tombstone until the board re-renders, and it says
  // WHICH of the two happened — one is still on disk, the other is gone. -----
  if (removed) {
    return (
      <li className="rounded-lg border border-dashed border-line-soft bg-surface-2/40 p-3">
        <p role="status" className="font-mono text-[11px] text-dim">
          {removed === "deleted" ? deletedMessage(app.company) : removedMessage(app.company)}
        </p>
      </li>
    );
  }

  const role = app.position.trim();

  return (
    <li
      aria-busy={busy !== null}
      draggable={onDragStart ? true : undefined}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      data-dragging={dragging || undefined}
      className="board-card group/card relative rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
      style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
    >
      <div className="flex items-start justify-between gap-2">
        {/* A card is an APPLICATION: company anchors it, the role discriminates
            it (four Amazon cards must read as four different rows), and the
            block itself opens the mail behind the card. */}
        {onOpenDetail ? (
          <button
            type="button"
            onClick={() => onOpenDetail(app)}
            aria-label={`Open ${app.company}${role ? ` — ${role}` : ""}`}
            className="min-w-0 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
          >
            <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-strong">
              <span className="truncate underline-offset-2 group-hover/card:underline">
                {app.company}
              </span>
              {qualifier && (
                <span className="shrink-0 rounded-full border border-line px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-muted">
                  {qualifier}
                </span>
              )}
            </span>
            {/* The role WRAPS (two lines) instead of ellipsizing: a job title's
                discriminating part is its tail — "…, AWS Data Services - 2026"
                — which is exactly what a one-line truncate eats. Four real
                Amazon roles measured 244–353px against a 198px box and
                rendered as identical text. `title` is the floor, not the fix:
                the board must read without hovering. */}
            {role ? (
              <span title={role} className="line-clamp-2 break-words text-xs text-foreground">
                {role}
              </span>
            ) : null}
          </button>
        ) : (
          <div className="min-w-0">
            <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-strong">
              <span className="truncate">{app.company}</span>
              {qualifier && (
                <span className="shrink-0 rounded-full border border-line px-1.5 py-px font-mono text-[9px] uppercase tracking-wide text-muted">
                  {qualifier}
                </span>
              )}
            </p>
            {role ? (
              <p title={role} className="line-clamp-2 break-words text-xs text-foreground">
                {role}
              </p>
            ) : null}
          </div>
        )}
        <div className="flex shrink-0 items-center gap-1">
          {busy !== null || optimistic ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-dim" aria-hidden />
          ) : null}
          <RowActionsMenu
            label={`Row actions for ${app.company}${role ? ` — ${role}` : ""}`}
            items={menuItems}
            disabled={busy !== null}
            triggerRef={triggerRef}
          />
        </div>
      </div>

      {sameCompanyCount > 0 && onFilterCompany ? (
        <button
          type="button"
          onClick={() => onFilterCompany(app.company)}
          aria-label={`Show all applications at ${app.company}`}
          className="mt-1 font-mono text-[10px] text-dim underline-offset-2 hover:text-strong hover:underline"
        >
          {sameCompanyCount} more at {app.company} →
        </button>
      ) : null}

      <div className="mt-2 flex items-center justify-between gap-2">
        <label className="sr-only" htmlFor={`status-${app.id}`}>
          Change stage for {app.company}
        </label>
        <select
          id={`status-${app.id}`}
          value={statusSelectValue(shownStatus)}
          disabled={busy !== null}
          aria-busy={busy === "status"}
          onChange={(e) => void onStatusChange(e.target.value)}
          className="max-w-[8.5rem] rounded border border-line-soft bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
        >
          {statusOptions(shownStatus).map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="tabular font-mono text-[10px] text-dim">{shortDate(filed)}</span>
      </div>

      {busy === "status" || optimistic ? (
        <p role="status" className="mt-1 font-mono text-[10px] text-dim">
          {busy === "status" ? `moving to ${shownStatus}…` : "board updating…"}
        </p>
      ) : null}

      {app.url ? (
        <a
          href={app.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 font-mono text-[10px] text-dim underline-offset-2 hover:text-strong hover:underline"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          open in gmail
        </a>
      ) : null}

      {/* The one action nothing can undo, so the one that asks first. Inline
          rather than a modal: a dialog on every removal is friction on the
          common case, and the common case ("Not an application") is undoable. */}
      {confirmingDelete ? (
        <div
          role="group"
          aria-label={`Confirm permanent delete of ${app.company}`}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            setConfirmingDelete(false);
            triggerRef.current?.focus();
          }}
          className="mt-2 rounded border border-reject/50 bg-reject/10 p-2"
        >
          {/* The stakes are wired to BOTH buttons rather than announced once as
              an alert: focus lands in here, so whichever button the user is on
              reads what it will do. */}
          <p id={confirmId} className="text-xs leading-snug text-strong">
            {DELETE_CONFIRM_QUESTION}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              ref={cancelRef}
              type="button"
              aria-describedby={confirmId}
              onClick={() => {
                setConfirmingDelete(false);
                triggerRef.current?.focus();
              }}
              className="rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface"
            >
              {CANCEL_LABEL}
            </button>
            <button
              type="button"
              aria-describedby={confirmId}
              onClick={() => void onDeleteConfirmed()}
              className="rounded border border-reject/60 px-2 py-1 text-xs text-reject transition-colors hover:bg-reject/15"
            >
              {DELETE_CONFIRM_LABEL}
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="mt-2 flex items-start gap-1.5 rounded border border-reject/50 bg-reject/10 px-2 py-1.5 text-xs leading-snug text-strong"
        >
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}
    </li>
  );
}
