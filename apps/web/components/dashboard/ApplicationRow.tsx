"use client";

import { ChevronDown, ExternalLink, Loader2, TriangleAlert, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useId, useRef, useState } from "react";

import { DeadlineTag, FiledStamp, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { notifySuccess } from "@/components/feedback/notify";
import { MailText } from "@/components/mail/MailText";
import { RowActionsMenu, type RowMenuItem } from "@/components/dashboard/RowActionsMenu";
import { safeText } from "@/lib/security/hostileText";
import { cardQualifier } from "@/lib/dashboard/board";
import { todayISO } from "@/lib/dashboard/age";
import { filedAt } from "@/lib/dashboard/dates";
import {
  CANCEL_LABEL,
  DELETED_TAIL,
  DELETE_CONFIRM_LABEL,
  DELETE_CONFIRM_QUESTION,
  DELETE_FAILED,
  DELETE_HINT,
  DELETE_LABEL,
  REMOVED_TAIL,
  REMOVE_FAILED,
  REMOVE_HINT,
  REMOVE_LABEL,
  REMOVE_STICKY_HINT,
  UNDO_LABEL,
  UNDO_WINDOW_SECONDS,
  removalPendingTail,
  rowName,
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
 * One of the two tombstones' sentences: the row's name, then what happened
 * to it.
 *
 * WHY THIS IS ITS OWN COMPONENT AND NOT AN INLINE FRAGMENT (#424). The name is
 * mail-derived — a synced row's `company` is whatever an ATS put in a display
 * name — so it has to go through `MailText`, which means it needs an element
 * of its own; `rowActions.ts` explains why the composed one-string form could
 * not be neutralised and why isolation does not stand in for the wrapper. It
 * is EXPORTED and hook-free for the same reason `MailText` is: it is the piece
 * of this row that `tests/unit/helpers/renderTsx.mjs` can render by calling it,
 * so the tombstone — a `useState` branch a static render can never reach — is
 * proven by execution rather than by a source scan.
 *
 * `tail` is written by `rowActions.ts` and never here, so the two outcomes go
 * on reading differently ("not deleted" versus "deleted permanently").
 */
export function RowOutcome({ company, tail }: { company: string; tail: string }) {
  return (
    <>
      <MailText value={rowName(company)} />
      {tail}
    </>
  );
}

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
 *
 * WHY THE IN-FLIGHT STATE IS `aria-disabled` AND NOT `disabled` (#425). The
 * control the user is standing on is the control the write locks, and a
 * FOCUSED element that becomes `disabled` is blurred by the browser to
 * `<body>` — measured at t=3ms after the change, on every row, and it never
 * comes back: the next Tab starts from the top of the document. That is not
 * the row being reparented into another stage group (a same-section
 * correction, `rejected → ghosted`, loses focus identically while the node
 * stays in the document; the unmount, when there is one, lands 1.4s later and
 * is downstream of a blur that has already happened).
 *
 * `aria-disabled` states the same thing to assistive tech WITHOUT taking the
 * element out of the focus order or out of the accessibility tree, so the
 * keyboard user keeps their place and can hear the `aria-busy` they are
 * waiting on. The lock is then enforced in the handler instead of by the UA:
 * see `onChange` below. Restoring focus after the fact is NOT the repair —
 * it races the unmount and flickers; not blurring is.
 */
const StageSelect = memo(function StageSelect({
  id,
  company,
  value,
  locked,
  busy,
  onChange,
}: {
  id: number;
  company: string;
  /** The stage to SHOW — the optimistic one while a change is in flight. */
  value: string;
  /**
   * A write is in flight and this control may not accept another one. NAMED
   * for the state, not for the attribute: it deliberately does not reach the
   * DOM's `disabled` (see the note above), so calling it `disabled` would
   * invite exactly the one-word change that reinstates the defect.
   */
  locked: boolean;
  busy: boolean;
  /** Must be referentially stable; see the note above. */
  onChange: (next: string) => void;
}) {
  return (
    <>
      {/* `safeText`, not `MailText`: this is an accessible NAME. The company
          is drawn visibly a few nodes away and carries the hidden-character
          flag there, and stuffing a second warning into every control's
          announced name would bury the name the label exists to give — the
          trade `lib/security/hostileText.ts` states for exactly these slots. */}
      <label className="sr-only" htmlFor={`status-${id}`}>
        Change stage for {safeText(company)}
      </label>
      {/* Still a NATIVE controlled <select> — the memo contract above, the
          keyboard/AT semantics and the enum options are all unchanged. Only
          the FACE moved off the OS widget: `.select-control` (globals.css)
          strips `appearance`, the chevron is drawn here (ours, so it matches
          the board's other glyphs and dims with the control's in-flight state
          via `peer` — `peer-aria-disabled`, because `peer-disabled` reads the
          DOM property this control no longer sets), and
          engines that support stylable pickers dress the open list too. The
          wrapper now carries the geometry the old comment measured, and the
          reasons hold verbatim: `w-[8.5rem]`, not max-w, because an
          intrinsic-width select is as wide as its current value, and 17 rows
          put the board's main control on four different x positions (a 78px
          spread, measured) — fixed width + the fixed-width tail after it
          (see the meta cluster) is what makes the selects a column; `h-6`
          matches the cluster's other controls (the Gmail slot, the menu
          trigger), so a card with a select and a card without one — the
          employer set header — compute the same height (the OS-drawn
          select's intrinsic height was a measured 1px taller). The select
          itself fills the wrapper, so the box the cluster lays out is
          byte-identical to before. */}
      <span className="relative inline-flex h-6 w-[8.5rem]">
        <select
          id={`status-${id}`}
          value={statusSelectValue(value)}
          aria-disabled={locked}
          aria-busy={busy}
          // IGNORED, not prevented. `aria-disabled` leaves the control
          // operable, so a change CAN still be dispatched mid-write; dropping
          // it here is what makes the lock real. The `value` prop does not
          // move, and React restores a controlled <select>'s DOM selection
          // after a change its handler did not act on
          // (`restoreControlledState`), so the control snaps back to the stage
          // in flight without needing a re-render. The guard lives HERE rather
          // than in the row's `onStatusChange` because that callback's
          // referential stability is the memo contract above — reading the
          // in-flight state there would churn the one prop that must not
          // churn.
          onChange={(e) => {
            if (locked) return;
            onChange(e.target.value);
          }}
          className="select-control peer h-full w-full rounded border border-line-soft bg-surface pl-1.5 pr-5 text-[11px] text-muted outline-none transition-colors hover:border-line focus:border-line-strong aria-disabled:opacity-50"
        >
          {statusOptions(value).map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-1 top-1/2 h-3 w-3 -translate-y-1/2 text-dim peer-aria-disabled:opacity-50"
        />
      </span>
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
  revealOnOpen = true,
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
  /** True while the detail pane is DOCKED open beside the list (`lg+`, see
   *  #157): the row's stage select + Gmail slot yield ONLY where the
   *  worklist cannot hold them (#173) — a container query against the
   *  worklist's own measure, under 32rem the pair folds and its 176px is
   *  what buys the pane its width. Nothing is lost while folded: the pane
   *  carries its own working stage control and Gmail link for the open card,
   *  drag-to-stage still works on every row, and every other row is one
   *  click from being that card. The board only sets this when the pane is
   *  actually docked, so no breakpoint prefix is needed. */
  folded?: boolean;
  /** True when this row is the card open in the detail pane — the "you are
   *  here" mark (border steps to `line-strong`, the same delta as hover),
   *  and the scroll target while ↑/↓ traverse the list. */
  detailOpen?: boolean;
  /** Whether becoming the open card may move the reader's viewport. True for
   *  an open the reader asked for; false for one the PAGE seeded (see the
   *  effect below — `nearest` reaches the document, not just the worklist). */
  revealOnOpen?: boolean;
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
  // on screen. `nearest` scrolls the minimum distance; instant on purpose —
  // rapid traversal must not queue smooth scrolls, and instant needs no
  // reduced-motion fork.
  //
  // ONLY FOR AN OPEN THE READER ASKED FOR (`revealOnOpen`). The comment here
  // used to claim `nearest` "leaves every other scroll context alone", and it
  // does not: it walks every scroll container up to the document. In the app
  // the worklist is its own scroller so the page barely moves. On the landing
  // the board sits in an `overflow-clip` stage — not a scroller — so the
  // document is the only container, and a pane the PAGE seeded yanked the
  // reader back into the act from wherever they had scrolled to. Measured on
  // a production build: a jump to y=5800 came back to 3219 about 1.6s later,
  // which is the seed waiting out the row's travel and then scrolling.
  //
  // It is the same rule the seed already follows for focus — docked only, no
  // focus theft. A viewport is not the page's to move either.
  useEffect(() => {
    if (detailOpen && revealOnOpen) rowRef.current?.scrollIntoView({ block: "nearest" });
  }, [detailOpen, revealOnOpen]);

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
      // Success is otherwise silent — on the list view the row stays put and
      // only the select's face changes. The key is deliberately target-free
      // (#511): a triage burst across rows merges into ONE toast reading
      // "N applications updated" instead of stacking one per row. Failure
      // stays out of the toaster on purpose — this row already owns an
      // inline `role="alert"` for it, and a toast would say it twice.
      notifySuccess("application.status", `${safeText(app.company)} updated`, {
        countMessage: (n) => `${n} applications updated`,
      });
      router.refresh();
    },
    [app.company, app.id, app.status, optimisticTo, router, transport],
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
      hint: fromGmail ? REMOVE_STICKY_HINT : REMOVE_HINT,
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
          <RowOutcome company={app.company} tail={removalPendingTail(secondsLeft ?? 0)} />
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
          <RowOutcome
            company={app.company}
            tail={removed === "deleted" ? DELETED_TAIL : REMOVED_TAIL}
          />
        </p>
      </div>
    );
  }

  /**
   * NEUTRALISED UNCONDITIONALLY, NOT ONLY WHEN THE SYNC OWNS IT (#424).
   * `position_source` is `"user"` for a typed title and NULL when extraction
   * produced it, so only the NULL rows are mail-derived — but branching on that
   * would leave a code path that renders `position` RAW, gated on a field that
   * is not a trust boundary. It is a sync-ownership flag the backend sets on
   * any write through `/role`, and the detail sheet sets it optimistically
   * before the server confirms. A raw render path reachable whenever that flag
   * says "user" is precisely the shape this fix exists to remove.
   *
   * What that costs is a marker on a self-typed role that genuinely carries an
   * invisible code point — a soft hyphen pasted out of a job posting, say. The
   * marker is TRUE in that case: there is an invisible character in the string.
   * A raw path is not true in any case. So the sanitiser applies whoever chose
   * the bytes, because the defect is about what the screen says, not about who
   * typed it.
   */
  const role = app.position.trim();

  const identity = inSet ? (
    // Set member: the role IS the line (the header names the employer). The
    // qualifier survives — a `closed` set's members must each say rejected /
    // withdrawn / ghosted for themselves.
    <span className="flex min-w-0 flex-1 items-baseline gap-2">
      {role ? (
        <span
          title={safeText(role)}
          className="line-clamp-2 min-w-0 break-words text-sm leading-snug text-foreground underline-offset-2 group-hover/row:underline"
        >
          <MailText value={role} />
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
          <MailText value={app.company} />
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
          title={safeText(role)}
          className="line-clamp-2 min-w-0 break-words text-[13px] leading-snug text-foreground"
        >
          <MailText value={role} />
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
          aria-label={`Open ${safeText(app.company)}${role ? ` — ${safeText(role)}` : ""}`}
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
        {/* The fold (#157/#173): while the detail pane is docked open, the
            select and the Gmail slot yield only where the worklist cannot
            hold them — their 176px (select 136 + slot 24 + two gaps) is what
            the pane borrows from every row at the dock floor. The sensor is
            the worklist's own measure (`@container` on the pane), never the
            viewport: at 32rem+ a row holds identity AND controls beside the
            open pane (the shell measures 588/748px at 1280/1440), while
            under it the identity would starve (409px at the owner's 1024),
            so the pair folds to the pane, which carries both for the open
            card. One wrapper for the pair, `contents` so the cluster's flex
            gap still reaches them; display, not unmount, so the fold cannot
            perturb the controlled select and both states share one tree
            shape (see BoardCell for why that matters). */}
        <span className={folded ? "hidden @min-[32rem]:contents" : "contents"}>
          <StageSelect
            id={app.id}
            company={app.company}
            value={shownStatus}
            locked={busy !== null}
            busy={busy === "status"}
            onChange={onStatusChange}
          />
          {app.url ? (
            <a
              href={app.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open the mail behind ${safeText(app.company)} in Gmail`}
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
          )}
        </span>
        <RowActionsMenu
          label={`Row actions for ${safeText(app.company)}${role ? ` — ${safeText(role)}` : ""}`}
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
          aria-label={`Confirm permanent delete of ${safeText(app.company)}`}
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
