"use client";

import { Layers } from "lucide-react";

import { QUIET_AFTER_DAYS, daysBetween } from "@/lib/dashboard/age";
import { shortDate } from "@/lib/dashboard/dates";
import { stageOf } from "@/lib/dashboard/summary";

/**
 * The small shared pieces of a board card's anatomy, used by both the
 * interactive `ApplicationCard` and the read-only demo/sample card so the two
 * can never drift apart visually.
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
  /** `todayISO()` — computed once per board render, threaded down. */
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
      className="mt-1.5 inline-flex items-center gap-1 rounded border border-line-soft px-1.5 py-0.5 font-mono text-[10px] text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
    >
      <Layers className="h-3 w-3" aria-hidden />+{count} at {company}
    </button>
  );
}
