"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import {
  MOMENTUM_DAYS,
  QUIET_AFTER_DAYS,
  ageHistogram,
  bucketAges,
  dailyCounts,
  daysBetween,
  weekOverWeek,
} from "@/lib/dashboard/age";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";
import { filedAt } from "@/lib/dashboard/dates";
import {
  deadlineCaption,
  deadlinePulse,
  deadlineRunway,
  duePhrase,
} from "@/lib/dashboard/deadline";
import type { PulseFilter } from "@/lib/dashboard/pulseFilter";
import { isOpenStage, type PulseRow } from "@/lib/dashboard/summary";
import { cn } from "@/lib/utils";
import { PulseDetail, type PulseDetailKind } from "./PulseDetail";

/**
 * The pulse — the four signals the board's rows actually carry, drawn instead
 * of restated. Everything on it is NEW information the subtitle and the board
 * don't already say:
 *
 *   - **momentum** — applications filed per DAY (`MOMENTUM_DAYS` days of
 *     bars, oldest first) and the this-week-vs-last delta, from the same one
 *     derivation (`lib/dashboard/age.ts`) so the arrow can never contradict
 *     the bars. Days, not weeks (#156): the real account filed its whole
 *     board inside four weeks, so weekly buckets rendered a 41-application
 *     burst as 7 flat dashes and one filled tick — the daily bursts are the
 *     shape worth drawing;
 *   - **ageing** — the open (`isOpenStage`) rows as a day-of-age histogram,
 *     oldest at the left so "recent" reads rightward in both charts; the
 *     ≥2-week overflow bin is the amber "quiet" signal, the same threshold
 *     that tags individual cards. The caption names only the non-zero
 *     buckets — `0 1–2 wk · 0 quiet` was most of a line spent saying nothing
 *     is there (#159);
 *   - **deadlines** — the rows carrying a `due_at`, bucketed overdue / inside
 *     the soon window / after it by the same derivation that inks the card
 *     tags (`lib/dashboard/deadline.ts`), plus the single most urgent row BY
 *     NAME — the one thing on this surface a user should act on today. When
 *     nothing carries a deadline the cell says so and says where a deadline
 *     comes from, instead of inventing urgency: most boards, most of the
 *     time, honestly have nothing due;
 *   - **auto-filed** — how much of this board arrived from the user's own
 *     mail (source = "gmail" rows) and what is being held for their review,
 *     deep-linked to the review queue. The visible caption now names the
 *     remainder — `36 of 41` with five unexplained rows read as five rows
 *     UNACCOUNTED FOR (#158), while the bar's aria-label was already telling
 *     screen readers "5 by hand". The mechanism's real names (the
 *     classifier, the 0.85 gate) belong to the review queue this cell links
 *     into, which draws every held verdict against that gate — here the user
 *     has a mailbox, not a classifier. Settings used to carry the same
 *     explanation and no longer does: the gate is one number for every account
 *     and there was never a working way to move it (#208), so a whole card of
 *     prose about it was sitting on the page of things you can change.
 *
 * THE CELLS OPEN — all four of them. Pressing one docks a detail panel
 * (`PulseDetail`) under the band — inside the dashboard, anchored to its
 * cell, with the board still live around it. One panel, one interaction, four
 * contents; every drawn unit inside it (a day bar, an age bin, a runway bin, a
 * provenance group) narrows the WORKLIST to the rows it counts, which is what
 * makes the band a work surface instead of a poster. Not a modal, on the
 * record: the row-detail decision already rejected an exclusive overlay ("an
 * overlay's exclusivity contract IS the complaint"), so this panel dims
 * nothing, traps nothing, and closes on Escape, outside click, its own ✕ or
 * the act of filtering.
 *
 * The deadline cell was the exception until 2026-08-13, and the reason it was
 * is worth keeping: it opened onto nothing on a board with no deadlines, and
 * "a panel of invented urgency is the exact failure its caption already
 * refuses". The board that argument was measured on carried zero deadlines;
 * the live one now carries a real one, and the owner overruled the exception
 * regardless. The worry survives as the gate rather than as a refusal — no
 * deadlines, no trigger — which is the same condition the other three cells
 * have always been under (see each cell's `expand`).
 *
 * ONE home, one layout: a full-width band across the top of the board's body
 * (`PipelineBoard` mounts it above the spine + worklist row). This is the
 * pre-#136 home restored at a fraction of the cost: the original strip spent
 * ~200px of every viewport; this band says the same four things in ~56px —
 * label, drawn element and one figure line per cell. The two rejected homes
 * stay rejected: the shell rail (PR #122) made the sidebar itself scroll, and
 * the stage spine (#136) took the pulse out of the dashboard's content area.
 * Left columns are closed territory for this feature. The detail panel is
 * `absolute` inside the band's own `relative` (its containing block — the
 * #149/#152/#153 family is why that is stated, not assumed) and height-capped,
 * so the document never scrolls and the worklist floors never move: the band's
 * two-line budget is untouched, and depth is bought by OPENING, not by
 * growing.
 *
 * `lg`-up only, one instance, no display-none twins: below `lg` the dashboard
 * leads with the worklist and every signal's ground truth already inks the
 * cards themselves (age tags, deadline tags, the review queue in the list) —
 * which is also why the panel needs no phone sheet: its triggers don't exist
 * there. Between `lg` and `xl` the band speaks without drawing: captions set
 * one notch down (11px on the same 16px line, so the band's height — and the
 * worklist's floors — never move) and every bar waits for `xl`. Measured at
 * 1024×768 the four cells hold 159–172px of content while the auto-filed
 * sentence alone is 176px, so no caption+bar pair fits at any bar width
 * (see SegmentBar). The deadline cell's bucket counts wait for `xl` on the
 * same terms and for the same reason: below it, that cell's second line is
 * the only place the most urgent row can be NAMED, and a named row is worth
 * more there than three numbers (see the cell).
 *
 * Rows arrive as {@link PulseRow} — the projection of a board row this
 * component actually reads; callers holding full rows pass them as-is
 * (structurally assignable).
 *
 * This is a client component, and deliberately: the deadline cell counts what
 * is overdue, which is a claim about the READER's day, so its clock read has to
 * survive past the server render (`useLocalToday`). The whole band still
 * server-renders; the panel exists only after a click.
 *
 * Ink policy (owner call, 2026-08-12: colour where the data is, not
 * everywhere): the DRAWN elements carry chromatic ink; labels, counts and
 * prose stay on the text ramp. These charts are not stage rollups — they
 * count time and provenance — so they must not borrow stage ink: doing so is
 * what rendered the whole band grey on the real account (every row in
 * `applied`, whose stage accent is deliberately achromatic). Instead,
 * recency wears the product's sky accent (`--viz-rules`) — the momentum
 * bars' last seven days and the age histogram's under-a-week bins — and the
 * auto-filed share wears the verdict emerald (`--viz-setfit`). Amber/red stay
 * reserved for the attention states they already mean (the quiet bin, the
 * review queue), and the neutral bins stay grey ON PURPOSE. Every fill
 * measures ≥3:1 against its ground in BOTH themes (WCAG 1.4.11; re-measured
 * for the panel's `--surface` ground 2026-08-13 — worst case emerald 3.77:1
 * light / 3.43:1 on the light track), and no distinction rides on colour
 * alone — every split the bars draw is also positional (both charts run
 * oldest→newest on one shared axis reading) and restated in numbers by the
 * panel one click away, and a zero-day's 2px stub is distinguished by SIZE,
 * not by its hairline ink.
 *
 * Caption grammar (Ayush, 2026-08-13, on `6 <1 wk · 5 1–2 wk · 3 quiet`:
 * "these text are still there, they are lot confusing!"): a caption is ONE
 * claim, two at most, each binding one figure to the words that own it —
 * never the per-bucket recitation, which was six numerals in nine words
 * restating a distribution the bar beside it already draws, its pairs
 * colliding as they went (`6 <1` reads as a comparison; `5 1–2 wk` butts a
 * count against a range). The bar carries the shape; the caption carries
 * the claim worth acting on — the quiet share, the week-over-week
 * direction, the named remainder — with figures bound FORWARD by words
 * ("of", "up from", "by hand"), never left touching a unit's numeral. The
 * lead figure sits a step brighter than its words (`text-strong`), and
 * amber/red colour a claim as a unit, never a lone digit.
 *
 * Honesty rules: the board fetch is one bounded page, so when the loaded rows
 * are fewer than the account's total the row-derived signals say they describe
 * the newest N rather than pretending to describe everything — once, as the
 * band's trailing line, since every signal derives from the same slice.
 * Ages/days are calendar-day math on a day string — UTC for the server pass
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

/** A day-resolution micro chart: one bar per day, `xl`-up, flexing into
 *  whatever the caption leaves (same sentence-first contract as SegmentBar,
 *  same reasons). ~2–3px bars at the cap — a rhythm strip, not a readable
 *  axis; the numbers live in the caption and the full chart in the panel.
 *  A zero day keeps a 2px stub so the RHYTHM (gaps between bursts) stays
 *  visible; its meaning is carried by size, never by the hairline's ink. */
