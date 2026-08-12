"use client";

import Link from "next/link";

import {
  MOMENTUM_WEEKS,
  bucketAges,
  daysBetween,
  momentumDelta,
  weeklyCounts,
} from "@/lib/dashboard/age";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { filedAt } from "@/lib/dashboard/dates";
import { DUE_SOON_DAYS, deadlinePulse, duePhrase } from "@/lib/dashboard/deadline";
import { stageOf, type Application } from "@/lib/dashboard/summary";

/**
 * The pulse strip — the four signals the rows actually carry, drawn instead
 * of restated. Sits under the SyncBar; everything on it is NEW information the
 * subtitle and the board don't already say:
 *
 *   - **momentum** — applications filed per week (8 weeks of bars) and the
 *     last-4-weeks-vs-prior-4 delta, from the same one derivation
 *     (`lib/dashboard/age.ts`) so the arrow can never contradict the bars;
 *   - **ageing** — the open (applied + interviewing) rows bucketed by days
 *     since filed; the ≥{@link QUIET_AFTER_DAYS}-day share is the amber
 *     "quiet" signal, the same threshold that tags individual cards;
 *   - **deadlines** — the rows carrying a `due_at`, bucketed
 *     overdue / due ≤{@link DUE_SOON_DAYS}d / later by the same derivation
 *     that inks the card tags (`lib/dashboard/deadline.ts`), plus the single
 *     most urgent row BY NAME — the one thing on this strip a user should act
 *     on today. When nothing carries a deadline the cell says so and says
 *     where deadlines come from, instead of drawing an empty bar or inventing
 *     urgency: most boards, most of the time, honestly have nothing due;
 *   - **classifier** — how much of this pipeline the classifier built
 *     (source = "gmail" rows) and what it is holding under the 0.85 gate,
 *     deep-linked to the review queue.
 *
 * This is a client component, and deliberately: the deadline cell counts what
 * is overdue, which is a claim about the READER's day, so its clock read has to
 * survive past the server render (`useLocalToday`). The alternative — keeping
 * it a server component and threading `today` down from `app/(app)/dashboard/
 * page.tsx` — cannot work, because that page is itself a server component: the
 * value it threaded would be the UTC day, frozen at request time, and would
 * never be corrected once the browser could say what zone it is in. Wrapping it
 * in a client shell just to inject the prop would pull this module into the
 * client bundle anyway (it already is one, via `DemoDashboard`), so the shell
 * would buy nothing but indirection. Nothing here is interactive beyond the
 * existing `Link`; the whole surface still server-renders.
 *
 * Honesty rules: the board fetch is one bounded page, so when the loaded rows
 * are fewer than the account's total the row-derived cells say they describe
 * the newest N rather than pretending to describe everything. Ages/weeks are
 * calendar-day math on a day string — UTC for the server pass and the hydrating
 * pass, the reader's own day thereafter — so the strip hydrates cleanly and
 * then tells the truth about time left. The micro-bars are `aria-hidden` decoration over the
 * numbers, animate in with a transform-only CSS entrance (`.pulse-seg`,
 * globals.css), and collapse to their final state under
 * `prefers-reduced-motion` — nothing here is gated on an animation.
 */
