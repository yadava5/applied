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
import { stageOf, type PulseRow } from "@/lib/dashboard/summary";

/**
 * The pulse — the four signals the board's rows actually carry, drawn instead
 * of restated. Everything on it is NEW information the subtitle and the board
 * don't already say:
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
 *     most urgent row BY NAME — the one thing on this surface a user should
 *     act on today. When nothing carries a deadline the cell says so and says
 *     where deadlines come from, instead of drawing an empty bar or inventing
 *     urgency: most boards, most of the time, honestly have nothing due;
 *   - **classifier** — how much of this pipeline the classifier built
 *     (source = "gmail" rows) and what it is holding under the 0.85 gate,
 *     deep-linked to the review queue.
 *
 * Two homes, one derivation:
 *
 *   - `layout="rail"` — the signed-in app. The pulse lives in the shell
 *     sidebar (`components/shell/Sidebar.tsx`), under the pipeline snapshot,
 *     as a narrow instrument column: each signal is a caps label, a drawn
 *     bar, and a ladder of dot–label–figure rungs — the same grammar as the
 *     snapshot's distribution bar above it, so the rail reads as one
 *     instrument rather than a strip folded to fit. The scope caveat prints
 *     once, as the column's last line, instead of once per cell. The rail is
 *     hidden below `md` and the pulse goes with it, deliberately: a phone
 *     dashboard leads with the worklist, and every signal's ground truth
 *     already inks the cards themselves (age tags, deadline tags, the review
 *     queue in the list). No display-none twin renders elsewhere.
 *   - `layout="strip"` — the /demo flow twin, which has no shell rail: the
 *     standalone horizontal four-cell band, unchanged.
 *
 * Content and testids are shared, so the derived signals have one
 * implementation to audit and `pulse-week` counts the same bars in both.
 *
 * Rows arrive as {@link PulseRow} — the projection of a board row this
 * component actually reads. The demo twin passes its full fixture rows
 * (structurally assignable); the shell rail passes the projected page it
 * loaded (`lib/shell/rail.ts`).
 *
 * This is a client component, and deliberately: the deadline cell counts what
 * is overdue, which is a claim about the READER's day, so its clock read has to
 * survive past the server render (`useLocalToday`). The alternative — keeping
 * it a server component and threading `today` down from the server — cannot
 * work, because the value threaded would be the UTC day, frozen at request
 * time, and never corrected once the browser could say what zone it is in.
 * Nothing here is interactive beyond the existing `Link`; the whole surface
 * still server-renders.
 *
 * Honesty rules: the board fetch is one bounded page, so when the loaded rows
 * are fewer than the account's total the row-derived signals say they describe
 * the newest N rather than pretending to describe everything. Ages/weeks are
 * calendar-day math on a day string — UTC for the server pass and the hydrating
 * pass, the reader's own day thereafter — so the pulse hydrates cleanly and
 * then tells the truth about time left. The micro-bars are `aria-hidden`
 * decoration over the numbers, animate in with a transform-only CSS entrance
 * (`.pulse-seg`, globals.css), and collapse to their final state under
 * `prefers-reduced-motion` — nothing here is gated on an animation.
 */

/** One rung of a rail ladder: dot, label, tabular figure on the right. */
function LadderRung({
  color,
  label,
  count,
  tone = "text-strong",
}: {
  color: string;
  label: string;
  count: number;
  tone?: string;
}) {
  return (
    <li className="flex items-center gap-2 text-xs">
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: color }}
      />
      <span className="text-muted">{label}</span>
      <span className={`tabular ml-auto font-mono text-[11px] ${tone}`}>{count}</span>
    </li>
  );
}

/** A thin proportional bar of coloured segments (zero segments not drawn). */
function SegmentBar({
  ariaLabel,
  total,
  segments,
}: {
  ariaLabel: string;
  total: number;
  segments: readonly (readonly [number, string])[];
}) {
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="mt-2.5 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
    >
      {segments
        .filter(([count]) => count > 0)
        .map(([count, color], i) => (
          <span
            key={color}
            className="pulse-seg-x h-full"
            style={{
              width: `${(count / total) * 100}%`,
              background: color,
              ["--i" as string]: i,
            }}
          />
        ))}
    </div>
  );
}

