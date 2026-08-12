"use client";

import { CalendarClock, Layers } from "lucide-react";

import { QUIET_AFTER_DAYS, daysBetween } from "@/lib/dashboard/age";
import { longDate, shortDate } from "@/lib/dashboard/dates";
import { dueInfo, duePhrase, type DueState } from "@/lib/dashboard/deadline";
import { stageOf } from "@/lib/dashboard/summary";

/**
 * The small shared pieces of a worklist row's anatomy, used by both the
 * interactive `ApplicationRow` and the read-only demo/sample row so the two
 * can never drift apart visually. Every piece is inline (no top margins):
 * the row's meta cluster owns the spacing, so a tag can never push a row
 * taller than its neighbours.
 */

/**
 * The card's date stamp, now carrying the ageing signal: an applied-stage row
 * ≥ {@link QUIET_AFTER_DAYS} days old with no stage movement gets an amber
 * "quiet Nd" tag — the same threshold the pulse strip counts, so the board and
 * the strip always agree on what "quiet" means. Other stages show the date
 * alone: their filed date says nothing honest about how stale the *contact*
 * is, so no claim is made.
 */
export function FiledStamp({
  filed,
  status,
  today,
}: {
  /** ISO date/timestamp the card treats as its filed moment (`filedAt`). */
  filed: string;
  status: string;
  /** `useLocalToday()` — computed once per board render, threaded down. */
  today: string;
}) {
  const age = daysBetween(filed, today);
  const quiet = stageOf(status) === "applied" && age !== null && age >= QUIET_AFTER_DAYS;
  return (
    <span className="tabular font-mono text-[10px] text-dim">
      {shortDate(filed)}
      {quiet ? (
        <span className="text-review" title={`filed ${age} days ago and still at applied`}>
          {" "}
          · quiet {age}d
        </span>
      ) : null}
    </span>
  );
}

/**
 * One chip anatomy — clock glyph · distance phrase · calendar day — with the
 * ink escalating by state, so the three states read apart at a glance while
 * occupying the same slot (a tag never jumps position as its day approaches):
 *
 *   - **ahead** — dim mono, no frame: present, calm, and honest about it;
 *   - **soon** (≤ {@link DUE_SOON_DAYS} days) — amber ink + border, the same
 *     needs-attention amber as the review queue;
 *   - **overdue** — the red wash, with the phrase in `text-strong`: the only
 *     wash a live card can carry, the same stop-vocabulary as the delete
 *     confirm. Measured (both themes) rather than eyeballed: strong-on-wash
 *     15.06:1 dark / 13.67:1 light; amber 8.51:1 dark / 4.57:1 light — the
 *     10% amber wash was DROPPED from the soon state because amber-on-wash
 *     measured 4.01:1 in light, under AA.
 */
const DUE_TAG_CLASS: Record<DueState, string> = {
  overdue: "border-reject/50 bg-reject/10 text-strong",
  soon: "border-review/50 text-review",
  ahead: "border-transparent text-dim",
};

/**
 * The card's deadline — rendered ONLY when the row carries a `due_at`. A row
 * without one shows nothing at all: no placeholder, no prompt, no inferred
 * urgency (`dueInfo` returning `null` is the whole gate). The words are the
 * CVD-safe channel — "overdue" / "due in Nd" carry the state without the hue.
 */
export function DeadlineTag({
  dueAt,
  today,
}: {
  /** The row's `due_at` — ISO datetime, or null/undefined for "no deadline". */
  dueAt: string | null | undefined;
  /** `useLocalToday()` — the board's one clock read, threaded down. */
  today: string;
}) {
  const due = dueInfo(dueAt, today);
  if (!due) return null;
  const day = shortDate(dueAt);
  return (
    <p
      data-testid="deadline-tag"
      data-due-state={due.state}
      title={`deadline ${longDate(dueAt)}`}
      className={`tabular inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] leading-snug ${DUE_TAG_CLASS[due.state]}`}
    >
      <CalendarClock
        className={`h-3 w-3 shrink-0 ${due.state === "overdue" ? "text-reject-ink" : ""}`}
        aria-hidden
      />
      <span>
        {duePhrase(due.daysLeft)} · {due.state === "overdue" ? `was due ${day}` : day}
      </span>
    </p>
  );
}

/**
 * The same-company affordance: "+N at Amazon" opens the employer's set view
 * (the board filters to the company and the `CompanyBand` names the set).
 * The accessible name stays "Show all applications at …" — the contract the
 * board's tests and muscle memory rely on. The caller suppresses it while the
 * active filter already IS this company (rendering "3 more at Amazon" inside
 * Amazon's own set view was the bug).
 */
export function SameCompanyChip({
  company,
  count,
  onFilter,
}: {
  company: string;
  /** How many OTHER applications share the company. */
  count: number;
  onFilter: (company: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onFilter(company)}
      aria-label={`Show all applications at ${company}`}
      className="inline-flex items-center gap-1 rounded border border-line-soft px-1.5 py-0.5 text-[11px] font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
    >
      <Layers className="h-3 w-3" aria-hidden />+{count} at {company}
    </button>
  );
}
