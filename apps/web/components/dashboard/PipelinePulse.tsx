"use client";

import Link from "next/link";

import { bucketAges, daysBetween, momentumDelta, weeklyCounts } from "@/lib/dashboard/age";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { filedAt } from "@/lib/dashboard/dates";
import { DUE_SOON_DAYS, deadlinePulse, duePhrase } from "@/lib/dashboard/deadline";
import { stageOf, type PulseRow } from "@/lib/dashboard/summary";

/**
 * The pulse — the four signals the board's rows actually carry, drawn instead
 * of restated. Everything on it is NEW information the subtitle and the board
 * don't already say:
 *
 *   - **momentum** — applications filed per week (`MOMENTUM_WEEKS` weeks
 *     of bars, oldest first) and the last-4-weeks-vs-prior-4 delta, from the
 *     same one derivation (`lib/dashboard/age.ts`) so the arrow can never
 *     contradict the bars;
 *   - **ageing** — the open (applied + assessment + interviewing) rows
 *     bucketed by days since filed; the ≥2-week share is the amber "quiet"
 *     signal, the same threshold that tags individual cards;
 *   - **deadlines** — the rows carrying a `due_at`, bucketed
 *     overdue / due ≤{@link DUE_SOON_DAYS}d / later by the same derivation
 *     that inks the card tags (`lib/dashboard/deadline.ts`), plus the single
 *     most urgent row BY NAME — the one thing on this surface a user should
 *     act on today. When nothing carries a deadline the cell says so and says
 *     where deadlines come from, instead of inventing urgency: most boards,
 *     most of the time, honestly have nothing due;
 *   - **classifier** — how much of this pipeline the classifier built
 *     (source = "gmail" rows) and what it is holding under the 0.85 gate,
 *     deep-linked to the review queue.
 *
 * ONE home, one layout: the column under the stage buttons in the board's own
 * spine (`PipelineBoard` mounts it inside the "Stages" aside). It lived as a
 * full-width strip above the worklist, then as the shell rail's instrument
 * column (PR #122) — both were the wrong shelf, measured: the strip spent a
 * ~200px band of every viewport restating what this column says in the
 * spine's own blank space, and the rail version made the sidebar itself
 * scroll (744px of column in a 537–717px pane at 1280×720…1440×900), which
 * read as "the dashboard still scrolls". The spine has the empty vertical
 * run under "closed", it is stage-lens territory (these signals ARE lenses on
 * the same rows), and it collapses below `lg` exactly like the pulse should:
 * a phone dashboard leads with the worklist, and every signal's ground truth
 * already inks the cards themselves (age tags, deadline tags, the review
 * queue in the list). No display-none twin renders anywhere.
 *
 * The grammar is the spine's own: a caps label, a drawn element, one figure
 * line — dense on purpose. No week axis (the delta line states recency; the
 * aria-label states "oldest first"), no ladders (three rungs of dot–label–
 * figure cost 3× the height of one condensed line and said the same thing),
 * and exactly two bars (momentum's and ageing's): deadline counts are units,
 * not proportions, and the classifier fraction is already a number.
 *
 * Rows arrive as {@link PulseRow} — the projection of a board row this
 * component actually reads; callers holding full rows pass them as-is
 * (structurally assignable).
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
 * the newest N rather than pretending to describe everything — once, as the
 * column's last line, since every signal derives from the same slice.
 * Ages/weeks are calendar-day math on a day string — UTC for the server pass
 * and the hydrating pass, the reader's own day thereafter — so the pulse
 * hydrates cleanly and then tells the truth about time left. The micro-bars
 * are `aria-hidden` decoration over the numbers, animate in with a
 * transform-only CSS entrance (`.pulse-seg`, globals.css), and collapse to
 * their final state under `prefers-reduced-motion` — nothing here is gated on
 * an animation.
 */

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
      className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
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
}: {
  /** The loaded rows — the same bounded page `PipelineBoard` renders. */
  applications: PulseRow[];
  /** The account's true total, from the counts-only summary endpoint. */
  total: number;
  /** Verdicts held under the gate for the user (0 when the queue is clear). */
  needsReview: number;
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
  //
  // `assessment` is open, and naming it here is not optional: this is a stage
  // ALLOW-list, not a `stageOf` lookup, so TypeScript would not have noticed
  // its absence — assessment rows would simply have vanished from the ageing
  // line and from `openTotal`. Same defect family as `stageOf`'s
  // `?? "applied"` fallback, in a different disguise.
  const openAges = applications
    .filter((app) => {
      const stage = stageOf(app.status);
      return stage === "applied" || stage === "assessment" || stage === "interviewing";
    })
    .map((app) => daysBetween(filedAt(app), today));
  const ages = bucketAges(openAges);
  const openTotal = ages.fresh + ages.waiting + ages.quiet;

  // --- deadlines (rows carrying a due_at; no due date, no claim) -------------
  const due = deadlinePulse(applications, today);

  // --- classifier -----------------------------------------------------------
  const autoFiled = applications.filter((app) => app.source === "gmail").length;

  const scopeNote = complete ? null : `newest ${applications.length} of ${total}`;

  return (
    <section aria-label="Pipeline pulse" data-testid="pipeline-pulse" className="flex flex-col">
      {/* momentum */}
      <div className="border-t border-line-soft py-2">
        <h2 className="label-caps">momentum · filed per wk</h2>
        <div
          role="img"
          aria-label={`Applications filed per week, oldest first: ${weeks.join(", ")}`}
          className="mt-1.5 flex h-5 items-end gap-1"
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
        <p className="tabular mt-1.5 text-xs text-muted">
          <span className="tabular text-strong">{recent}</span> last 4 wk{" "}
          <span aria-hidden="true">{arrow}</span> vs {prior} prior
        </p>
      </div>

      {/* ageing */}
      <div className="border-t border-line-soft py-2">
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
            <p className="tabular mt-1.5 text-xs text-muted">
              <span className="tabular text-strong">{ages.fresh}</span> &lt;1 wk ·{" "}
              <span className="tabular">{ages.waiting}</span> 1–2 wk ·{" "}
              {/* "quiet" is the column's one amber word when it is non-zero —
                  the same threshold that tags the individual cards. */}
              <span className={ages.quiet > 0 ? "text-review" : ""}>
                <span className="tabular">{ages.quiet}</span> quiet
              </span>
            </p>
          </>
        )}
      </div>

      {/* deadlines */}
      <div className="border-t border-line-soft py-2">
        <h2 className="label-caps">deadlines · time left</h2>
        {due.total === 0 ? (
          <>
            {/* The state most users see most of the time, so it earns real
                copy: never a nag, never counts drawn at zero. */}
            <p className="mt-2 text-xs text-dim">nothing due</p>
            <p className="mt-1 text-[11px] leading-snug text-dim">
              filed from mail when one is stated · or set one in a card&apos;s detail
            </p>
          </>
        ) : (
          <>
            {/* Counts, no bar: deadline counts are units, not proportions —
                two overdue beside ten "later" is not a 1:5 wash of red.
                "N overdue" turns red as a unit — a red word beside a white
                digit would put the emphasis on the wrong half. */}
            <p className="tabular mt-1.5 text-xs text-muted">
              <span className={due.overdue > 0 ? "font-medium text-reject-ink" : ""}>
                <span className={due.overdue > 0 ? "tabular" : "tabular text-strong"}>
                  {due.overdue}
                </span>{" "}
                overdue
              </span>{" "}
              · <span className="tabular">{due.soon}</span> ≤{DUE_SOON_DAYS}d ·{" "}
              <span className="tabular">{due.later}</span> later
            </p>
            {/* The one to act on today, by name — smallest days-left wins, so
                an overdue row outranks everything until it is dealt with. */}
            {due.urgent ? (
              <p className="mt-1 text-xs leading-snug text-muted">
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

      {/* classifier */}
      <div className="border-t border-line-soft py-2">
        <h2 className="label-caps">classifier</h2>
        <p className="tabular mt-1.5 text-xs text-muted">
          <span className="tabular text-strong">{autoFiled}</span> of {applications.length}{" "}
          auto-filed from mail
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

      {/* The bounded-page caveat, once for the whole column — every signal
          above derives from the same loaded slice, so per-cell repetition
          bought nothing but noise at this width. */}
      {scopeNote ? (
        <p className="border-t border-line-soft py-2 text-[11px] leading-snug text-dim">
          signals derive from the {scopeNote} rows
        </p>
      ) : null}
    </section>
  );
}
