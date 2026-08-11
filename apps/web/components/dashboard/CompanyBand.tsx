"use client";

import { Layers, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { filedAt, shortDate } from "@/lib/dashboard/dates";
import { STAGES, stageOf, type Application } from "@/lib/dashboard/summary";

/**
 * The employer-as-a-set header. When the board is filtered to one company,
 * this band names the set the cards below now form: how many applications the
 * employer holds, how they sit across the stages, and the span they were filed
 * over. Four Amazon applications stop being four unrelated cards — the board
 * gathers them (the cards glide together via the shared layout animation) and
 * this band states what the set is.
 *
 * Facts are computed from the company's FULL row set (never the search-
 * narrowed one), so the band describes the employer even while a search
 * narrows what is visible. The clear control carries the same accessible name
 * the old filter chip did ("Stop filtering by …"), so the affordance's
 * contract is unchanged.
 */
export function CompanyBand({
  company,
  apps,
  statusOf,
  onClear,
}: {
  company: string;
  /** Every board row at this company, unfiltered. */
  apps: Application[];
  /** Status resolver — the board passes its optimistic-overlay-aware one. */
  statusOf: (app: Application) => string;
  onClear: () => void;
}) {
  const reduceMotion = useReducedMotion();

  const byStage = STAGES.map((stage) => ({
    stage,
    count: apps.filter((app) => stageOf(statusOf(app)) === stage.key).length,
  })).filter(({ count }) => count > 0);

  const filedDates = apps.map((app) => filedAt(app)).sort();
  const earliest = filedDates[0];
  const latest = filedDates[filedDates.length - 1];
  const span =
    apps.length > 1 && shortDate(earliest) !== shortDate(latest)
      ? `filed ${shortDate(earliest)} – ${shortDate(latest)}`
      : `filed ${shortDate(latest)}`;

  return (
    <motion.section
      aria-label={`All applications at ${company}`}
      data-testid="company-band"
      initial={reduceMotion ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line-strong bg-surface px-4 py-3"
    >
      <Layers className="h-4 w-4 shrink-0 text-muted" aria-hidden />
      <div className="min-w-0">
        <p className="truncate text-base font-medium leading-tight text-strong">{company}</p>
        <p className="font-mono text-[11px] text-dim">
          {apps.length} application{apps.length === 1 ? "" : "s"} · {span}
        </p>
      </div>
      <ul className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1">
        {byStage.map(({ stage, count }) => (
          <li key={stage.key} className="flex items-center gap-1.5 font-mono text-[11px]">
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: stage.color }}
            />
            <span className="text-muted">{stage.label}</span>
            <span className="tabular text-strong">{count}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onClear}
        aria-label={`Stop filtering by ${company}`}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-3 py-1 font-mono text-[11px] text-strong transition-colors hover:border-line-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        clear
        <X className="h-3 w-3" aria-hidden />
      </button>
    </motion.section>
  );
}