function DayStrip({
  ariaLabel,
  counts,
  testId,
  colorAt,
}: {
  ariaLabel: string;
  counts: number[];
  testId: string;
  /** Ink for a non-zero bar at index `i` — the caption's own split, drawn. */
  colorAt: (i: number) => string;
}) {
  const peak = Math.max(...counts, 1);
  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="hidden h-4 min-w-0 max-w-24 flex-1 items-end gap-px xl:flex"
    >
      {counts.map((count, i) => (
        <span
          key={i}
          data-testid={testId}
          className="pulse-seg min-w-0 flex-1 rounded-[1px]"
          style={{
            height: count > 0 ? `${Math.max(18, (count / peak) * 100)}%` : "2px",
            background: count > 0 ? colorAt(i) : "var(--line-strong)",
            ["--i" as string]: i,
          }}
        />
      ))}
    </div>
  );
}

/**
 * One cell of the band: caps label (with an optional aside — the deadline
 * cell's "act on this today" slot), then one content line. TWO LINES, `py-2`
 * — the whole band's height budget lives here, because every pixel it grows
 * comes out of the worklist below it.
 *
 * A grid rather than two flex rows, so the aside can change WHICH line it is
 * on without existing twice. From `xl` it rides the label's own line, exactly
 * as it always has; below `xl` it drops to the second line and takes the
 * cell's full measure, because there it cannot share a line with the label
 * and still say anything (measured: at 1024×768 the label + gap leave the
 * aside 83px against the 97px its two fixed parts alone need, which is how
 * the company name arrived at ZERO — see the deadlines cell). One node, two
 * placements: a display-none twin would duplicate the row's name in the
 * accessibility tree and in every `getByText`.
 *
 * The two-line budget survives that move because THIS component pairs it, not
 * its callers: a cell whose aside has taken the second line hides its own
 * content line there. Left to the caller it was got wrong immediately — the
 * content wrapper stayed in flow while its only child was hidden, which is a
 * zero-height row that still costs a `gap-y-1`, and the band measured 60px at
 * 1024 against 55px everywhere else. A wrapper that renders nothing must not
 * hold a row; the cell that owns the layout is the one that can promise it.
 *
 * A cell given `expand` is a TRIGGER for the detail panel: a stretched button
 * fills the whole cell (Ayush's ask was "click the whole momentum", not a
 * disclosure glyph), the grid rides above it inert (`pointer-events-none`) so
 * hits land on the button, and anything inside that must stay interactive
 * (the review-queue link) opts back in with `pointer-events-auto`. The grid
 * is one layer in from the cell's box only in that arm — same padding
 * outside, same gaps inside, so the geometry the worklist floors gate is
 * identical in both. The chevron is the resting affordance — dim until
 * hover, focus or open, `aria-expanded` carrying the state for everyone else.
 *
 * WHICH LINE THE CHEVRON RIDES, since 2026-08-13 the deadline cell has both an
 * aside and an `expand` and the two want the same far column. The chevron
 * takes whichever line has room, one node, two placements — the same trick
 * this grid already plays with the aside:
 *
 *   · a cell with no aside keeps it on the label line, where it always was;
 *   · a cell with BOTH keeps it there below `xl` — the aside has dropped to
 *     line two, so the label line's far column is empty — and moves it to the
 *     content line at `xl`, where the aside has come back up. Measured at
 *     1280×800 the label line is full to ~2px: label + name + due phrase need
 *     every pixel of the cell's 224px, so a 12px glyph there is bought by
 *     clipping the company name, which the caption-integrity gate rightly
 *     fails. The content line at that width spends ~183px of 224 on its
 *     caption, so it can seat the glyph and still say the whole sentence.
 *
 * The content line reserves that space with `pr-5` rather than a third grid
 * column: column one is `auto`, so a caption placed in it would size the
 * track and steal the width back off the aside above — the exact defect the
 * move exists to avoid.
 */
