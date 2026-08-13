"use client";

import Link from "next/link";
import type { ReactNode } from "react";

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
 *     where a deadline comes from, instead of inventing urgency: most boards,
 *     most of the time, honestly have nothing due;
 *   - **auto-filed** — how much of this board arrived from the user's own
 *     mail (source = "gmail" rows) and what is being held for their review,
 *     deep-linked to the review queue. The mechanism's real names (the
 *     classifier, the 0.85 gate) live in Settings, which is the page that
 *     controls them — here the user has a mailbox, not a classifier.
 *
 * ONE home, one layout: a full-width band across the top of the board's body
 * (`PipelineBoard` mounts it above the spine + worklist row). This is the
 * pre-#136 home restored at a fraction of the cost: the original strip spent
 * ~200px of every viewport (p-4 cells, h-9 bars, a week-axis line, a
 * two-line urgent block); this band says the same four things in ~56px —
 * label, drawn element and one figure line per cell, the urgent row riding
 * the deadline cell's own label line. The two rejected homes stay rejected:
 * the shell rail (PR #122) made the sidebar itself scroll, and the stage
 * spine (#136) took the pulse out of the dashboard's content area, which is
 * where the owner keeps putting it back. Left columns are closed territory
 * for this feature.
 *
 * `lg`-up only, one instance, no display-none twins: below `lg` the dashboard
 * leads with the worklist and every signal's ground truth already inks the
 * cards themselves (age tags, deadline tags, the review queue in the list).
 * Between `lg` and `xl` the band speaks without drawing: captions set one
 * notch down (11px on the same 16px line, so the band's height — and the
 * worklist's floors — never move) and every bar waits for `xl`. Measured at
 * 1024×768 the four cells hold 159–172px of content while the auto-filed
 * sentence alone is 176px, so no caption+bar pair fits at any bar width
 * (see SegmentBar). The words lose nothing the drawings said — every bar's
 * aria restates its caption's numbers — except the momentum cell's 8-week
 * shape, the one honest casualty; its delta sentence keeps that signal
 * until `xl` returns the bars.
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
 * Ink policy (owner call, 2026-08-12: colour where the data is, not
 * everywhere): the DRAWN elements carry chromatic ink; labels, counts and
 * prose stay on the text ramp. These charts are not stage rollups — they
 * count time and provenance — so they must not borrow stage ink: doing so is
 * what rendered the whole band grey on the real account (every row in
 * `applied`, whose stage accent is deliberately achromatic). Instead,
 * recency wears the product's sky accent (`--viz-rules`, the nav-focus and
 * brand-mark hue) on the momentum bars and the age bar's fresh segment, and
 * the auto-filed share wears the verdict emerald (`--viz-setfit`, the brand
 * mark's "delivered" node). Amber/red stay reserved for the attention states
 * they already mean, and the neutral buckets (prior weeks, 1–2 wk, filed by
 * hand) stay grey ON PURPOSE — a board with one hot bucket reads as one
 * strong ink, not as a wash. Every fill measures ≥3:1 against its ground in
 * BOTH themes (WCAG 1.4.11; worst case emerald on the light track, 3.43:1),
 * and no distinction rides on colour alone — the caption's numbers restate
 * every split the bars draw.
 *
 * Honesty rules: the board fetch is one bounded page, so when the loaded rows
 * are fewer than the account's total the row-derived signals say they describe
 * the newest N rather than pretending to describe everything — once, as the
 * band's trailing line, since every signal derives from the same slice.
 * Ages/weeks are calendar-day math on a day string — UTC for the server pass
 * and the hydrating pass, the reader's own day thereafter — so the pulse
 * hydrates cleanly and then tells the truth about time left. The micro-bars
 * are `aria-hidden` decoration over the numbers, animate in with a
 * transform-only CSS entrance (`.pulse-seg`, globals.css), and collapse to
 * their final state under `prefers-reduced-motion` — nothing here is gated on
 * an animation.
 */

/** A thin proportional bar of coloured segments (zero segments not drawn).
 *
 *  Sizing is the sentence-first contract, measured (dev Chromium,
 *  2026-08-12): the bar renders from `xl` up and flexes into whatever the
 *  caption leaves, capped at `maxWidthClass`. Below `xl` no cell can afford
 *  it — at 1024×768 the auto-filed cell holds 171px against a 176px
 *  sentence, so ANY bar width is bought with ellipsis (a fixed w-16 clipped
 *  the sentence 77px there, w-12 still 61px; the bar-less base band already
 *  clipped 4.8px). From 1280×800 the cells hold 223–235px, which fits
 *  caption + full-cap bar with only 2–3px spare: `flex-1` (basis 0) is what
 *  makes that safe — a caption that grows (three-digit counts) shrinks the
 *  bar instead of ellipsizing, because decoration never holds a claim on
 *  space the sentence needs. */
function SegmentBar({
  ariaLabel,
  total,
  segments,
  maxWidthClass = "max-w-16",
}: {
  ariaLabel: string;
  total: number;
  segments: readonly (readonly [number, string])[];
  maxWidthClass?: string;
}) {
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      // gap-px: a hairline of ground between touching segments, so a bucket
      // boundary never rides on hue alone (fresh|waiting sit at near-equal
      // luminance by design — the ramp greys match the chromatic fills' weight).
      className={`hidden h-1.5 min-w-0 flex-1 gap-px overflow-hidden rounded-full bg-surface-2 xl:flex ${maxWidthClass}`}
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

/**
 * One cell of the band: caps label (with an optional right-aligned aside on
 * the same line — the deadline cell's "act on this today" slot), then one
 * content line. Two lines, `py-2` — the whole band's height budget lives
 * here, because every pixel it grows comes out of the worklist below it.
 */
function PulseCell({
  label,
  aside,
  children,
}: {
  label: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 border-line-soft px-3 py-2 first:pl-0 last:pr-0 [&+&]:border-l">
      <div className="flex items-baseline justify-between gap-2">
        {/* A cell WITH an aside keeps its (short) label whole and lets the
            aside truncate; a cell without one lets the label give way at the
            narrowest lg widths instead of bleeding into its neighbour. */}
        <h2 className={aside ? "label-caps shrink-0" : "label-caps min-w-0 truncate"}>{label}</h2>
        {aside}
      </div>
      <div className="mt-1 flex min-w-0 items-center gap-2">{children}</div>
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

  // --- auto-filed -----------------------------------------------------------
  const autoFiled = applications.filter((app) => app.source === "gmail").length;

  const scopeNote = complete ? null : `newest ${applications.length} of ${total}`;

  return (
    <section
      aria-label="Board pulse"
      data-testid="pipeline-pulse"
      className="hidden border-y border-line-soft lg:grid lg:grid-cols-4"
    >
      {/* momentum */}
      <PulseCell label="momentum · filed per wk">
        <div
          role="img"
          aria-label={`Applications filed per week, oldest first: ${weeks.join(", ")}`}
          // Same xl gate and flex-absorb as SegmentBar: the delta sentence is
          // 129px and the lg-range line holds 100px beside a w-16 bar —
          // no width of week-columns fits without ellipsizing the sentence.
          className="hidden h-4 min-w-0 max-w-16 flex-1 items-end gap-0.5 xl:flex"
        >
          {weeks.map((count, i) => (
            <span
              key={i}
              data-testid="pulse-week"
              title={`${count} filed`}
              className="pulse-seg min-w-0 flex-1 rounded-sm"
              style={{
                height: count > 0 ? `${Math.max(18, (count / peak) * 100)}%` : "2px",
                // Two inks, one meaning: the delta sentence beside these bars
                // compares the last 4 weeks against the prior 4, so the bars
                // draw that same split — the recency sky for the half the
                // sentence leads with, the ramp's neutral grey for the prior
                // baseline, mirroring the sentence's own strong-vs-muted
                // weights. (A same-hue 45% fade was measured first: 1.8:1 on
                // the light ground, invisible. Solid neutral keeps every
                // filled bar ≥3:1 in both themes.) Colour encodes the
                // comparison; it never decorates.
                background:
                  count > 0
                    ? i >= weeks.length - 4
                      ? "var(--viz-rules)"
                      : "var(--text-dim)"
                    : "var(--line-strong)",
                ["--i" as string]: i,
              }}
            />
          ))}
        </div>
        <p
          data-testid="pulse-caption"
          className="tabular min-w-0 truncate text-[11px]/4 text-muted xl:text-xs"
        >
          <span className="tabular text-strong">{recent}</span> last 4 wk{" "}
          <span aria-hidden="true">{arrow}</span> vs {prior} prior
        </p>
      </PulseCell>

      {/* ageing */}
      <PulseCell label="open · age since filed">
        {openTotal === 0 ? (
          <p data-testid="pulse-caption" className="text-[11px]/4 text-dim xl:text-xs">
            no open applications
          </p>
        ) : (
          <>
            {/* A cool→warm staleness ramp: fresh wears the recency sky (the
                same fact the momentum bars ink — days since filed), waiting
                stays ramp-grey, quiet keeps the amber its card tags already
                wear. A one-bucket board draws one solid ink — a young board
                reads sky, a stalling one amber — instead of the uniform grey
                the stage borrow used to produce. */}
            <SegmentBar
              ariaLabel={`Open applications by age: ${ages.fresh} under a week, ${ages.waiting} one to two weeks, ${ages.quiet} quiet two weeks or more`}
              total={openTotal}
              segments={[
                [ages.fresh, "var(--viz-rules)"],
                [ages.waiting, "var(--text-dim)"],
                [ages.quiet, "var(--amber)"],
              ]}
            />
            <p
              data-testid="pulse-caption"
              className="tabular min-w-0 truncate text-[11px]/4 text-muted xl:text-xs"
            >
              <span className="tabular text-strong">{ages.fresh}</span> &lt;1 wk ·{" "}
              <span className="tabular">{ages.waiting}</span> 1–2 wk ·{" "}
              {/* "quiet" is the band's one amber word when it is non-zero —
                  the same threshold that tags the individual cards. */}
              <span className={ages.quiet > 0 ? "text-review" : ""}>
                <span className="tabular">{ages.quiet}</span> quiet
              </span>
            </p>
          </>
        )}
      </PulseCell>

      {/* deadlines — the label tail is cut here (unlike its siblings) to make
          room for the one thing on this surface to act on today, named on the
          label's own line: the row with the smallest days-left, so an overdue
          row outranks everything until it is dealt with. */}
      <PulseCell
        label="deadlines"
        aside={
          due.urgent ? (
            // The phrase is the urgent part, so it never truncates; a long
            // company name gives way instead.
            <p className="flex min-w-0 items-baseline gap-1 text-xs leading-snug text-muted">
              <span className="shrink-0">next ·</span>
              <span className="min-w-0 truncate">{due.urgent.company}</span>
              <span
                className={`tabular shrink-0 font-mono text-[10px] ${
                  due.urgent.daysLeft < 0 ? "text-reject-ink" : "text-review"
                }`}
              >
                {duePhrase(due.urgent.daysLeft)}
              </span>
            </p>
          ) : undefined
        }
      >
        {due.total === 0 ? (
          // The state most users see most of the time — never a nag, never
          // counts drawn at zero, and it says where a deadline comes from.
          // "in a card", not "in a card's detail": the longer tail measured
          // 201px against this cell's 159px at 1024×768 — the one caption no
          // type size could save.
          <p
            data-testid="pulse-caption"
            className="min-w-0 truncate text-[11px]/4 text-dim xl:text-xs"
          >
            nothing due · set one in a card
          </p>
        ) : (
          // Counts, no bar: deadline counts are units, not proportions — two
          // overdue beside ten "later" is not a 1:5 wash of red. "N overdue"
          // turns red as a unit — a red word beside a white digit would put
          // the emphasis on the wrong half.
          <p
            data-testid="pulse-caption"
            className="tabular min-w-0 truncate text-[11px]/4 text-muted xl:text-xs"
          >
            <span className={due.overdue > 0 ? "font-medium text-reject-ink" : ""}>
              <span className={due.overdue > 0 ? "tabular" : "tabular text-strong"}>
                {due.overdue}
              </span>{" "}
              overdue
            </span>{" "}
            {/* "soon" takes the review amber only while it counts something —
                the same ink its card tags already wear. */}
            ·{" "}
            <span className={due.soon > 0 ? "text-review" : ""}>
              <span className="tabular">{due.soon}</span> ≤{DUE_SOON_DAYS}d
            </span>{" "}
            · <span className="tabular">{due.later}</span> later
          </p>
        )}
      </PulseCell>

      {/* auto-filed */}
      <PulseCell label="auto-filed · from your mail">
        {/* The machine's own cell gets the machine's verdict ink: the
            auto-filed share in emerald (`--viz-setfit`, the brand mark's
            "delivered" node), the hand-filed remainder in ramp-grey. Same
            inline h-1.5 geometry as the ageing bar, so the drawn element
            costs the band no height — the two-line budget is the contract. */}
        {applications.length > 0 ? (
          <SegmentBar
            ariaLabel={`${autoFiled} of ${applications.length} filed from your mail, ${applications.length - autoFiled} by hand`}
            total={applications.length}
            segments={[
              [autoFiled, "var(--viz-setfit)"],
              [applications.length - autoFiled, "var(--text-dim)"],
            ]}
            maxWidthClass="max-w-12"
          />
        ) : null}
        {/* The one caption holding a focusable control. `truncate`'s
            overflow-hidden crops the app-wide focus ring (2px at +1px
            offset) — measured, the link's box IS this p's content box, so
            the ring lost its top, bottom and right edges. The 4px padding,
            pulled back by equal negative margins, moves the clip boundary
            past the ring without spending a pixel of layout: content width,
            line height and the band's floors are unchanged. */}
        <p
          data-testid="pulse-caption"
          className="tabular -my-[4px] -mr-[4px] min-w-0 truncate py-[4px] pr-[4px] text-[11px]/4 text-muted xl:text-xs"
        >
          <span className="tabular text-strong">{autoFiled}</span> of {applications.length}
          {" · "}
          {needsReview > 0 ? (
            // "held for review", not "held for YOUR review": the queue this
            // links to is headed "Needs review", so the link keeps the review
            // family's name — and the short form is what fits beside the
            // figure at the lg boundary (163px vs the long form's 190px,
            // against a 171px cell).
            <Link
              href="/dashboard#needs-classification"
              className="font-medium text-review underline-offset-2 hover:underline"
            >
              <span className="tabular">{needsReview}</span> held for review →
            </Link>
          ) : (
            <span className="text-dim">nothing waiting on you</span>
          )}
        </p>
      </PulseCell>

      {/* The bounded-page caveat, once for the whole band — every signal
          above derives from the same loaded slice, so per-cell repetition
          bought nothing but noise. */}
      {scopeNote ? (
        <p className="tabular col-span-full border-t border-line-soft py-1 text-[11px] leading-snug text-dim">
          signals derive from the {scopeNote} rows
        </p>
      ) : null}
    </section>
  );
}
