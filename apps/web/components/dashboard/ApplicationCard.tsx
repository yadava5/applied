"use client";

import { ExternalLink, Loader2, TriangleAlert, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useId, useRef, useState } from "react";

import { DeadlineTag, FiledStamp, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { RowActionsMenu, type RowMenuItem } from "@/components/dashboard/RowActionsMenu";
import { cardQualifier } from "@/lib/dashboard/board";
import { todayISO } from "@/lib/dashboard/age";
import { filedAt } from "@/lib/dashboard/dates";
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
 * The stage control — label and `<select>` together — behind `memo`, and that
 * memo is load-bearing rather than a performance nicety.
 *
 * A controlled `<select>` is re-asserted onto the DOM by React on EVERY commit
 * that touches its fiber: `commitUpdate` → `updateProperties` → `updateOptions`
 * re-selects the option matching the `value` prop, and React 19 reads that prop
 * unconditionally — there is no "did value change?" guard on that path. So any
 * re-render of the surrounding card, for any reason, re-writes the control's
 * DOM value.
 *
 * That is invisible until a re-render lands between the moment the browser sets
 * the selected option and the moment it delivers `change`. `input`/`change` are
 * DISCRETE events, so React flushes all pending work synchronously inside the
 * `input` dispatch — and if a render was pending, the user's just-made choice
 * is overwritten with the row's old status before `onChange` ever sees it. The
 * handler then reads `next === app.status`, returns, and the stage change is
 * silently discarded: no request, no error, no visible failure.
 *
 * That is exactly what the reader's-day swap made reproducible. `useLocalToday`
 * re-renders every card once, tens of milliseconds after hydration (see
 * `useLocalToday.ts`), and a stage change chosen in that window vanished.
 * Isolating the control means a card re-render that changes nothing ABOUT THE
 * CONTROL — a re-dating, a sibling's move, a filter — bails out here, the
 * `<select>` fiber is never committed, and nothing can overwrite a choice in
 * flight.
 *
 * `memo` only bails out on shallow-equal props, so `onChange` has to be
 * referentially stable (`useCallback` in the card) — a fresh closure per render
 * defeats the whole thing. Nothing but the row's identity, its shown stage and
 * its in-flight state may be passed in; `today` deliberately is NOT, because
 * the day changing is precisely the re-render this must survive.
 */
const StageSelect = memo(function StageSelect({
  id,
  company,
  value,
  disabled,
  busy,
  onChange,
}: {
  id: number;
  company: string;
  /** The stage to SHOW — the optimistic one while a change is in flight. */
  value: string;
  disabled: boolean;
  busy: boolean;
  /** Must be referentially stable; see the note above. */
  onChange: (next: string) => void;
}) {
  return (
    <>
      <label className="sr-only" htmlFor={`status-${id}`}>
        Change stage for {company}
      </label>
      <select
        id={`status-${id}`}
        value={statusSelectValue(value)}
        disabled={disabled}
        aria-busy={busy}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[8.5rem] rounded border border-line-soft bg-surface px-1.5 py-0.5 text-[11px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
      >
        {statusOptions(value).map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </>
  );
});

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
  today = todayISO(),
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
  /** Today's calendar day — the board threads one read of the clock down so
   *  every card's age tag and deadline state derive from the same instant
   *  (`useLocalToday`: UTC for the server pass, the reader's own day once
   *  mounted). The UTC default only stands in for a caller that renders a card
   *  outside the board; the board always passes its own. */
  today?: string;
  /** Opens the detail sheet (the mail behind this card). */
  onOpenDetail?: (app: Application) => void;
  /**
   * How many OTHER applications share this company. A card is an application,
   * not a company — one employer can hold several — so this is a light
   * affordance ("+3 at Amazon"), never a merge. The board passes 0 while its
   * active filter already IS this company.
   */
  sameCompanyCount?: number;
  /** Filters the board to this card's company (opens the set view). */
  onFilterCompany?: (company: string) => void;
  /** True while this card is the one being dragged. */
  dragging?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLDivElement>) => void;
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

  // `useCallback`, not a plain function: this is `StageSelect`'s only unstable
  // prop, and a fresh closure per render would re-render the control on every
  // board change — which is the thing that overwrites a choice in flight (see
  // StageSelect). The deps are the row's identity and the stage it is showing;
  // re-dating a fixture changes neither.
  const optimisticTo = optimistic?.to;
  const onStatusChange = useCallback(
    async (next: string) => {
      const current = statusSelectValue(app.status);
      if (next === (optimisticTo ?? app.status)) return;
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
    },
    [app.id, app.status, optimisticTo, router, transport],
  );

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
      <div className="rounded-lg border border-dashed border-line bg-surface-2/60 p-3">
        <p role="status" className="text-xs leading-snug text-muted">
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
      </div>
    );
  }

  // --- Committed: an honest tombstone until the board re-renders, and it says
  // WHICH of the two happened — one is still on disk, the other is gone. -----
  if (removed) {
    return (
      <div className="rounded-lg border border-dashed border-line-soft bg-surface-2/40 p-3">
        <p role="status" className="text-xs text-dim">
          {removed === "deleted" ? deletedMessage(app.company) : removedMessage(app.company)}
        </p>
      </div>
    );
  }

  const role = app.position.trim();

  return (
    <div
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
                <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
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
              <span title={role} className="line-clamp-2 break-words text-[13px] leading-snug text-foreground">
                {role}
              </span>
            ) : null}
          </button>
        ) : (
          <div className="min-w-0">
            <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-strong">
              <span className="truncate">{app.company}</span>
              {qualifier && (
                <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
                  {qualifier}
                </span>
              )}
            </p>
            {role ? (
              <p title={role} className="line-clamp-2 break-words text-[13px] leading-snug text-foreground">
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
        <SameCompanyChip company={app.company} count={sameCompanyCount} onFilter={onFilterCompany} />
      ) : null}

      {/* Renders nothing unless the row carries a due_at — the tag never
          prompts, and never guesses (see DeadlineTag). */}
      <DeadlineTag dueAt={app.due_at} today={today} />

      <div className="mt-2 flex items-center justify-between gap-2">
        <StageSelect
          id={app.id}
          company={app.company}
          value={shownStatus}
          disabled={busy !== null}
          busy={busy === "status"}
          onChange={onStatusChange}
        />
        <FiledStamp filed={filed} status={shownStatus} today={today} />
      </div>

      {busy === "status" || optimistic ? (
        <p role="status" className="mt-1 text-[11px] text-dim">
          {busy === "status" ? `moving to ${shownStatus}…` : "board updating…"}
        </p>
      ) : null}

      {app.url ? (
        <a
          href={app.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
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
              className="rounded border border-reject/60 px-2 py-1 text-xs text-reject-ink transition-colors hover:bg-reject/15"
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
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject-ink" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}
