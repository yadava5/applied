"use client";

import { Layers, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

/**
 * The board's filter state, said once: *filtered to {company}*, plus the
 * control that undoes it. A state indicator, not a header — deliberately
 * quieter than the cards underneath it, and one line.
 *
 * It used to be a header, and it restated three things the screen already
 * showed: the employer's application count, the spread across stages, and the
 * span they were filed over. You arrive here by clicking "+3 at Amazon" and
 * land on four cards you can count at a glance; every card states its own
 * stage and its own filed date; the spine states the distribution. So the band
 * was a second rendering of numbers already on screen — the exact defect this
 * dashboard has already removed twice, when the stat tiles, the classifier
 * strip, the distribution bars and the recent-activity feed all went (see the
 * page's own doc comment — "Nothing on the page restates either" — and the
 * `metrics-poster surfaces stay dead` e2e test that keeps them gone).
 *
 * Treat that as the rule for anything added here: if a number belongs in this
 * band, check first whether the cards or the spine are already saying it.
 * They usually are.
 *
 * Two things are NOT redundant and must survive:
 *   - The clear control, whose accessible name stays `Stop filtering by …`.
 *     That string is the affordance's contract — the chip, the specs and
 *     muscle memory all share it.
 *   - `partial`. The signed-in board is ONE bounded page of a possibly larger
 *     account, so a filtered view of it is a slice of a slice. Without the
 *     caveat, an employer's set silently implies an older application never
 *     existed. It says only that — the board's own `scopeNote` already states
 *     which rows are loaded, so this does not restate the numbers either.
 */
export function CompanyBand({
  company,
  partial = false,
  onClear,
}: {
  company: string;
  /** The board itself is truncated, so this employer's set is loaded rows only. */
  partial?: boolean;
  onClear: () => void;
}) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.section
      aria-label={`All applications at ${company}`}
      data-testid="company-band"
      initial={reduceMotion ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-line-soft bg-surface-2/60 px-3 py-1.5 text-sm"
    >
      <Layers className="h-3.5 w-3.5 shrink-0 text-dim" aria-hidden />
      {/* Siblings, not a wrapping paragraph: the company name is then the one
          element whose text IS the company, which is how the specs find it. */}
      <span className="shrink-0 text-muted">filtered to</span>
      <span className="min-w-0 truncate font-medium text-strong">{company}</span>
      {partial ? (
        <span className="min-w-0 text-xs text-dim">
          · this employer may hold rows this board has not loaded
        </span>
      ) : null}
      <button
        type="button"
        onClick={onClear}
        aria-label={`Stop filtering by ${company}`}
        className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        clear
        <X className="h-3 w-3" aria-hidden />
      </button>
    </motion.section>
  );
}
