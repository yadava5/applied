import Link from "next/link";

import {
  MOMENTUM_WEEKS,
  bucketAges,
  daysBetween,
  momentumDelta,
  todayISO,
  weeklyCounts,
} from "@/lib/dashboard/age";
import { filedAt } from "@/lib/dashboard/dates";
import { stageOf, type Application } from "@/lib/dashboard/summary";

/**
 * The pulse strip — the three signals the rows actually carry, drawn instead
 * of restated. Sits under the SyncBar; everything on it is NEW information the
 * subtitle and the board don't already say:
 *
 *   - **momentum** — applications filed per week (8 weeks of bars) and the
 *     last-4-weeks-vs-prior-4 delta, from the same one derivation
 *     (`lib/dashboard/age.ts`) so the arrow can never contradict the bars;
 *   - **ageing** — the open (applied + interviewing) rows bucketed by days
 *     since filed; the ≥{@link QUIET_AFTER_DAYS}-day share is the amber
 *     "quiet" signal, the same threshold that tags individual cards;
 *   - **classifier** — how much of this pipeline the classifier built
 *     (source = "gmail" rows) and what it is holding under the 0.85 gate,
 *     deep-linked to the review queue.
 *
 * Honesty rules: the board fetch is one bounded page, so when the loaded rows
 * are fewer than the account's total the row-derived cells say they describe
 * the newest N rather than pretending to describe everything. Ages/weeks are
 * calendar-day math in UTC on both server and client (`age.ts`), so the strip
 * hydrates cleanly. The micro-bars are `aria-hidden` decoration over the
 * numbers, animate in with a transform-only CSS entrance (`.pulse-seg`,
 * globals.css), and collapse to their final state under
 * `prefers-reduced-motion` — nothing here is gated on an animation.
 */
export function PipelinePulse({
  applications,
  total,
  needsReview,
}: {
  /** The board's loaded rows — the same page `PipelineBoard` renders. */
  applications: Application[];
  /** The account's true total, from the counts-only summary endpoint. */
  total: number;
  /** Verdicts held under the gate for the user (0 when the queue is clear). */
  needsReview: number;
}) {
  const today = todayISO();
  /** True when the single board page holds every row the account has. */
  const complete = applications.length >= total;

  // --- momentum -------------------------------------------------------------
  const weeks = weeklyCounts(
    applications.map((app) => filedAt(app)),
    today,
  );
  const peak = Math.max(...weeks, 1);
  const { recent, prior } = momentumDelta(weeks);
  const arrow = recent > prior ? "↑" : recent < prior ? "↓" : "→";

  // --- ageing (open rows only — a closed row's age answers nothing) ---------
  const openAges = applications
    .filter((app) => {
      const stage = stageOf(app.status);
      return stage === "applied" || stage === "interviewing";
    })
    .map((app) => daysBetween(filedAt(app), today));
  const ages = bucketAges(openAges);
  const openTotal = ages.fresh + ages.waiting + ages.quiet;

  // --- classifier -----------------------------------------------------------
  const autoFiled = applications.filter((app) => app.source === "gmail").length;

  const scopeNote = complete ? null : `newest ${applications.length} of ${total}`;

  return (
    <section
      aria-label="Pipeline pulse"
      data-testid="pipeline-pulse"
      className="grid overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-3"
    >
      {/* --- momentum -------------------------------------------------------- */}
      <div className="border-b border-line-soft p-4 sm:border-b-0 sm:border-r">
        <h2 className="label-caps">momentum · filed per wk</h2>
        <div
          role="img"
          aria-label={`Applications filed per week, oldest first: ${weeks.join(", ")}`}
          className="mt-3 flex h-9 items-end gap-1"
        >
          {weeks.map((count, i) => (
            <span
              key={i}
              data-testid="pulse-week"
              title={`${count} filed`}
              className="pulse-seg min-w-0 flex-1 rounded-sm"
              style={{
                height: count > 0 ? `${Math.max(18, (count / peak) * 100)}%` : "2px",
                background: count > 0 ? "var(--stage-applied)" : "var(--line-strong)",
                ["--i" as string]: i,
              }}
            />
          ))}
        </div>
        <div className="mt-1 flex justify-between font-mono text-[10px] text-dim" aria-hidden="true">
          <span>{MOMENTUM_WEEKS} wk ago</span>
          <span>now</span>
        </div>
        <p className="tabular mt-2 text-xs text-muted">
          <span className="tabular text-strong">{recent}</span> last 4 wk{" "}
          <span aria-hidden="true">{arrow}</span> vs {prior} prior
          {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
        </p>
      </div>

      {/* --- ageing ---------------------------------------------------------- */}
      <div className="border-b border-line-soft p-4 sm:border-b-0 sm:border-r">
        <h2 className="label-caps">open · age since filed</h2>
        {openTotal === 0 ? (
          <p className="mt-3 text-xs text-dim">no open applications</p>
        ) : (
          <>
            <div
              role="img"
              aria-label={`Open applications by age: ${ages.fresh} under a week, ${ages.waiting} one to two weeks, ${ages.quiet} quiet two weeks or more`}
              className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
            >
              {(
                [
                  [ages.fresh, "var(--stage-applied)"],
                  [ages.waiting, "var(--text-dim)"],
                  [ages.quiet, "var(--amber)"],
                ] as const
              )
                .filter(([count]) => count > 0)
                .map(([count, color], i) => (
                  <span
                    key={color}
                    className="pulse-seg-x h-full"
                    style={{
                      width: `${(count / openTotal) * 100}%`,
                      background: color,
                      ["--i" as string]: i,
                    }}
                  />
                ))}
            </div>
            <p className="tabular mt-2 text-xs text-muted">
              <span className="tabular text-strong">{ages.fresh}</span> &lt;1 wk ·{" "}
              <span className="tabular">{ages.waiting}</span> 1–2 wk ·{" "}
              <span className={ages.quiet > 0 ? "text-review" : ""}>
                <span className="tabular">{ages.quiet}</span> quiet ≥2 wk
              </span>
              {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
            </p>
          </>
        )}
      </div>

      {/* --- classifier ------------------------------------------------------ */}
      <div className="p-4">
        <h2 className="label-caps">classifier</h2>
        <div
          role="img"
          aria-label={`${autoFiled} of ${applications.length} loaded rows were filed automatically from mail`}
          className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
        >
          {autoFiled > 0 ? (
            <span
              className="pulse-seg-x h-full"
              style={{
                width: `${applications.length > 0 ? (autoFiled / applications.length) * 100 : 0}%`,
                background: "var(--viz-setfit)",
                ["--i" as string]: 0,
              }}
            />
          ) : null}
        </div>
        {/* The scope note is not optional here just because the denominator is
            the loaded count: "120 of 200" reads as the whole account to anyone
            who hasn't done the arithmetic, and this cell's own aria-label has
            always said "of 200 LOADED rows". The visible line now agrees with
            the label, and with the other two cells. */}
        <p className="tabular mt-2 text-xs text-muted">
          <span className="tabular text-strong">{autoFiled}</span> of {applications.length}{" "}
          auto-filed from mail
          {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
        </p>
        {needsReview > 0 ? (
          <Link
            href="/dashboard#needs-classification"
            className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-review underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
          >
            <span className="tabular">{needsReview}</span> held under the 0.85 gate →
          </Link>
        ) : (
          <p className="mt-1 text-xs text-dim">queue clear · gate 0.85</p>
        )}
      </div>
    </section>
  );
}
