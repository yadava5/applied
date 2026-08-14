"use client";

import { CalendarClock, CalendarDays, Mail, MoonStar, PenLine } from "lucide-react";
import { X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { pulseFilterLabel, type PulseFilter } from "@/lib/dashboard/pulseFilter";

/**
 * The pulse filter's state, said once — `CompanyBand`'s twin for the filters
 * the pulse detail panel applies (#156/#158/#159): *filtered to filed Aug 5*,
 * plus the control that undoes it. Same discipline as its sibling: a state
 * indicator, not a header, and it restates nothing the cards already say —
 * the rows below each carry their own filed stamp, stage and source affordance,
 * and the board's own status line counts the matches.
 *
 * The clear control keeps the `Stop filtering by …` accessible-name family —
 * the affordance's contract, shared with the company band, the specs and
 * muscle memory.
 */
export function PulseFilterBand({
  filter,
  onClear,
}: {
  filter: PulseFilter;
  onClear: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const label = pulseFilterLabel(filter);
  const Icon =
    filter.kind === "day"
      ? CalendarDays
      : filter.kind === "quiet"
        ? MoonStar
        : // The two deadline filters share one glyph: both narrow to what is
          // DUE, and the label beside it is what says which slice.
          filter.kind === "due" || filter.kind === "dueIn"
          ? CalendarClock
          : filter.source === "mail"
            ? Mail
            : PenLine;

  return (
    <motion.section
      aria-label={`Applications ${label}`}
      data-testid="pulse-filter-band"
      initial={reduceMotion ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-line-soft bg-surface-2/60 px-3 py-1.5 text-sm"
    >
      <Icon className="h-3.5 w-3.5 shrink-0 text-dim" aria-hidden />
      <span className="shrink-0 text-muted">filtered to</span>
      <span className="min-w-0 truncate font-medium text-strong">{label}</span>
      <button
        type="button"
        onClick={onClear}
        aria-label={`Stop filtering by ${label}`}
        className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        clear
        <X className="h-3 w-3" aria-hidden />
      </button>
    </motion.section>
  );
}
