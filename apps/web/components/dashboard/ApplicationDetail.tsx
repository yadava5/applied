"use client";

import {
  ArrowDown,
  ArrowUp,
  CalendarClock,
  ExternalLink,
  Loader2,
  TriangleAlert,
  X,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { AUTO_FILE_GATE, GateMeter } from "@/components/viz/GateMeter";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { filedAt, longDate, shortDate } from "@/lib/dashboard/dates";
import {
  DEADLINE_ADD_LABEL,
  DEADLINE_CHANGE_LABEL,
  DEADLINE_CLEAR_FAILED,
  DEADLINE_CLEAR_HINT,
  DEADLINE_CLEAR_LABEL,
  DEADLINE_PICK_FIRST,
  DEADLINE_SAVE_FAILED,
  DEADLINE_SAVE_LABEL,
  dueDayISO,
  dueInfo,
  duePhrase,
  dueSourceLabel,
  type DueState,
} from "@/lib/dashboard/deadline";
import {
  readApplicationDetail,
  type ApplicationDetail as DetailData,
  type SplitCandidate,
} from "@/lib/dashboard/detail";
import { CANCEL_LABEL, statusChangeFailure } from "@/lib/dashboard/rowActions";
import { statusOptions, statusSelectValue } from "@/lib/dashboard/status";
import { STAGES, stageOf, type Application } from "@/lib/dashboard/summary";
import { liveBoardTransport, type BoardTransport } from "@/lib/dashboard/transport";
import { CATEGORY_META } from "@/lib/gmail/types";

/**
 * The application detail — the mail behind a card, in two geometries.
 *
 * `GET /api/applications/{id}` existed and was called by nothing: there was no
 * way to open a card and see which of four Amazon roles it is, or the thread
 * of verdicts that filed and advanced it. This view is that answer, and it is
 * the product's identity moment inside the app: each message renders as one
 * step of a verdict trail — category dot, confidence, subject, sender, date —
 * the same vocabulary as the landing's decision trace, because it is the same
 * fact ("your inbox already holds the verdict") shown on the user's own row.
 *
 * The two geometries (#157, the accepted design — do not reopen):
 *
 *   - **Docked pane at `xl+`** (`docked` non-false): the detail sits BESIDE
 *     the worklist, inside the board's own row, and the board stays readable
 *     and usable while it is open. The rejected alternative was the modal
 *     overlay this replaced — an overlay's exclusivity contract was itself
 *     the complaint (opening one card cost sight of every other). The rows
 *     fold their stage select + Gmail slot while the pane is open (see
 *     `ApplicationRow`), which is how the pane buys its width.
 *   - **Sheet below `xl`** (`docked={false}`): the `Dialog` sheet, unchanged
 *     — at those widths there is no board left to keep sight of.
 *
 * The traversal header — "N of M · ↑ ↓" — is what makes the pane a work
 * surface rather than a popup: moving between cards never costs a close and
 * a reopen, and ↑/↓ work from the keyboard while the detail is open (in both
 * geometries; the guard below keeps them off selects, inputs and menus).
 *
 * The stage control here is real (same PATCH + optimistic/rollback contract as
 * the card), not a display; every Gmail link opens the actual conversation.
 */

type LoadState = { kind: "loading" } | { kind: "error" } | { kind: "ready"; detail: DetailData };

function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

/** The sheet's deadline phrase ink, by state — measured in both themes (red
 * 6.89:1 dark / 6.47:1 light on the sheet surface; amber 8.87:1 / 5.02:1). */
const DUE_TEXT_CLASS: Record<DueState, string> = {
  overdue: "text-reject-ink",
  soon: "text-review",
  ahead: "text-muted",
};

function TrailMessage({
  message,
  isLast,
}: {
  message: DetailData["messages"][number];
  isLast: boolean;
}) {
  const meta = message.category
    ? (CATEGORY_META[message.category] ?? { label: message.category, dot: "bg-dim" })
    : null;
  const sender = message.sender_name || message.sender_email || "unknown sender";
  return (
    <li className="relative pl-6">
      {/* The trail: a hairline spine with one category-hued node per message. */}
      {!isLast ? (
        <span aria-hidden className="absolute left-[3px] top-4 h-full w-px bg-line-soft" />
      ) : null}
      <span
        aria-hidden
        className={`absolute left-0 top-1.5 h-[7px] w-[7px] rounded-full ${meta?.dot ?? "bg-dim"}`}
      />
      <div className="flex items-baseline justify-between gap-3">
        <p className="min-w-0 truncate text-sm font-medium text-strong">
          {message.subject || "(no subject)"}
        </p>
        <span className="tabular shrink-0 font-mono text-[10px] text-dim">
          {message.received_at ? shortDate(message.received_at) : ""}
        </span>
      </div>
      <p className="truncate text-xs text-muted">{sender}</p>
      {meta ? (
        // The verdict, in the DecisionTrace's vocabulary: category, then the
        // confidence drawn against the 0.85 gate — green cleared it, amber
        // waited for a human. The number stays as the accessible value.
        <p className="mt-0.5 flex items-center gap-2 text-[11px] text-dim">
          {meta.label}
          {typeof message.confidence === "number" ? (
            <>
              <GateMeter confidence={message.confidence} className="w-12" />
              <span
                className="tabular font-mono text-[10px]"
                style={{
                  color: message.confidence >= AUTO_FILE_GATE ? "var(--green)" : "var(--amber)",
                }}
              >
                {pct(message.confidence)}
              </span>
            </>
          ) : null}
        </p>
      ) : null}
      {message.snippet ? (
        <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-dim">{message.snippet}</p>
      ) : null}
      {message.gmail_link ? (
        <a
          href={message.gmail_link}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          open in gmail
        </a>
      ) : null}
    </li>
  );
}

/**
 * "This looks like N applications — split?" for a merged row.
 *
 * Renders only when the detail response carries two or more `split_candidates`
 * (see `lib/dashboard/detail.ts`), which the backend derives by re-clustering
 * this row's own stored mail. Empty is the normal case and offers nothing.
 *
 * The split itself takes NO request body: `POST /applications/{id}/split`
 * recomputes the clusters server-side from the same stored mail, so the client
 * cannot propose a division the server did not derive. The candidates here are
 * for display and consent only — they tell the user what they are agreeing to.
 */
function SplitPrompt({
  applicationId,
  company,
  candidates,
  onSplit,
}: {
  applicationId: number;
  company: string;
  candidates: SplitCandidate[];
  onSplit: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (candidates.length < 2) return null;

  async function split() {
    setBusy(true);
    setError(null);
    try {
      // No body on purpose — the endpoint re-derives the clusters from stored
      // mail. Sending `candidates` would imply the server honours them.
      const res = await fetch(`/api/applications/${applicationId}/split`, {
        method: "POST",
      });
      if (!res.ok) {
        setError("Couldn't split this row — it is unchanged.");
        setBusy(false);
        return;
      }
      onSplit();
    } catch {
      setError("Couldn't split this row — it is unchanged.");
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-review/40 bg-surface-2 p-3">
      <p className="text-sm text-strong">
        This looks like {candidates.length} applications at {company} — split them?
      </p>
      <ul className="mt-2 space-y-1">
        {candidates.map((c, i) => (
          // Keyed on the first message id, not the role: a role is nullable on
          // the wire and two clusters at one employer can share one.
          <li key={c.message_ids[0] ?? `candidate-${i}`} className="text-xs text-muted">
            {company} · {c.role ?? "no role named in this mail"}
            {c.retains_row ? " · keeps your edits" : null}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-dim">
        each becomes its own card · your edits stay on this one
      </p>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void split()}
          disabled={busy}
          className="rounded border border-review/50 px-2 py-1 text-xs font-medium text-strong transition-colors hover:border-review disabled:opacity-50"
        >
          {busy ? "splitting…" : `Split into ${candidates.length}`}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-reject-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function ApplicationDetail({
  app,
  onClose,
  docked = false,
  position = null,
  onTraverse,
  transport = liveBoardTransport,
}: {
  /** The card being inspected; `null` keeps the detail closed. */
  app: Application | null;
  onClose: () => void;
  /**
   * How the open detail sits at `xl+`, where the board docks it beside the
   * worklist: `"locked"` fills the shell's viewport pane and scrolls inside
   * itself, `"flow"` rides sticky on a page that scrolls (the /demo twin).
   * `false` — every width below `xl` — keeps the modal sheet. JS-driven by
   * the board's own media query, not CSS, because the two geometries differ
   * in behaviour (focus, Escape, scroll lock), not just position.
   */
  docked?: false | "locked" | "flow";
  /** Where the open card sits in the board's visible order (0-based), for
   *  the "N of M" traversal header. Null when the card fell out of the
   *  current view (a filter typed while it was open) — the header then hides
   *  rather than report a position in a list that no longer holds the card. */
  position?: { index: number; count: number } | null;
  /** Move the detail to the previous (-1) / next (+1) visible card. */
  onTraverse?: (delta: -1 | 1) => void;
  /** How reads/mutations reach data — the live proxy by default, fixtures on /demo. */
  transport?: BoardTransport;
}) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [stageBusy, setStageBusy] = useState(false);
  const [stageError, setStageError] = useState<string | null>(null);
  /** The stage the user just picked here, shown before the server confirms. */
  const [optimistic, setOptimistic] = useState<string | null>(null);
  /** The deadline a write here just committed, shown until the row prop
   *  catches up (`app` is the board's snapshot and survives `router.refresh`). */
  const [dueOverride, setDueOverride] = useState<{
    at: string | null;
    source: string | null;
  } | null>(null);
  const [dueEditing, setDueEditing] = useState(false);
  /** The date input's draft, `YYYY-MM-DD`. */
  const [dueDraft, setDueDraft] = useState("");
  const [dueBusy, setDueBusy] = useState<null | "save" | "clear">(null);
  const [dueError, setDueError] = useState<string | null>(null);

  /** The day this sheet measures deadlines against — the reader's own once
   *  mounted. Read here, above the early return, because it is a hook. */
  const today = useLocalToday();

  const load = useCallback(
    async (id: number) => {
      setState({ kind: "loading" });
      const res = await transport.detail(id);
      if (!res.ok) {
        setState({ kind: "error" });
        return;
      }
      setState({ kind: "ready", detail: readApplicationDetail(res.body) });
    },
    [transport],
  );

  useEffect(() => {
    if (!app) return;
    // Deferred off the effect body (the house rule — see BetaBanner): the
    // reset + fetch kick off in a macrotask, never a synchronous setState.
    const id = window.setTimeout(() => {
      setOptimistic(null);
      setStageError(null);
      setDueOverride(null);
      setDueEditing(false);
      setDueError(null);
      setDueBusy(null);
      void load(app.id);
    }, 0);
    return () => window.clearTimeout(id);
  }, [app, load]);

  const reduceMotion = useReducedMotion();
  const dockedRef = useRef<HTMLElement | null>(null);
  /** The docked pane's scroller — reset to the top on every traversal, so
   *  card N+1 never opens mid-way down card N's trail. */
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (app) scrollRef.current?.scrollTo({ top: 0 });
  }, [app]);

  // ↑/↓ traverse the board's visible order while the detail is open — from
  // anywhere, because focus legitimately rests in the worklist while the pane
  // is up. Document-level, with two guards: `defaultPrevented` (a control
  // that already answered the key — the row menu's roving focus — must win)
  // and a closest() over the elements that own their own arrows. Escape
  // closes the DOCKED pane here; the sheet's Dialog owns Escape below `xl`,
  // and two closers on one key would double-fire.
  useEffect(() => {
    if (!app) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        if (docked) onClose();
        return;
      }
      if ((event.key !== "ArrowUp" && event.key !== "ArrowDown") || !onTraverse) return;
      const target = event.target instanceof Element ? event.target : null;
      if (
        target?.closest("input, select, textarea, [contenteditable], [role='menu'], [role='listbox']")
      ) {
        return;
      }
      event.preventDefault();
      onTraverse(event.key === "ArrowUp" ? -1 : 1);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [app, docked, onClose, onTraverse]);

  // Focus, docked: the pane is NOT a modal — no trap, no scroll lock, the
  // board stays live — but opening still moves focus in (so the traversal
  // keys answer at once) and closing hands it back, the same contract the
  // Dialog keeps for the sheet. The restore is conditional: if the user has
  // meanwhile focused something of their own (clicked another row's opener),
  // that focus is theirs and stays put; we only catch focus that fell to
  // <body> because the pane under it unmounted.
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const dockedOpen = docked !== false && app !== null;
  useEffect(() => {
    if (!dockedOpen) return;
    // Captured now: by cleanup time the ref has been detached (React clears
    // refs before running effect cleanups on unmount).
    const pane = dockedRef.current;
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    pane?.focus();
    return () => {
      const previous = restoreFocusRef.current;
      restoreFocusRef.current = null;
      const active = document.activeElement;
      if (active === null || active === document.body || pane?.contains(active)) {
        previous?.focus?.();
      }
    };
  }, [dockedOpen]);

  // The card last inspected, retained through close: the Dialog's exit
  // animation plays over real content instead of a blank panel (guarded
  // render-adjustment — the same pattern the board's optimistic overlay uses).
  const [shown, setShown] = useState<Application | null>(app);
  if (app && app !== shown) setShown(app);

  if (!shown) return null;
  const active = shown;

  const shownStatus = optimistic ?? active.status;
  const stage = STAGES.find((s) => s.key === stageOf(shownStatus))!;
  const role = active.position.trim();
  // The deadline the sheet asserts: the row's own, unless a write here already
  // moved it. Calendar-day math against the reader's own day, the same clock
  // rule as the board — so a date picked as "today" in the control below can
  // never come back from it reading as overdue.
  const due = dueOverride ?? { at: active.due_at ?? null, source: active.due_source ?? null };
  const dueState = dueInfo(due.at, today);
  const dueSource = dueSourceLabel(due.source);

  async function onStageChange(next: string) {
    if (next === shownStatus) return;
    setStageError(null);
    setOptimistic(next);
    setStageBusy(true);
    const result = await transport.changeStatus(active.id, next);
    setStageBusy(false);
    if (!result.ok) {
      setOptimistic(null);
      setStageError(statusChangeFailure(next, active.status, result.detail));
      return;
    }
    router.refresh();
  }

  // NOT optimistic, unlike the stage control: the sheet stays on the old value
  // with a busy state until the server answers, so the date it asserts is never
  // one the backend may still refuse. Cheap here — the sheet is already open
  // and the row is not travelling between columns.
  async function onDeadlineSave() {
    const iso = dueDayISO(dueDraft);
    if (!iso) {
      setDueError(DEADLINE_PICK_FIRST);
      return;
    }
    setDueError(null);
    setDueBusy("save");
    const result = await transport.setDeadline(active.id, iso);
    setDueBusy(null);
    if (!result.ok) {
      setDueError(
        result.detail ? `${DEADLINE_SAVE_FAILED} ${result.detail}` : DEADLINE_SAVE_FAILED,
      );
      return;
    }
    // Any write through the deadline endpoint is the user's word — the
    // backend marks it "user" and sync keeps its hands off it.
    setDueOverride({ at: iso, source: "user" });
    setDueEditing(false);
    router.refresh();
  }

  async function onDeadlineClear() {
    setDueError(null);
    setDueBusy("clear");
    const result = await transport.setDeadline(active.id, null);
    setDueBusy(null);
    if (!result.ok) {
      setDueError(
        result.detail ? `${DEADLINE_CLEAR_FAILED} ${result.detail}` : DEADLINE_CLEAR_FAILED,
      );
      return;
    }
    setDueOverride({ at: null, source: null });
    router.refresh();
  }

  /** Everything below the identity — facts, controls, trail — shared verbatim
   *  by the docked pane and the sheet, so the two geometries cannot drift. */
  const body = (
    <div className="space-y-5">
        {/* --- The row's own facts + the working stage control ------------- */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {/* Not isolated behind `memo` the way the card's control is (see
              `StageSelect` in ApplicationCard for why a controlled select can
              lose a choice made while a render is pending). It does not need to
              be: this sheet is unmounted until a visitor opens a card, which is
              long after the reader's-day swap has landed, so there is no
              systematic pending render for a selection here to race. Everything
              below `if (!shown) return null` is also past the hook region, so
              `onStageChange` cannot be a `useCallback` without restructuring
              the component — worth doing only if this control ever does start
              losing changes. */}
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor={`detail-status-${active.id}`}>
              Change stage for {active.company}
            </label>
            <select
              id={`detail-status-${active.id}`}
              value={statusSelectValue(shownStatus)}
              disabled={stageBusy}
              onChange={(e) => void onStageChange(e.target.value)}
              className="rounded border border-line bg-surface-2 px-2 py-1 text-xs outline-none transition-colors hover:border-line-strong focus:border-line-strong disabled:opacity-50"
              style={{ color: stage.color }}
            >
              {statusOptions(shownStatus).map((option) => (
                <option key={option.value} value={option.value} disabled={option.disabled}>
                  {option.label}
                </option>
              ))}
            </select>
            {stageBusy ? (
              <Loader2
                className="h-3.5 w-3.5 animate-spin text-dim motion-reduce:animate-none"
                aria-hidden
              />
            ) : null}
          </div>
          <span className="tabular font-mono text-[11px] text-dim">
            filed {longDate(filedAt(active))}
          </span>
          {active.url ? (
            <a
              href={active.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              open in gmail
            </a>
          ) : null}
        </div>

        {stageError ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 rounded border border-reject/50 bg-reject/10 px-2 py-1.5 text-xs leading-snug text-strong"
          >
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject-ink" aria-hidden />
            <span>{stageError}</span>
          </p>
        ) : null}

        {/* --- The deadline: set, change, clear — and whose claim it is ----- */}
        {/* Quick on purpose: one native date input (the OS picker on a phone),
            an explicit Save so a half-typed date is never PUT, and a Clear that
            is visibly reversible — the Add control it returns to sits in the
            same slot. The date is data (mono, state ink); the words around it
            are not (Atkinson, dim). */}
        <div data-testid="detail-deadline" className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <CalendarClock className="h-3.5 w-3.5 shrink-0 text-dim" aria-hidden />
          {dueEditing ? (
            <>
              <label className="sr-only" htmlFor={`deadline-date-${active.id}`}>
                Deadline date for {active.company}
              </label>
              <input
                id={`deadline-date-${active.id}`}
                type="date"
                value={dueDraft}
                onChange={(e) => setDueDraft(e.target.value)}
                disabled={dueBusy !== null}
                className="rounded border border-line bg-surface-2 px-2 py-1 font-mono text-xs text-strong outline-none transition-colors hover:border-line-strong focus:border-line-strong disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => void onDeadlineSave()}
                disabled={dueBusy !== null}
                className="rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
              >
                {dueBusy === "save" ? "saving…" : DEADLINE_SAVE_LABEL}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDueEditing(false);
                  setDueError(null);
                }}
                disabled={dueBusy !== null}
                className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
              >
                {CANCEL_LABEL}
              </button>
            </>
          ) : due.at && dueState ? (
            <>
              <span className={`tabular font-mono text-[11px] ${DUE_TEXT_CLASS[dueState.state]}`}>
                {duePhrase(dueState.daysLeft)} ·{" "}
                {dueState.state === "overdue" ? `was due ${shortDate(due.at)}` : shortDate(due.at)}
              </span>
              {/* Who set it — two different claims, stated quietly, never guessed. */}
              {dueSource ? <span className="text-[11px] text-dim">{dueSource}</span> : null}
              <button
                type="button"
                aria-label={`Change the deadline for ${active.company}`}
                onClick={() => {
                  setDueDraft(due.at ? due.at.slice(0, 10) : "");
                  setDueError(null);
                  setDueEditing(true);
                }}
                disabled={dueBusy !== null}
                className="rounded border border-line px-2 py-1 text-xs text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
              >
                {DEADLINE_CHANGE_LABEL}
              </button>
              <button
                type="button"
                aria-label={`Clear the deadline for ${active.company}`}
                title={DEADLINE_CLEAR_HINT}
                onClick={() => void onDeadlineClear()}
                disabled={dueBusy !== null}
                className="rounded border border-line px-2 py-1 text-xs text-foreground transition-colors hover:border-line-strong hover:text-strong disabled:opacity-50"
              >
                {dueBusy === "clear" ? "clearing…" : DEADLINE_CLEAR_LABEL}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => {
                  setDueDraft("");
                  setDueError(null);
                  setDueEditing(true);
                }}
                className="rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong"
              >
                {DEADLINE_ADD_LABEL}
              </button>
              <span className="text-[11px] text-dim">for assessment and take-home windows</span>
            </>
          )}
          {dueBusy !== null ? (
            <Loader2
              className="h-3.5 w-3.5 animate-spin text-dim motion-reduce:animate-none"
              aria-hidden
            />
          ) : null}
        </div>

        {dueError ? (
          <p
            role="alert"
            className="flex items-start gap-1.5 rounded border border-reject/50 bg-reject/10 px-2 py-1.5 text-xs leading-snug text-strong"
          >
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reject-ink" aria-hidden />
            <span>{dueError}</span>
          </p>
        ) : null}

        {active.notes ? (
          <p className="rounded-lg border border-line-soft bg-surface-2 p-3 text-[12px] leading-relaxed text-muted">
            {active.notes}
          </p>
        ) : null}

        {/* --- The verdict trail ------------------------------------------- */}
        <div>
          {/* The count rides the label once known: with the panel sized to
              its content, "· 1 message" says the short trail is complete
              rather than truncated. */}
          <p className="label-caps mb-3">
            the mail behind this card
            {state.kind === "ready" && state.detail.messages.length > 0
              ? ` · ${state.detail.messages.length} message${
                  state.detail.messages.length === 1 ? "" : "s"
                }`
              : ""}
          </p>
          {state.kind === "loading" ? (
            <p className="flex items-center gap-2 text-xs text-dim" role="status">
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
              loading the mail trail…
            </p>
          ) : state.kind === "error" ? (
            <div role="alert" className="rounded-lg border border-reject/40 bg-surface-2 p-3">
              <p className="text-xs text-strong">Couldn&apos;t load the mail behind this card.</p>
              <button
                type="button"
                onClick={() => void load(active.id)}
                className="mt-2 rounded border border-line px-2 py-1 text-xs font-medium text-foreground transition-colors hover:border-line-strong hover:text-strong"
              >
                try again
              </button>
            </div>
          ) : state.detail.messages.length === 0 ? (
            <p className="text-xs text-dim">no linked mail — this row was filed by hand</p>
          ) : (
            <ul className="space-y-4">
              {state.detail.messages.map((message, i) => (
                <TrailMessage
                  key={message.message_id}
                  message={message}
                  isLast={i === state.detail.messages.length - 1}
                />
              ))}
            </ul>
          )}
        </div>

        {state.kind === "ready" ? (
          <SplitPrompt
            applicationId={active.id}
            company={active.company}
            candidates={state.detail.splitCandidates}
            onSplit={() => {
              onClose();
              router.refresh();
            }}
          />
        ) : null}

        {active.source ? (
          <p className="border-t border-line-soft pt-3 text-[11px] text-dim">
            source · {active.source === "gmail" ? "filed automatically from gmail" : active.source}
          </p>
        ) : null}
      </div>
  );

  /** "N of M · ↑ ↓" — the traversal header. The count is data (mono,
   *  tabular); the arrows are the pane's primary controls and stay clickable
   *  even though the keys are the fast path. Clamped at the ends, matching
   *  the board's own clamp — no wrap-around surprises at row 1. */
  const traversal =
    position && onTraverse ? (
      <div className="flex items-center gap-1.5">
        <span className="tabular font-mono text-[11px] text-dim">
          {position.index + 1} of {position.count}
        </span>
        <span aria-hidden className="text-[11px] text-dim">
          ·
        </span>
        <button
          type="button"
          aria-label="Previous application"
          aria-keyshortcuts="ArrowUp"
          disabled={position.index <= 0}
          onClick={() => onTraverse(-1)}
          className="grid h-6 w-6 place-items-center rounded border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:opacity-40"
        >
          <ArrowUp className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          aria-label="Next application"
          aria-keyshortcuts="ArrowDown"
          disabled={position.index >= position.count - 1}
          onClick={() => onTraverse(1)}
          className="grid h-6 w-6 place-items-center rounded border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:opacity-40"
        >
          <ArrowDown className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    ) : null;

  if (docked) {
    // No `shown` retention here: the pane closes by unmounting, instantly —
    // an exit animation on a docked work surface would make the worklist
    // wait for its width back.
    if (app === null) return null;
    return (
      <motion.section
        ref={dockedRef}
        tabIndex={-1}
        data-testid="application-detail"
        aria-label={`${active.company} — the mail behind this card`}
        initial={reduceMotion ? false : { opacity: 0, x: 12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        className={`relative flex w-[24rem] shrink-0 flex-col overflow-hidden rounded-xl border border-line bg-surface outline-none ${
          docked === "locked"
            ? "min-h-0"
            : "sticky top-5 max-h-[calc(100dvh-2.5rem)] self-start"
        }`}
        // The same 2px stage accent the rows carry — the thread that ties the
        // pane to the row it opened from, across the gap between them.
        style={{ borderLeft: `2px solid color-mix(in oklab, ${stage.color} 55%, transparent)` }}
      >
        {/* Pinned chrome: position + traversal + close on one quiet row, then
            the identity — always in sight however deep the trail scrolls. */}
        <header className="shrink-0 border-b border-line-soft p-4 pb-3">
          <div className="flex items-center gap-1.5">
            {traversal}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close detail"
              className="ml-auto grid h-6 w-6 shrink-0 place-items-center rounded text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
          <h2 className="mt-2 break-words text-lg font-medium leading-snug text-strong">
            {active.company}
          </h2>
          <p className="mt-0.5 text-sm text-muted">{role || "role not captured yet"}</p>
        </header>
        {/* `relative`: this scroller is the containing block for the trail's
            absolute spine/nodes and the sr-only labels — the #149 family. */}
        <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-y-auto p-4">
          {body}
        </div>
      </motion.section>
    );
  }

  return (
    <Dialog
      open={app !== null}
      onClose={onClose}
      variant="sheet"
      title={active.company}
      description={role || "role not captured yet"}
    >
      <div data-testid="application-detail">
        {traversal ? <div className="mb-4">{traversal}</div> : null}
        {body}
      </div>
    </Dialog>
  );
}
