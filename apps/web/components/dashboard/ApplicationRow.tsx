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

/** The honest slot for the 8-in-29 case: a row whose mail never named a role
 *  says so, in the same words the detail sheet and the review picker already
 *  use — instead of rendering shorter than its neighbours and making the
 *  whole list ragged. */
export const NO_ROLE_LABEL = "role not captured";

/**
 * The stage control — label and `<select>` together — behind `memo`, and that
 * memo is load-bearing rather than a performance nicety.
 *
 * A controlled `<select>` is re-asserted onto the DOM by React on EVERY commit
 * that touches its fiber: `commitUpdate` → `updateProperties` → `updateOptions`
 * re-selects the option matching the `value` prop, and React 19 reads that prop
 * unconditionally — there is no "did value change?" guard on that path. So any
 * re-render of the surrounding row, for any reason, re-writes the control's
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
 * re-renders every row once, tens of milliseconds after hydration (see
 * `useLocalToday.ts`), and a stage change chosen in that window vanished.
 * Isolating the control means a row re-render that changes nothing ABOUT THE
 * CONTROL — a re-dating, a sibling's move, a filter — bails out here, the
 * `<select>` fiber is never committed, and nothing can overwrite a choice in
 * flight.
 *
 * `memo` only bails out on shallow-equal props, so `onChange` has to be
 * referentially stable (`useCallback` in the row) — a fresh closure per render
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
        // `w-[8.5rem]`, not max-w: an intrinsic-width select is as wide as its
        // current value, so 17 rows put the board's main control on four
        // different x positions (a 78px spread, measured). Fixed width + a
        // fixed-width tail after it (see the meta cluster) is what makes the
        // selects a column. `h-6` matches the cluster's other controls (the
        // Gmail slot, the menu trigger), so a card with a select and a card
        // without one — the employer set header — compute the same height;
        // the select's intrinsic height was a measured 1px taller.
        className="h-6 w-[8.5rem] rounded border border-line-soft bg-surface px-1.5 text-[11px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong disabled:opacity-50"
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
 * This is the worklist form of what used to be `ApplicationCard`: the same
 * state machine over a full-width, fixed-skeleton line. At `sm` and up
 * everything a row can say lives on ONE line — company · role slot on the
 * left, then the meta cluster (chip, deadline, filed stamp, stage control,
 * Gmail link, actions) pinned right — so a row missing its role renders
 * exactly as tall as one that has it (the raggedness complaint was 8 of 29
 * live rows with no role line). The role slot never collapses: an absent role
 * prints {@link NO_ROLE_LABEL} in the dim rank, the same words the detail
 * sheet uses.
 *
 * Below `sm` the row is an explicit stack instead of a flex-wrap accident:
 * company + filed stamp on the first line, the role slot on the second, the
 * controls on the third, all anchored left. The wrap-based layout put the
 * chip/select cluster right-aligned on its own line — a dead gutter down the
 * left of every row — and any row carrying both a chip and a "quiet Nd" tag
 * wrapped its date onto a third line (measured: two row heights at 375px,
 * 69px and 96px, predicted exactly by chip+quiet). The stamp now lives on the
 * company line at phone width, so the controls line has a fixed population
 * and rows keep one shape.
 *
 * Three behaviours here are load-bearing:
 *
 *  1. **Removal is recoverable.** "Not an application" no longer fires
 *     anything: the row becomes a tombstone with an Undo for
 *     `UNDO_WINDOW_SECONDS`, and only when that expires does it POST the
 *     backend's *soft* dismiss (row + emails stay on disk, restorable).
 *     Undo is a cancelled timer — nothing was sent, so there is nothing to
 *     reverse and no training example written and then written over. The hard
 *     `DELETE` — which erases the row and its linked mail, and which no layer
 *     can undo — is a separate item behind an inline confirm.
 *  2. **The stage control is optimistic.** The chosen stage (and the row's
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
export function ApplicationRow({
  app,
  columnLabel,
  today = todayISO(),
  onOpenDetail,
  inSet = false,
  sameCompanyCount = 0,
  sameCompanyLabel,
  onFilterCompany,
  dragging = false,
  onDragStart,
  onDragEnd,
  folded = false,
  detailOpen = false,
  transport = liveBoardTransport,
}: {
  app: Application;
  /** The heading of the stage group this row is rendered in (see `board.ts`). */
  columnLabel?: string;
  /** Today's calendar day — the board threads one read of the clock down so
   *  every row's age tag and deadline state derive from the same instant
   *  (`useLocalToday`: UTC for the server pass, the reader's own day once
   *  mounted). The UTC default only stands in for a caller that renders a row
   *  outside the board; the board always passes its own. */
  today?: string;
  /** Opens the detail sheet (the mail behind this row). */
  onOpenDetail?: (app: Application) => void;
  /** True for a member of an employer set: the set's header already names the
   *  company, so the row leads with its role — repeating the employer three
   *  times under a header that says it is the duplication grouping removes.
   *  The accessible name keeps the company; only the visible lead changes. */
  inSet?: boolean;
  /**
   * How many OTHER applications share this company. A row is an application,
   * not a company — one employer can hold several — so this is a light
   * affordance, never a merge. The board passes 0 while its active filter
   * already IS this company, and for member rows inside an employer set
   * (the set's header owns the affordance there).
   */
  sameCompanyCount?: number;
  /** Stage-aware chip text ("+1 in interviewing") when the board groups by
   *  employer; without it the chip says "+N at {company}" (search view). */
  sameCompanyLabel?: string | null;
  /** Filters the board to this row's company (opens the set view). */
  onFilterCompany?: (company: string) => void;
  /** True while this row is the one being dragged. */
  dragging?: boolean;
  onDragStart?: (event: React.DragEvent<HTMLDivElement>) => void;
  onDragEnd?: () => void;
  /** True while the detail pane is DOCKED open beside the list (`xl+`, see
   *  #157): the row folds its stage select + Gmail slot — the 176px that buy
   *  the pane its width. Nothing is lost while folded: the pane carries its
   *  own working stage control and Gmail link for the open card, and every
   *  other row is one click from being that card. The board only sets this
   *  when the pane is actually docked, so no breakpoint prefix is needed. */
  folded?: boolean;
  /** True when this row is the card open in the detail pane — the "you are
   *  here" mark (border steps to `line-strong`, the same delta as hover),
   *  and the scroll target while ↑/↓ traverse the list. */
  detailOpen?: boolean;
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
  const rowRef = useRef<HTMLDivElement | null>(null);

  // The highlight follows ↑/↓: when this row becomes the open card, keep it
  // on screen. `nearest` scrolls the worklist the minimum distance and leaves
  // every other scroll context alone; instant on purpose — rapid traversal
  // must not queue smooth scrolls, and instant needs no reduced-motion fork.
  useEffect(() => {
    if (detailOpen) rowRef.current?.scrollIntoView({ block: "nearest" });
  }, [detailOpen]);

  // Server data caught up (to our value or to a different one): drop the
  // overlay and show the truth. Both arms matter — without the second, a
  // backend that answered with something else would leave the row asserting a
  // stage it is not at, forever.
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
      // success, so a change that did not move the row to another group (it
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-dashed border-line bg-surface-2/60 px-3 py-2">
        <p role="status" className="min-w-0 flex-1 text-xs leading-snug text-muted">
          {removalPendingMessage(app.company, secondsLeft ?? 0)}
        </p>
        <button
          ref={undoRef}
          type="button"
          onClick={() => {
            refocusTrigger.current = true;
            setSecondsLeft(null);
          }}
          className="inline-flex shrink-0 items-center gap-1.5 rounded border border-line px-2 py-1 text-xs text-strong transition-colors hover:border-line-strong hover:bg-surface"
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
      <div className="rounded-lg border border-dashed border-line-soft bg-surface-2/40 px-3 py-2">
        <p role="status" className="text-xs text-dim">
          {removed === "deleted" ? deletedMessage(app.company) : removedMessage(app.company)}
        </p>
      </div>
    );
  }

  const role = app.position.trim();

  const identity = inSet ? (
    // Set member: the role IS the line (the header names the employer). The
    // qualifier survives — a `closed` set's members must each say rejected /
    // withdrawn / ghosted for themselves.
    <span className="flex min-w-0 flex-1 items-baseline gap-2">
      {role ? (
        <span
          title={role}
          className="line-clamp-2 min-w-0 break-words text-sm leading-snug text-foreground underline-offset-2 group-hover/row:underline"
        >
          {role}
        </span>
      ) : (
        <span className="text-sm leading-snug text-dim underline-offset-2 group-hover/row:underline">
          {NO_ROLE_LABEL}
        </span>
      )}
      {qualifier && (
        <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
          {qualifier}
        </span>
      )}
      <span className="ml-auto shrink-0 sm:hidden">
        <FiledStamp filed={filed} status={shownStatus} today={today} />
      </span>
    </span>
  ) : (
    <>
      <span className="flex min-w-0 items-baseline gap-2 text-sm font-medium text-strong sm:max-w-[16rem] sm:shrink-0">
        <span className="min-w-0 truncate underline-offset-2 group-hover/row:underline">
          {app.company}
        </span>
        {qualifier && (
          <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
            {qualifier}
          </span>
        )}
        {/* Below `sm` the filed stamp rides the company line (pinned right),
            which is what keeps the controls line one fixed shape — see the
            component note. Above `sm` its twin renders in the meta cluster. */}
        <span className="ml-auto shrink-0 font-normal sm:hidden">
          <FiledStamp filed={filed} status={shownStatus} today={today} />
        </span>
      </span>
      {/* The role WRAPS (two lines) instead of ellipsizing when it must: a job
          title's discriminating part is its tail — "…, AWS Data Services -
          2026" — which is exactly what a one-line truncate eats. At the row's
          full-width measure this almost never fires; `title` stays the floor,
          not the fix. An absent role prints the slot's honest placeholder so
          the line's shape never changes. */}
      {role ? (
        <span
          title={role}
          className="line-clamp-2 min-w-0 break-words text-[13px] leading-snug text-foreground"
        >
          {role}
        </span>
      ) : (
        <span className="text-[13px] leading-snug text-dim">{NO_ROLE_LABEL}</span>
      )}
    </>
  );

  return (
    <div
      ref={rowRef}
      aria-busy={busy !== null}
      draggable={onDragStart ? true : undefined}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      data-dragging={dragging || undefined}
      data-detail-open={detailOpen || undefined}
      className={`board-row group/row relative flex flex-col gap-y-1.5 rounded-lg border ${
        detailOpen ? "border-line-strong" : "border-line-soft"
      } bg-surface-2 py-2 pl-3 pr-2 transition-colors hover:border-line-strong sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3 sm:pr-1.5`}
      style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
    >
      {/* A row is an APPLICATION: company anchors it, the role discriminates
          it (four Amazon rows must read as four different lines), and the
          block itself opens the mail behind the row. */}
      {onOpenDetail ? (
        <button
          type="button"
          onClick={() => onOpenDetail(app)}
          aria-label={`Open ${app.company}${role ? ` — ${role}` : ""}`}
          className="flex min-w-0 flex-col gap-y-0.5 text-left sm:flex-1 sm:basis-56 sm:flex-row sm:items-baseline sm:gap-x-2.5"
        >
          {identity}
        </button>
      ) : (
        <div className="flex min-w-0 flex-col gap-y-0.5 sm:flex-1 sm:basis-56 sm:flex-row sm:items-baseline sm:gap-x-2.5">
          {identity}
        </div>
      )}

      {/* The meta cluster — every fact in one fixed order, pinned right from
          `sm` up so the eye can read a column of rows like a table. The order
          puts the variable-width pieces (chip, deadline, stamp) BEFORE the
          fixed-width tail (select · Gmail slot · menu): with the tail constant,
          every select shares one x position, which the old order — stamp and a
          conditional link after the select — measurably broke (78px spread).
          `max-w-full` (never `shrink-0`): an unshrinkable cluster refuses the
          wrap and pushes the row past a phone's viewport instead of taking its
          own line. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 sm:ml-auto sm:max-w-full sm:justify-end">
        {sameCompanyCount > 0 && onFilterCompany ? (
          <SameCompanyChip
            company={app.company}
            count={sameCompanyCount}
            label={sameCompanyLabel ?? undefined}
            onFilter={onFilterCompany}
          />
        ) : null}
        {/* Renders nothing unless the row carries a due_at — the tag never
            prompts, and never guesses (see DeadlineTag). */}
        <DeadlineTag dueAt={app.due_at} today={today} />
        {busy !== null || optimistic ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-dim motion-reduce:animate-none" aria-hidden />
        ) : null}
        <span className="hidden sm:inline">
          <FiledStamp filed={filed} status={shownStatus} today={today} />
        </span>
        {/* The fold (#157): while the detail pane is docked open, the select
            and the Gmail slot leave — the pane holds both for the open card,
            and their 176px (select 136 + slot 24 + two gaps) is exactly the
            width the pane borrows from every row. Unmounted, not hidden:
            the select is controlled and prop-driven, so it re-mounts on the
            exact value it left. */}
        {!folded ? (
          <StageSelect
            id={app.id}
            company={app.company}
            value={shownStatus}
            disabled={busy !== null}
            busy={busy === "status"}
            onChange={onStatusChange}
          />
        ) : null}
        {!folded ? (
          app.url ? (
            <a
              href={app.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open the mail behind ${app.company} in Gmail`}
              title="open in gmail"
              className="grid h-6 w-6 place-items-center rounded text-dim transition-colors hover:bg-surface hover:text-strong"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : (
            // A rowed-up board needs this slot even when there is no mail to
            // open — a hole here shifts the select column 32px on manual rows.
            // Phone rows drop it: the controls line is left-anchored, not a
            // column, and the space matters more.
            <span className="hidden h-6 w-6 sm:block" aria-hidden="true" />
          )
        ) : null}
        <RowActionsMenu
          label={`Row actions for ${app.company}${role ? ` — ${role}` : ""}`}
          items={menuItems}
          disabled={busy !== null}
          triggerRef={triggerRef}
        />
      </div>

      {busy === "status" || optimistic ? (
        <p role="status" className="basis-full text-[11px] text-dim">
          {busy === "status" ? `moving to ${shownStatus}…` : "board updating…"}
        </p>
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
          className="basis-full rounded border border-reject/50 bg-reject/10 p-2"
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
          className="flex basis-full items-start gap-1.5 rounded border border-reject/50 bg-reject/10 px-2 py-1.5 text-xs leading-snug text-strong"
        >
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject-ink" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}