export function PipelinePulse({
  applications,
  total,
  needsReview,
  layout = "strip",
}: {
  /** The loaded rows — the same bounded page `PipelineBoard` renders. */
  applications: PulseRow[];
  /** The account's true total, from the counts-only summary endpoint. */
  total: number;
  /** Verdicts held under the gate for the user (0 when the queue is clear). */
  needsReview: number;
  /** `strip` — the standalone horizontal band (the /demo twin). `rail` — the
   *  shell sidebar's instrument column (see the doc block above). */
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

  /** Momentum bars — shared by both layouts; only the drawn height differs. */
  const momentumBars = (height: string) => (
    <div
      role="img"
      aria-label={`Applications filed per week, oldest first: ${weeks.join(", ")}`}
      className={`mt-2.5 flex ${height} items-end gap-1`}
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
  );

  const momentumAxis = (
    <div className="mt-1 flex justify-between font-mono text-[10px] text-dim" aria-hidden="true">
      <span>{MOMENTUM_WEEKS} wk ago</span>
      <span>now</span>
    </div>
  );

  /** The classifier's held-work line — the queue link or the all-clear. */
  const reviewLine =
    needsReview > 0 ? (
      <Link
        href="/dashboard#needs-classification"
        className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-review underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
      >
        <span className="tabular">{needsReview}</span> held under the 0.85 gate →
      </Link>
    ) : (
      <p className="mt-1 text-xs text-dim">queue clear · gate 0.85</p>
    );

  // --- the rail: the shell sidebar's instrument column ------------------------
  //
  // Sections ranked by urgency, not by the strip's reading order: on short
  // viewports the rail's middle scrolls, so whatever clips must be the least
  // actionable thing — deadlines (the one signal that names a to-do) sit
  // directly under the trend; provenance clips first. The column draws
  // exactly two bars (the snapshot's stage share above it, the amber ageing
  // share here): deadline counts are units, not proportions, and the
  // classifier fraction is already a number — bars there restated their own
  // ladders.
  if (layout === "rail") {
    return (
      <section aria-label="Pipeline pulse" data-testid="pipeline-pulse" className="flex flex-col">
        {/* momentum */}
        <div className="border-t border-line-soft py-3">
          <h2 className="label-caps">momentum · filed per wk</h2>
          {momentumBars("h-6")}
          {momentumAxis}
          <p className="tabular mt-1.5 text-xs text-muted">
            <span className="tabular text-strong">{recent}</span> last 4 wk{" "}
            <span aria-hidden="true">{arrow}</span> vs {prior} prior
          </p>
        </div>

        {/* deadlines */}
        <div className="border-t border-line-soft py-3">
          <h2 className="label-caps">deadlines · time left</h2>
          {due.total === 0 ? (
            <>
              {/* The state most users see most of the time, so it earns real
                  copy: never a nag, never a ladder drawn at zero. */}
              <p className="mt-2 text-xs text-dim">nothing due</p>
              <p className="mt-1 text-[11px] leading-snug text-dim">
                filed from mail when one is stated · or set one in a card&apos;s detail
              </p>
            </>
          ) : (
            <>
              <ul className="mt-2 space-y-1">
                <LadderRung
                  color="var(--red)"
                  label="overdue"
                  count={due.overdue}
                  tone={due.overdue > 0 ? "font-medium text-reject-ink" : "text-strong"}
                />
                <LadderRung color="var(--amber)" label={`due ≤${DUE_SOON_DAYS}d`} count={due.soon} />
                <LadderRung color="var(--stage-applied)" label="later" count={due.later} />
              </ul>
              {/* The one to act on today, by name — smallest days-left wins, so
                  an overdue row outranks everything until it is dealt with. */}
              {due.urgent ? (
                <p className="mt-2 text-xs text-muted">
                  next · {due.urgent.company}{" "}
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

        {/* ageing */}
        <div className="border-t border-line-soft py-3">
          <h2 className="label-caps">open · age since filed</h2>
          {openTotal === 0 ? (
            <p className="mt-2 text-xs text-dim">no open applications</p>
          ) : (
            <>
              <SegmentBar
                ariaLabel={`Open applications by age: ${ages.fresh} under a week, ${ages.waiting} one to two weeks, ${ages.quiet} quiet two weeks or more`}
                total={openTotal}
                segments={[
                  [ages.fresh, "var(--stage-applied)"],
                  [ages.waiting, "var(--text-dim)"],
                  [ages.quiet, "var(--amber)"],
                ]}
              />
              <ul className="mt-2 space-y-1">
                <LadderRung color="var(--stage-applied)" label="<1 wk" count={ages.fresh} />
                <LadderRung color="var(--text-dim)" label="1–2 wk" count={ages.waiting} />
                {/* "quiet" is the rail's one amber word when it is non-zero —
                    the same threshold that tags the individual cards. */}
                <LadderRung
                  color="var(--amber)"
                  label="quiet ≥2 wk"
                  count={ages.quiet}
                  tone={ages.quiet > 0 ? "text-review" : "text-strong"}
                />
              </ul>
            </>
          )}
        </div>

        {/* classifier */}
        <div className="border-t border-line-soft py-3">
          <h2 className="label-caps">classifier</h2>
          <p className="tabular mt-2 text-xs text-muted">
            <span className="tabular text-strong">{autoFiled}</span> of {applications.length}{" "}
            auto-filed from mail
          </p>
          {reviewLine}
        </div>

        {/* The bounded-page caveat, once for the whole column — every signal
            above derives from the same loaded slice, so per-cell repetition
            bought nothing but noise at this width. */}
        {scopeNote ? (
          <p className="border-t border-line-soft py-3 text-[11px] leading-snug text-dim">
            signals derive from the {scopeNote} rows
          </p>
        ) : null}
      </section>
    );
  }

  // --- the strip: the /demo flow twin's horizontal band -----------------------
  return (
    <section
      aria-label="Pipeline pulse"
      data-testid="pipeline-pulse"
      className="grid overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-2 lg:grid-cols-4"
    >
      {/* --- momentum -------------------------------------------------------- */}
      <div className="border-b border-line-soft p-4 sm:border-r lg:border-b-0">
        <h2 className="label-caps">momentum · filed per wk</h2>
        {momentumBars("h-9")}
        {momentumAxis}
        <p className="tabular mt-2 text-xs text-muted">
          <span className="tabular text-strong">{recent}</span> last 4 wk{" "}
          <span aria-hidden="true">{arrow}</span> vs {prior} prior
          {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
        </p>
      </div>

      {/* --- ageing ---------------------------------------------------------- */}
      <div className="border-b border-line-soft p-4 lg:border-b-0 lg:border-r">
        <h2 className="label-caps">open · age since filed</h2>
        {openTotal === 0 ? (
          <p className="mt-3 text-xs text-dim">no open applications</p>
        ) : (
          <>
            <SegmentBar
              ariaLabel={`Open applications by age: ${ages.fresh} under a week, ${ages.waiting} one to two weeks, ${ages.quiet} quiet two weeks or more`}
              total={openTotal}
              segments={[
                [ages.fresh, "var(--stage-applied)"],
                [ages.waiting, "var(--text-dim)"],
                [ages.quiet, "var(--amber)"],
              ]}
            />
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
      <div className="border-b border-line-soft p-4 sm:border-b-0 sm:border-r">
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
            <SegmentBar
              ariaLabel={`Deadlines on loaded rows: ${due.overdue} overdue, ${due.soon} due within ${DUE_SOON_DAYS} days, ${due.later} later`}
              total={due.total}
              segments={[
                [due.overdue, "var(--red)"],
                [due.soon, "var(--amber)"],
                [due.later, "var(--stage-applied)"],
              ]}
            />
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
      <div className="p-4">
        <h2 className="label-caps">classifier</h2>
        <SegmentBar
          ariaLabel={`${autoFiled} of ${applications.length} loaded rows were filed automatically from mail`}
          total={Math.max(applications.length, 1)}
          segments={[[autoFiled, "var(--viz-setfit)"]]}
        />
        {/* The scope note is not optional here just because the denominator is
            the loaded count: "120 of 200" reads as the whole account to anyone
            who hasn't done the arithmetic, and this cell's own aria-label has
            always said "of 200 LOADED rows". The visible line agrees with the
            label, and with the other two cells. */}
        <p className="tabular mt-2 text-xs text-muted">
          <span className="tabular text-strong">{autoFiled}</span> of {applications.length}{" "}
          auto-filed from mail
          {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
        </p>
        {reviewLine}
      </div>
    </section>
  );
}