function PulseCell({
  label,
  aside,
  expand,
  triggerRef,
  children,
}: {
  label: string;
  aside?: ReactNode;
  expand?: {
    name: string;
    open: boolean;
    onToggle: () => void;
  };
  /** The stretched button's ref — a separate prop, forwarded straight into
   *  `ref`, so Escape/close can return focus to the trigger that opened. */
  triggerRef?: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
}) {
  const grid = (layer: string) => (
    <div
      className={cn(
        "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 xl:items-baseline",
        layer,
      )}
    >
      {/* `data-clip-ok`: labels are the one text in this band allowed to
          ellipsize — the auto-filed label measures 191px against a 171px cell
          at 1024 and gives way BY DESIGN rather than bleeding into its
          neighbour. The caption-integrity gate reads this attribute; nothing
          else in the band carries it. A trigger cell's label stays in column
          one at every width — the chevron owns the far column — so it gives
          way a chevron's width sooner, which is the same trade. */}
      <h2
        data-clip-ok=""
        className={cn(
          "label-caps row-start-1 min-w-0 truncate",
          expand ? "col-span-1" : "col-span-2 xl:col-span-1",
        )}
      >
        {label}
      </h2>
      {aside ? (
        <div className="col-span-2 row-start-2 min-w-0 xl:col-span-1 xl:col-start-2 xl:row-start-1">
          {aside}
        </div>
      ) : null}
      {expand ? (
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "col-start-2 h-3 w-3 self-center justify-self-end text-dim transition-transform motion-reduce:transition-none",
            aside ? "row-start-1 xl:row-start-2" : "row-start-1",
            expand.open
              ? "rotate-180 opacity-100"
              : "opacity-40 group-hover:opacity-100 group-focus-within:opacity-100",
          )}
        />
      ) : null}
      {/* `col-start-1` is not decoration: with the chevron holding column two
          of THIS row (a cell with both an aside and a trigger, at `xl`), an
          auto-placed two-column span finds no room in the explicit grid and
          opens an implicit third column — measured, that put the caption
          outside the cell and squeezed the aside back over the label. Stating
          the start lets the two share the row, and `pr-5` keeps them apart. */}
      <div
        className={cn(
          "col-span-2 col-start-1 row-start-2 flex min-w-0 items-center gap-2",
          aside && "max-xl:hidden",
          aside && expand && "xl:pr-5",
        )}
      >
        {children}
      </div>
    </div>
  );
  return (
    <div className="group relative min-w-0 border-line-soft px-3 py-2 first:pl-0 last:pr-0 [&+&]:border-l">
      {expand ? (
        <>
          <button
            type="button"
            ref={triggerRef}
            aria-expanded={expand.open}
            aria-controls="pulse-detail"
            aria-label={expand.name}
            onClick={expand.onToggle}
            data-open={expand.open || undefined}
            className="absolute inset-0 rounded-md transition-colors hover:bg-surface-2/50 data-[open]:bg-surface-2/50"
          />
          {/* Above the button in paint order (positioned + later), inert to
              the pointer so the stretched hit area stays whole. */}
          {grid("pointer-events-none relative")}
        </>
      ) : (
        grid("")
      )}
    </div>
  );
}

