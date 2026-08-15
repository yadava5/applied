import { classifyWithRules } from "@/lib/demo/rulesLayer";

import { VERDICT_EMAIL } from "./verdictEmailData";

/**
 * Variant C's hero artifact: the single row that just changed.
 *
 * C leads with the outcome at its smallest — one application whose stage the
 * classifier just moved — and then the descent shows the machinery: the mail
 * that did it (`VerdictEmail`, the same Larkspur email), the decision that
 * ships, the retention promise. The full board appears after the argument.
 *
 * The right side of the arrow is DERIVED, not typed: `classifyWithRules` runs
 * on the email's whole body here, at render, and the chip prints whatever it
 * returns — the same call the descent shows the visitor live. Server-safe:
 * pure inputs, no dates, no state.
 */

/** The classifier's category vocabulary → the board's stage vocabulary. */
const STAGE_OF_CATEGORY: Record<string, string> = {
  rejection: "rejected",
  offer: "offered",
  interview: "interviewing",
  assessment: "assessment",
  applied: "applied",
};

export function ChangedRow() {
  const verdict = classifyWithRules(
    VERDICT_EMAIL.subject,
    VERDICT_EMAIL.body,
    VERDICT_EMAIL.senderEmail,
  );
  const stage = STAGE_OF_CATEGORY[verdict.category] ?? verdict.category;

  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4">
        <div className="min-w-0">
          <p className="truncate text-base font-medium text-strong">{VERDICT_EMAIL.company}</p>
          <p className="truncate text-sm text-muted">{VERDICT_EMAIL.role}</p>
        </div>
        <p className="flex shrink-0 items-center gap-2.5" aria-label={`stage moved: applied to ${stage}`}>
          <span className="label-caps text-dim line-through decoration-line-strong">applied</span>
          <span aria-hidden className="text-dim">
            →
          </span>
          <span className="label-caps rounded-md border border-reject/50 px-2 py-1 text-reject-ink">
            {stage}
          </span>
        </p>
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line-soft px-5 py-2.5">
        {/* The stage chip above IS computed live; the MOVE on this page is the
            window act writing the verdict through its own fixture transport
            (MarketingBoard). So the caption claims the classifier's work, not
            the classifier's hand on this particular row. */}
        <span className="inline-flex items-center gap-2 text-xs text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          what the classifier does — replayed on fixture data
        </span>
        <span aria-hidden className="text-xs text-dim">
          the email that did it ↓
        </span>
      </figcaption>
    </figure>
  );
}
