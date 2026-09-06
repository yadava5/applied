"use client";

import { ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";

import { DeadlineTag, SameCompanyChip } from "@/components/dashboard/CardMeta";
import { QUIET_AFTER_DAYS, daysBetween } from "@/lib/dashboard/age";
import { filedAt, shortDate } from "@/lib/dashboard/dates";
import type { BoardColumn } from "@/lib/dashboard/board";
import type { Application } from "@/lib/dashboard/summary";
import { cn } from "@/lib/utils";

/**
 * One employer's applications within one stage, folded into a single card
 * that opens inline — the answer to "four cards all saying Amazon".
 *
 * This is a VIEW over the same rows the flat list would render (see
 * `lib/dashboard/employerGroups.ts` for why it must never become a merge).
 * The header claims nothing a member could contradict:
 *
 *   - it names the employer and counts the applications — the count in mono
 *     because it is a figure, the word in the product voice;
 *   - it shows the filing SPAN (oldest – newest), since one date would be
 *     some member's date passed off as everyone's;
 *   - it carries the set's most urgent deadline, because a deadline folded
 *     out of sight until a click is a deadline missed — and the quiet tag of
 *     its oldest member, the two signals a collapsed card may not swallow;
 *   - it never shows a status qualifier or a stage control: members of a
 *     `closed` set can be rejected AND withdrawn, and bulk stage moves are
 *     not offered. Every member row keeps its own select, menu and mail.
 *
 * Collapsed, the card wears `.board-stack` — two card edges peeking out
 * beneath it — so "several live here" is legible before any copy is read.
 * Open, the members render as full rows on a hairline rail; the deck look
 * goes away because the children are the deck.
 *
 * The cross-stage chip (rendered only when the employer holds rows in OTHER
 * stages) keeps the company-filter affordance: expansion answers "what are
 * the N here", the chip answers "everything at this employer, wherever it
 * stands". Its accessible name stays `Show all applications at {company}`.
 */
export function EmployerSetRow({
  company,
  items,
  column,
  today,
  open,
  onToggle,
  setKey,
  chip,
  onFilterCompany,
  children,
}: {
  company: string;
  /** The member applications, in the stage group's own order. */
  items: Application[];
  /** The stage group this set lives in — its label, key and accent. */
  column: BoardColumn;
  /** The board's one clock read, threaded down (`useLocalToday`). */
  today: string;
  open: boolean;
  onToggle: () => void;
  /** `${stage}:${company}` — this set's identity, and the board's focus
   *  anchor for a row that regrouped into it while collapsed (#425). */
  setKey: string;
  /** Cross-stage affordance, prebuilt by the board: how many of this
   *  employer's applications sit outside this stage, and where. */
  chip: { count: number; label: string } | null;
  onFilterCompany?: (company: string) => void;
  /** The member rows (`BoardCell`-wrapped), rendered only while open. */
  children: ReactNode;
}) {
  const listId = useId();

  // The span and the quiet signal derive from the members' own filed dates —
  // the same fields their FiledStamps render, so header and rows cannot
  // disagree. String compare is safe: `filedAt` yields ISO dates/timestamps.
  const filedDates = items.map((app) => filedAt(app));
  const oldest = filedDates.reduce((a, b) => (b < a ? b : a));
  const newest = filedDates.reduce((a, b) => (b > a ? b : a));
  const oldestAge = daysBetween(oldest, today);
  const quietAge =
    column.key === "applied" && oldestAge !== null && oldestAge >= QUIET_AFTER_DAYS
      ? oldestAge
      : null;

  // The set's most urgent deadline: the earliest due_at (an overdue one is by
  // definition earliest). `DeadlineTag` derives the state and the phrase.
  const urgentDue = items
    .map((app) => app.due_at)
    .filter((d): d is string => d != null)
    .sort()[0];

  const span = (
    <span className="tabular font-mono text-[10px] text-dim">
      {shortDate(oldest) === shortDate(newest)
        ? shortDate(newest)
        : `${shortDate(oldest)} – ${shortDate(newest)}`}
      {quietAge !== null ? (
        <span
          className="text-review"
          title={`oldest filed ${quietAge} days ago and still at applied`}
        >
          {" "}
          · quiet {quietAge}d
        </span>
      ) : null}
    </span>
  );

  const showChip = chip !== null && onFilterCompany !== undefined;
  // The urgent tag exists so a COLLAPSED card cannot swallow a deadline; open,
  // the owning member row shows its own and a second copy would double-claim.
  const showUrgent = !open && urgentDue !== undefined;
  const hasPhoneMeta = showChip || showUrgent;

  return (
    <div>
      {/* Same skeleton as ApplicationRow — stacked lines below `sm`, one line
          above — so a set header and a single row stay the same height. */}
      <div
        className={cn(
          "board-row group/row relative flex flex-col gap-y-1.5 rounded-lg border border-line-soft bg-surface-2 py-2 pl-3 pr-2 transition-colors hover:border-line-strong sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-3",
          !open && "board-stack",
        )}
        style={{ borderLeft: `2px solid color-mix(in oklab, ${column.color} 55%, transparent)` }}
      >
        <button
          type="button"
          // The focus anchor for a row that regrouped INTO this set (#425).
          // A corrected row landing in a COLLAPSED set has no `status-<id>`
          // select to return the reader to, because it is not rendered; the
          // board falls back to this header, which is where the row now is.
          // A data attribute rather than an id: a company name is arbitrary
          // text and would need escaping to survive `getElementById`.
          data-set-toggle={setKey}
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-label={`${company} — ${items.length} applications`}
          onClick={onToggle}
          className="flex min-w-0 flex-col gap-y-0.5 text-left sm:flex-1 sm:basis-56 sm:flex-row sm:items-baseline sm:gap-x-2.5"
        >
          <span className="flex min-w-0 items-baseline gap-2 text-sm font-medium text-strong sm:max-w-[16rem] sm:shrink-0">
            <span className="min-w-0 truncate underline-offset-2 group-hover/row:underline">
              {company}
            </span>
            {/* Below `sm` the span rides the company line; above it lives in
                the meta cluster like every row's date does. */}
            <span className="ml-auto shrink-0 font-normal sm:hidden">{span}</span>
          </span>
          {/* The role slot: for a set, the discriminator is the count. */}
          <span className="flex min-w-0 items-center gap-1.5 text-[13px] leading-snug text-muted">
            <span className="tabular font-mono text-xs text-strong">{items.length}</span>
            applications
            <ChevronRight
              className={cn(
                "h-3.5 w-3.5 shrink-0 text-dim transition-transform motion-reduce:transition-none",
                open && "rotate-90",
              )}
              aria-hidden
            />
          </span>
        </button>

        <div
          className={cn(
            hasPhoneMeta ? "flex" : "hidden sm:flex",
            "flex-wrap items-center gap-x-2 gap-y-1 sm:ml-auto sm:max-w-full sm:justify-end",
          )}
        >
          {showChip ? (
            <SameCompanyChip
              company={company}
              count={chip.count}
              label={chip.label}
              onFilter={onFilterCompany}
            />
          ) : null}
          {showUrgent ? <DeadlineTag dueAt={urgentDue} today={today} /> : null}
          <span className="hidden sm:inline">{span}</span>
        </div>
      </div>

      {open ? (
        <ul id={listId} className="ml-1 mt-1.5 space-y-1.5 border-l border-line-soft pl-3">
          {children}
        </ul>
      ) : null}
    </div>
  );
}