export function PipelinePulse({
  applications,
  total,
  needsReview,
  onFilter,
}: {
  /** The loaded rows — the same bounded page `PipelineBoard` renders. */
  applications: PulseRow[];
  /** The account's true total, from the counts-only summary endpoint. */
  total: number;
  /** Verdicts held under the gate for the user (0 when the queue is clear). */
  needsReview: number;
  /** The panel's click-through: narrow the worklist to the rows a drawn unit
   *  counts. Owned by `PipelineBoard`, which holds the list being narrowed. */
  onFilter: (filter: PulseFilter) => void;
}) {
  const today = useLocalToday();
  /** True when the single board page holds every row the account has. */
  const complete = applications.length >= total;

  /** Which cell's detail panel is open, if any — one panel, ever. */
  const [open, setOpen] = useState<PulseDetailKind | null>(null);
  const sectionRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const momentumTrigger = useRef<HTMLButtonElement | null>(null);
  const ageTrigger = useRef<HTMLButtonElement | null>(null);
  const deadlineTrigger = useRef<HTMLButtonElement | null>(null);
  const provenanceTrigger = useRef<HTMLButtonElement | null>(null);
  const triggerFor = (kind: PulseDetailKind) =>
    kind === "momentum"
      ? momentumTrigger
      : kind === "age"
        ? ageTrigger
        : kind === "deadline"
          ? deadlineTrigger
          : provenanceTrigger;

  // The panel is non-modal, so its lifecycle is: Escape closes and returns
  // focus to the trigger; any press outside the band closes it and lets the
  // press land where it fell (clicking a worklist row should select the row,
  // not spend the click on dismissal).
  useEffect(() => {
    if (open === null) return;
    const onPointerDown = (event: PointerEvent) => {
      if (
        sectionRef.current &&
        event.target instanceof Node &&
        !sectionRef.current.contains(event.target)
      ) {
        setOpen(null);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(null);
        triggerFor(open).current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Keyboard continuity: opening moves focus into the panel (it is DOM-last
  // in the band, several tab stops away from the trigger that opened it).
  useEffect(() => {
    if (open !== null) panelRef.current?.focus();
  }, [open]);

  const toggle = (kind: PulseDetailKind) => setOpen((cur) => (cur === kind ? null : kind));

  /** Filtering IS the panel's exit: the narrowed worklist is the answer, so
   *  the panel clears out of the way and focus returns to the trigger. */
  const applyFilter = (filter: PulseFilter) => {
    onFilter(filter);
    if (open !== null) triggerFor(open).current?.focus();
    setOpen(null);
  };

  // --- momentum -------------------------------------------------------------
  const days = dailyCounts(
    applications.map((app) => filedAt(app)),
    today,
  );
  const filedInWindow = days.reduce((a, b) => a + b, 0);
  const { thisWeek, lastWeek } = weekOverWeek(days);

  // --- ageing (open rows only — a closed row's age answers nothing) ---------
  const openRows = applications.filter((app) => isOpenStage(app.status));
  const openAges = openRows.map((app) => daysBetween(filedAt(app), today));
  const ages = bucketAges(openAges);
  const openTotal = ages.fresh + ages.waiting + ages.quiet;
  const ageBins = ageHistogram(openAges);
  /** The panel's "longest waiting" names — top of the ageing curve. */
  const oldestOpen = openRows
    .map((app) => ({ company: app.company, age: daysBetween(filedAt(app), today) }))
    .filter((row): row is { company: string; age: number } => row.age !== null && row.age >= 0)
    .sort((a, b) => b.age - a.age)
    .slice(0, 3);

  // --- deadlines (rows carrying a due_at; no due date, no claim) -------------
  const due = deadlinePulse(applications, today);

  // --- auto-filed -----------------------------------------------------------
  const autoFiled = applications.filter((app) => app.source === "gmail").length;
  const byHand = applications.length - autoFiled;
  /** Newest mail-sourced filing — the panel's "sync is alive" line. */
  let lastFromMail: string | null = null;
  {
    let bestAge = Infinity;
    for (const app of applications) {
      if (app.source !== "gmail") continue;
      const age = daysBetween(filedAt(app), today);
      if (age !== null && age >= 0 && age < bestAge) {
        bestAge = age;
        lastFromMail = filedAt(app);
      }
    }
  }

  const scopeNote = complete ? null : `newest ${applications.length} of ${total}`;

  /** The ageing caption — ONE claim, per the band's caption grammar. The
   *  first cut here (#159) omitted the empty buckets; Ayush re-reported it
   *  on a board with NO empty buckets (`6 <1 wk · 5 1–2 wk · 3 quiet` —
   *  "these text are still there, they are lot confusing!"), which is the
   *  proof the recitation itself was the defect, not the zeroes. The bar
   *  above this line and the panel behind it carry the distribution; the
   *  line carries the one thing anyone acts on — the quiet share when it
   *  exists, the bound every row clears when it doesn't. */
  const ageCaption = (() => {
    if (ages.fresh === openTotal)
      return (
        <>
          all <span className="tabular text-strong">{openTotal}</span> under a wk
        </>
      );
    if (ages.waiting === openTotal)
      return (
        <>
          all <span className="tabular text-strong">{openTotal}</span> 1–2 wk old
        </>
      );
    if (ages.quiet === openTotal)
      return (
        <span className="text-review">
          all <span className="tabular">{openTotal}</span> quiet 2 wk+
        </span>
      );
    // "quiet" is the band's one amber word — the same threshold that tags
    // the individual cards — and the whole claim turns amber as a unit, the
    // deadline cell's own "N overdue" contract. "of" is what binds the two
    // figures into one ratio instead of two adjacent counts.
    if (ages.quiet > 0)
      return (
        <span className="text-review">
          <span className="tabular">{ages.quiet}</span> of{" "}
          <span className="tabular">{openTotal}</span> quiet
        </span>
      );
    // Fresh and waiting mixed, nothing quiet: the honest single claim is the
    // bound they all clear — the same threshold quiet starts at.
    return (
      <>
        all <span className="tabular text-strong">{openTotal}</span> under 2 wk
      </>
    );
  })();

  return (
    <section
      ref={sectionRef}
      aria-label="Board pulse"
      data-testid="pipeline-pulse"
      // `relative` is the panel's containing block — load-bearing, not
      // styling: an absolute child with no positioned ancestor plants its box
      // at document scale and the whole shell scrolls (#149's family).
      className="relative hidden border-y border-line-soft lg:grid lg:grid-cols-4"
    >
      {/* momentum */}
      <PulseCell
        label="momentum · filed per day"
        expand={
          filedInWindow > 0
            ? {
                name: "Momentum detail",
                open: open === "momentum",
                onToggle: () => toggle("momentum"),
              }
            : undefined
        }
        triggerRef={momentumTrigger}
      >
        <DayStrip
          ariaLabel={`Filed per day, last ${MOMENTUM_DAYS} days: ${filedInWindow} total — this week ${thisWeek}, last week ${lastWeek}`}
          counts={days}
          testId="pulse-day"
          // Two inks, one meaning: the delta sentence beside these bars
          // compares this week against last, so the bars draw that same
          // split — the recency sky for the seven days the sentence leads
          // with, the ramp's neutral grey for everything before them. (A
          // same-hue 45% fade was measured first: 1.8:1 on the light ground,
          // invisible. Solid neutral keeps every filled bar ≥3:1 in both
          // themes.) Colour encodes the comparison; it never decorates.
          colorAt={(i) => (i >= days.length - 7 ? "var(--viz-rules)" : "var(--text-dim)")}
        />
        <p
          data-testid="pulse-caption"
          className="tabular min-w-0 truncate text-[11px]/4 text-muted xl:text-xs"
        >
          {/* Direction is a word, not a glyph beside a bare pair: `↑ vs 0
              last` put a count against a label with nothing binding them —
              the same collision the ageing caption was reported for. "up
              from 0" owns its figure; the baseline number stays on the muted
              ramp the way the prior days' bars stay grey. */}
          <span className="tabular text-strong">{thisWeek}</span> this wk
          {" · "}
          {thisWeek > lastWeek ? (
            <>up from {lastWeek}</>
          ) : thisWeek < lastWeek ? (
            <>down from {lastWeek}</>
          ) : (
            <>same as last</>
          )}
        </p>
      </PulseCell>

      {/* ageing */}
      <PulseCell
        label="open · age since filed"
        expand={
          openTotal > 0
            ? {
                name: "Ageing detail",
                open: open === "age",
                onToggle: () => toggle("age"),
              }
            : undefined
        }
        triggerRef={ageTrigger}
      >
        {openTotal === 0 ? (
          <p data-testid="pulse-caption" className="text-[11px]/4 text-dim xl:text-xs">
            no open applications
          </p>
        ) : (
          <>
            {/* The same day resolution as momentum, on the same axis reading:
                recent is rightward in both charts (oldest — the amber
                overflow bin — at the far left). A one-block SegmentBar drew
                a 38-rows-one-bucket board as one undifferentiated slab
                (#159); per-day bins give the bar the board's actual shape. */}
            <DayStrip
              ariaLabel={`Open applications by age, oldest left: ${ages.quiet} two weeks or more, ${ages.waiting} one to two weeks, ${ages.fresh} under a week`}
              counts={[...ageBins].reverse()}
              testId="pulse-age"
              colorAt={(i) => {
                const age = QUIET_AFTER_DAYS - i;
                if (age >= QUIET_AFTER_DAYS) return "var(--amber)";
                return age >= 7 ? "var(--text-dim)" : "var(--viz-rules)";
              }}
            />
            <p
              data-testid="pulse-caption"
              className="tabular min-w-0 truncate text-[11px]/4 text-muted xl:text-xs"
            >
              {ageCaption}
            </p>
          </>
        )}
      </PulseCell>

      {/* deadlines — the label tail is cut here (unlike its siblings) to make
          room for the one thing on this surface to act on today: the row with
          the smallest days-left, so an overdue row outranks everything until
          it is dealt with.

          IT OPENS, since 2026-08-13, and the comment that stood here said it
          never would: "the measured board has zero deadlines set, and a detail
          pane over nothing would be exactly the invented urgency this cell
          refuses". That was true of the board it was written against and is
          not true of the board now — the live account carries a real deadline
          — and the owner overruled the call outright ("i meant the deadline!
          it's not by design, do that too for god sake!"). The worry it was
          protecting was still the right worry, so it is answered in the shape
          rather than dropped: the cell is a trigger only while
          `due.total > 0`, exactly the gate its three siblings already use
          (`filedInWindow > 0`, `openTotal > 0`, `applications.length > 0`).
          On a board with nothing due there is no chevron, no button and no
          panel — the caption's "nothing due · set one in a card" is the whole
          honest answer, and a panel could only have restated it at length.

          WHERE the urgent row is named moves with the width, because at the lg
          boundary it cannot be named on the label's own line at all. Measured
          on /demo/shell (`next start`, headless Chrome, 2026-08-13), the cell
          is (viewport − 288) / 4 wide and the aside gets (cell − 24) − 76:
          148px at 1280 and 83px at 1024, against 177px for the full phrase.
          The company name is the only part that may shrink, so it took the
          whole shortfall — 50px of its 80px at 1280, and ZERO at 1024, where
          the cell read `next ·  overdue 2d`: a sentence with a dangling
          separator and no subject, which is worse than any ellipsis. So:

            · below `xl` the row is named on the cell's OWN line (the full
              measure, 160px at 1024 against the 137px name + phrase need) and
              the bucket counts wait for `xl` — the same trade, in the same
              words, that every bar in this band already makes. The counts are
              context; the name is the thing to act on, and the ageing cell's
              amber "quiet" still carries the same board's stalling signal;
            · `next ·` waits for 1440, the width at which it measured 11px of
              slack rather than 1px. Between `xl` and there the label, the name
              and the phrase say the whole thing without it.

          The name is never allowed to reach zero again at any width the band
          renders; `shell.spec.ts`'s caption-integrity gate measures it. */}
      <PulseCell
        label="deadlines"
        expand={
          due.total > 0
            ? {
                name: "Deadlines detail",
                open: open === "deadline",
                onToggle: () => toggle("deadline"),
              }
            : undefined
        }
        triggerRef={deadlineTrigger}
        aside={
          due.urgent ? (
            // The phrase is the urgent part, so it never truncates; a long
            // company name gives way instead — but only down to what the
            // cell's own line leaves it, never to nothing.
            //
            // Same type as every other caption in the band (11px on the same
            // 16px line below `xl`), because below `xl` this IS the cell's
            // caption line and sat one notch louder than its three siblings.
            // `justify-end` only from `xl`, where it shares the label's line
            // and has always sat at the cell's right edge.
            // `h-[1lh]`: ONE line box of this element's own type, the same
            // guarantee SinceLastLook's ArrivalLine makes and for the same
            // reason — baseline-aligning 11px prose against a 10px mono stamp
            // sums the larger ascent to the larger descent and returns a 17px
            // box, which on its own row cost the band a pixel it does not
            // have. Pinning the line means the type inside can change without
            // the worklist paying for it.
            <p className="flex h-[1lh] min-w-0 items-baseline gap-1 text-[11px]/4 text-muted xl:justify-end xl:text-xs">
              <span className="hidden shrink-0 min-[1440px]:inline">next ·</span>
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
        {/* The claims, from the one derivation the panel and the card tags
            share (`deadlineCaption`) — so the cell, the panel behind it and
            the tag on the row can never say three different things. Words and
            ordering live there; this is only how they are inked.

            No bar, ever: deadline counts are units, not proportions — two
            overdue beside ten "later" is not a 1:5 wash of red — and the
            runway that DOES draw them is a click away, where it has the room
            to be read. A claim turns colour as a unit ("1 overdue", not a red
            word beside a white digit), and the calm claim's lead figure sits
            a step brighter than its words, the band's own idiom.

            Below `xl` this line belongs to the named row instead, and
            PulseCell is what hands it over — it does so only when an aside
            exists to take it, so the claims can never stand down for an empty
            line. Nothing here has to know the width. */}
        <p
          data-testid="pulse-caption"
          className={cn(
            "min-w-0 truncate text-[11px]/4 xl:text-xs",
            due.total === 0 ? "text-dim" : "tabular text-muted",
          )}
        >
          {deadlineCaption(due).map((claim, i) => (
            <Fragment key={i}>
              {i > 0 ? " · " : null}
              <span
                className={cn(
                  claim.tone === "overdue" && "font-medium text-reject-ink",
                  claim.tone === "soon" && "text-review",
                )}
              >
                {claim.lead ? `${claim.lead} ` : null}
                {claim.count === null ? null : (
                  <span className={cn("tabular", claim.tone === "calm" && "text-strong")}>
                    {claim.count}
                  </span>
                )}
                {claim.count === null ? claim.words : ` ${claim.words}`}
              </span>
            </Fragment>
          ))}
        </p>
      </PulseCell>

      {/* auto-filed */}
      <PulseCell
        label="auto-filed · from your mail"
        expand={
          applications.length > 0
            ? {
                name: "Auto-filed detail",
                open: open === "provenance",
                onToggle: () => toggle("provenance"),
              }
            : undefined
        }
        triggerRef={provenanceTrigger}
      >
        {/* The machine's own cell gets the machine's verdict ink: the
            auto-filed share in emerald (`--viz-setfit`, the brand mark's
            "delivered" node), the hand-filed remainder in ramp-grey. Same
            inline h-1.5 geometry as ever, so the drawn element costs the
            band no height — the two-line budget is the contract. */}
        {applications.length > 0 ? (
          <SegmentBar
            ariaLabel={`${autoFiled} of ${applications.length} filed from your mail, ${byHand} by hand`}
            total={applications.length}
            segments={[
              [autoFiled, "var(--viz-setfit)"],
              [byHand, "var(--text-dim)"],
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
          {applications.length === 0 ? (
            <span className="text-dim">nothing filed yet</span>
          ) : needsReview > 0 ? (
            <>
              <span className="tabular text-strong">{autoFiled}</span> of {applications.length}
              {" · "}
              {/* "held for review", not "held for YOUR review": the queue this
                  links to is headed "Needs review", so the link keeps the review
                  family's name — and the short form is what fits beside the
                  figure at the lg boundary (163px vs the long form's 190px,
                  against a 171px cell). The remainder-by-hand answer waits in
                  the panel while something actionable holds this slot.
                  `pointer-events-auto`: the cell's stretched trigger owns every
                  other pixel; this link opts back in. */}
              <Link
                href="/dashboard#needs-classification"
                className="pointer-events-auto font-medium text-review underline-offset-2 hover:underline"
              >
                <span className="tabular">{needsReview}</span> held for review →
              </Link>
            </>
          ) : byHand > 0 ? (
            // The caption says what the aria-label always said (#158): the
            // remainder is the user's own hand-filed rows — benign, and
            // worrying only while it went unnamed. Two parallel claims for
            // the two provenances the bar draws, each figure bound forward
            // to its source: the earlier `36 of 41 · 5 by hand` left the
            // reader to reconcile THREE numerals, `41 · 5` touching across
            // the separator, and the total is the one number the subtitle
            // already owns.
            <>
              <span className="tabular text-strong">{autoFiled}</span> from your mail
              {" · "}
              <span className="tabular">{byHand}</span> by hand
            </>
          ) : (
            <>
              all <span className="tabular text-strong">{applications.length}</span> from your mail
            </>
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

      {/* The detail panel — docked under the band, anchored to its cell,
          board live around it. Mounted only while open, so the resting band
          costs exactly what it cost before. */}
      {open !== null ? (
        <PulseDetail
          panelRef={panelRef as RefObject<HTMLDivElement | null>}
          kind={open}
          today={today}
          momentum={{ days, thisWeek, lastWeek }}
          age={{ bins: ageBins, openTotal, quiet: ages.quiet, oldest: oldestOpen }}
          // The panel's numbers are the cell's own: one derivation, bucketed
          // once, drawn twice — the runway bins the rows the caption counted.
          deadline={{ pulse: due, runway: deadlineRunway(due.rows) }}
          provenance={{
            mail: autoFiled,
            hand: byHand,
            total: applications.length,
            needsReview,
            lastFromMail,
          }}
          onFilter={applyFilter}
          onClose={() => {
            triggerFor(open).current?.focus();
            setOpen(null);
          }}
        />
      ) : null}
    </section>
  );
}