export function PipelinePulse({
  applications,
  total,
  needsReview,
  layout = "strip",
}: {
  /** The board's loaded rows — the same page `PipelineBoard` renders. */
  applications: Application[];
  /** The account's true total, from the counts-only summary endpoint. */
  total: number;
  /** Verdicts held under the gate for the user (0 when the queue is clear). */
  needsReview: number;
  /** `strip` — the standalone horizontal band (the /demo twin). `rail` — the
   *  same four cells stacked for the board's spine, framed by the spine
   *  itself rather than their own border. Content and testids are identical
   *  in both, so the derived signals have one implementation to audit. */
  layout?: "strip" | "rail";
}) {
  const today = useLocalToday();
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

  // --- deadlines (rows carrying a due_at; no due date, no claim) -------------
  const due = deadlinePulse(applications, today);

  // --- classifier -----------------------------------------------------------
  const autoFiled = applications.filter((app) => app.source === "gmail").length;

  const scopeNote = complete ? null : `newest ${applications.length} of ${total}`;

  const rail = layout === "rail";
  /** Per-cell frame: the strip draws its own borders; the rail cells stack
   *  with hairline separators and lean on the spine's framing. */
  const cell = {
    momentum: rail ? "py-3 first:pt-0" : "border-b border-line-soft p-4 sm:border-r lg:border-b-0",
    ageing: rail ? "border-t border-line-soft py-3" : "border-b border-line-soft p-4 lg:border-b-0 lg:border-r",
    deadlines: rail ? "border-t border-line-soft py-3" : "border-b border-line-soft p-4 sm:border-b-0 sm:border-r",
    classifier: rail ? "border-t border-line-soft py-3 last:pb-0" : "p-4",
  };

  return (
    <section
      aria-label="Pipeline pulse"
      data-testid="pipeline-pulse"
      className={
        rail
          ? "flex flex-col"
          : "grid overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-2 lg:grid-cols-4"
      }
    >
      {/* --- momentum -------------------------------------------------------- */}
      <div className={cell.momentum}>
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
      <div className={cell.ageing}>
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

      {/* --- deadlines ------------------------------------------------------- */}
      <div className={cell.deadlines}>
        <h2 className="label-caps">deadlines · time left</h2>
        {due.total === 0 ? (
          <>
            {/* The state most users see most of the time, so it earns real
                copy: what the cell measures, and where a deadline comes from —
                never a nag, never a bar drawn at zero. */}
            <p className="mt-3 text-xs text-dim">nothing due — no loaded row carries a deadline</p>
            <p className="mt-1 text-[11px] leading-snug text-dim">
              filed from mail when one is stated · or set one in a card&apos;s detail
            </p>
          </>
        ) : (
          <>
            <div
              role="img"
              aria-label={`Deadlines on loaded rows: ${due.overdue} overdue, ${due.soon} due within ${DUE_SOON_DAYS} days, ${due.later} later`}
              className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
            >
              {(
                [
                  [due.overdue, "var(--red)"],
                  [due.soon, "var(--amber)"],
                  [due.later, "var(--stage-applied)"],
                ] as const
              )
                .filter(([count]) => count > 0)
                .map(([count, color], i) => (
                  <span
                    key={color}
                    className="pulse-seg-x h-full"
                    style={{
                      width: `${(count / due.total) * 100}%`,
                      background: color,
                      ["--i" as string]: i,
                    }}
                  />
                ))}
            </div>
            <p className="tabular mt-2 text-xs text-muted">
              {/* "N overdue" turns red as a unit — a red word beside a white
                  digit would put the emphasis on the wrong half. */}
              <span className={due.overdue > 0 ? "font-medium text-reject-ink" : ""}>
                <span className={due.overdue > 0 ? "tabular" : "tabular text-strong"}>
                  {due.overdue}
                </span>{" "}
                overdue
              </span>{" "}
              · <span className="tabular">{due.soon}</span> due ≤{DUE_SOON_DAYS}d ·{" "}
              <span className="tabular">{due.later}</span> later
              {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
            </p>
            {/* The one to act on today, by name — smallest days-left wins, so an
                overdue row outranks everything until it is dealt with. */}
            {due.urgent ? (
              <p className="mt-1 text-xs text-muted">
                most urgent · {due.urgent.company}{" "}
                <span
                  className={`tabular font-mono text-[10px] ${
                    due.urgent.daysLeft < 0 ? "text-reject-ink" : "text-review"
                  }`}
                >
                  {duePhrase(due.urgent.daysLeft)}
                </span>
              </p>
            ) : null}
          </>
        )}
      </div>

      {/* --- classifier ------------------------------------------------------ */}
      <div className={cell.classifier}>
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
