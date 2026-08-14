"use client";

import { X } from "lucide-react";
import Link from "next/link";
import type { ReactNode, RefObject } from "react";

import { MOMENTUM_DAYS, QUIET_AFTER_DAYS, bestDay, currentStreak, isoDaysAgo, weekdayOf } from "@/lib/dashboard/age";
import { shortDate } from "@/lib/dashboard/dates";
import {
  DUE_SOON_DAYS,
  DUE_SOON_WORDS,
  duePhrase,
  type DeadlineBin,
  type DeadlinePulse,
} from "@/lib/dashboard/deadline";
import type { PulseFilter } from "@/lib/dashboard/pulseFilter";
import { cn } from "@/lib/utils";

/**
 * The pulse's detail panel — one panel, one interaction, four contents
 * (#156/#158/#159 asked for "one coherent system, not three popovers"; the
 * deadline content joined them on 2026-08-13, when the owner overruled the
 * cell's standing refusal to open — see `PipelinePulse`'s header).
 * `PipelinePulse` mounts it inside the band's own `relative`, so it is an
 * `absolute` box under the band, anchored to the cell that opened it, with
 * the board fully live around it: no backdrop, no focus trap, no route. The
 * exclusivity contract the row-detail overlay was rejected for is exactly
 * what this shape avoids.
 *
 * The one verb, everywhere: every drawn unit — a day bar, an age bin, a
 * provenance group, a named row — is a control that narrows the WORKLIST to
 * the rows it counts (`onFilter`), and filtering closes the panel because the
 * narrowed list is the answer. That verb is what Ayush's "more detailed
 * analysis" cashes out to: not more prose about the rows, the rows.
 *
 * Geometry safety, stated because it is load-bearing: `max-h-80` +
 * `overflow-y-auto` caps the box so it can never extend past the shell's
 * <main> and hand the document a scrollbar (the #149 family, from the other
 * direction) — at the smallest locked viewport (1024×768) the band's bottom
 * sits ~180px into a ~700px pane, so 320px of panel clears it with room. The
 * worklist floors are untouched by construction: the panel overlays, it never
 * participates in the band's flow height.
 *
 * Numbers are figures (`tabular`, Atkinson) — mono stays reserved for machine
 * values, and nothing here is one. Charts reuse the band's exact inks on
 * grounds re-measured for `--surface` (see PipelinePulse's ink note), and the
 * captions/labels restate every count so no distinction rides on colour.
 */

export type PulseDetailKind = "momentum" | "age" | "deadline" | "provenance";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** `Tue Aug 5` — the panel's day name: weekday first, because weekday
 *  structure ("my Tuesdays are heavy") is half of what a daily chart is for. */
function dayName(iso: string): string {
  const wd = weekdayOf(iso);
  return wd === null ? shortDate(iso) : `${WEEKDAYS[wd]} ${shortDate(iso)}`;
}

/** Where the panel docks: under the cell that opened it. Grid maths, not
 *  measurement — the band is four equal columns.
 *
 *  Except that the third column's own quarter-line cannot hold the panel at
 *  every width, which is why the fourth cell anchors right rather than at
 *  `left-3/4`: the band is `viewport − 288` wide, so `left-1/2` puts this
 *  26rem box 48px past the band's right edge at 1024 — outside its own
 *  containing block, over the shell's padding. It clears from ~1120 up, so the
 *  cell's true anchor is an `xl` refinement of the same right edge its
 *  neighbour uses, never the other way round. */
const ANCHOR: Record<PulseDetailKind, string> = {
  momentum: "left-0",
  age: "left-1/4",
  deadline: "right-0 xl:left-1/2 xl:right-auto",
  provenance: "right-0",
};

const TITLES: Record<PulseDetailKind, string> = {
  momentum: `momentum · the last ${MOMENTUM_DAYS} days`,
  age: "open applications · by age",
  deadline: "deadlines · by time left",
  provenance: "auto-filed · how applications arrived",
};

/** A clickable histogram: the shared chart of the momentum and age contents.
 *  Bars with a count are buttons; empty positions keep their 2px stub as
 *  inert rhythm. `gapBefore` marks a boundary (weeks, the quiet threshold)
 *  with space — structure drawn with layout, not with more ink. */
function DayBars({
  bars,
  ariaLabel,
}: {
  ariaLabel: string;
  bars: {
    count: number;
    color: string;
    name: string;
    gapBefore?: boolean;
    onSelect?: () => void;
  }[];
}) {
  const peak = Math.max(...bars.map((bar) => bar.count), 1);
  return (
    <div role="group" aria-label={ariaLabel} className="flex h-20 items-end gap-px">
      {bars.map((bar, i) =>
        bar.count > 0 && bar.onSelect ? (
          <button
            key={i}
            type="button"
            title={bar.name}
            aria-label={`${bar.name} — show these on the board`}
            onClick={bar.onSelect}
            className={cn(
              "pulse-seg min-w-0 flex-1 rounded-t-[2px] transition-opacity hover:opacity-75 motion-reduce:transition-none",
              bar.gapBefore && "ml-1",
            )}
            style={{
              height: `${Math.max(10, (bar.count / peak) * 100)}%`,
              background: bar.color,
              ["--i" as string]: i,
            }}
          />
        ) : (
          <span
            key={i}
            aria-hidden="true"
            className={cn("min-w-0 flex-1 rounded-[1px]", bar.gapBefore && "ml-1")}
            style={{ height: "2px", background: "var(--line-strong)" }}
          />
        ),
      )}
    </div>
  );
}

/** How many dots a runway column draws before it counts the rest in figures.
 *  Five 8px dots and their gaps fill the column's 80px; the sixth would have
 *  to shrink them, and a dot that changes size stops being one unit. */
const RUNWAY_DOTS = 5;

/**
 * The runway — the deadline content's drawn element, and the pulse's only
 * chart that looks FORWARD: what is already late, then each day of the soon
 * window on its own, then everything past it.
 *
 * A dot per deadline, not a bar per bucket. The deadline cell has always said
 * its counts are units and not proportions ("two overdue beside ten later is
 * not a 1:5 wash of red"), and a unit chart is that sentence drawn: on the
 * board this was built for — one deadline, two days out — a bar chart draws
 * one full-height bar and four empty bins, which reads as "everything is due",
 * while one dot on the +2 column reads as the one thing it is. Height is a
 * count you can recount, not a scale.
 *
 * The whole column is the control, the way the whole cell is the trigger
 * upstairs, and each one narrows the worklist to exactly the rows its dots
 * stand for.
 */
function Runway({
  bins,
  onSelect,
}: {
  bins: DeadlineBin[];
  onSelect: (bin: DeadlineBin) => void;
}) {
  // One template, two grids (dots, then labels), so a label can never drift
  // off the column it names.
  const columns = { gridTemplateColumns: `repeat(${bins.length}, minmax(0, 1fr))` };
  // The chart reserves exactly the tallest stack it has to draw — the same
  // peak-scaling DayBars does, and the reason this content is dots at all: a
  // fixed 5-dot column spent ~50px of an empty panel proving that a board with
  // one deadline could have had five. 28px keeps the shortest column a
  // comfortable target; the extra rung is the "+N" figure's line.
  const peak = Math.min(Math.max(...bins.map((bin) => bin.count), 1), RUNWAY_DOTS);
  const column = {
    height: `${Math.max(28, peak * 12 + 4 + (bins.some((bin) => bin.count > RUNWAY_DOTS) ? 12 : 0))}px`,
  };
  const label = (bin: DeadlineBin) =>
    bin.kind === "overdue"
      ? "overdue"
      : bin.kind === "later"
        ? "later"
        : bin.days === 0
          ? "today"
          : `+${bin.days} d`;
  // The inks the card tags already wear, on the panel's own `--surface`
  // ground: red-ink 10.04:1 dark / 6.47:1 light, amber 8.87:1 / 5.02:1, the
  // ramp grey 9.14:1 / 5.35:1 (WCAG 2.1, measured 2026-08-13 — the bar is
  // 3:1 for non-text). Nothing rides on hue alone: every column is named
  // beneath it, counted in its own accessible name, and named again in the
  // list below.
  const ink = (bin: DeadlineBin) =>
    bin.kind === "overdue"
      ? "var(--red-ink)"
      : bin.kind === "later"
        ? "var(--text-dim)"
        : "var(--amber)";
  const name = (bin: DeadlineBin) =>
    bin.kind === "overdue"
      ? `overdue — ${bin.count}`
      : bin.kind === "later"
        ? `due after ${DUE_SOON_WORDS} — ${bin.count}`
        : `${duePhrase(bin.days)} — ${bin.count}`;

  return (
    <div className="mt-3">
      <div
        role="group"
        aria-label="Deadlines by time left, overdue first — select a column to filter the worklist"
        className="grid gap-1 border-b border-line-soft"
        style={columns}
      >
        {bins.map((bin, i) =>
          bin.count > 0 ? (
            <button
              key={i}
              type="button"
              title={name(bin)}
              aria-label={`${name(bin)} — show these on the board`}
              onClick={() => onSelect(bin)}
              style={column}
              className="flex flex-col-reverse items-center gap-1 rounded-t-md pb-1 transition-colors hover:bg-surface-2 motion-reduce:transition-none"
            >
              {Array.from({ length: Math.min(bin.count, RUNWAY_DOTS) }, (_, dot) => (
                <span
                  key={dot}
                  className="pulse-dot h-2 w-2 shrink-0 rounded-full"
                  style={{ background: ink(bin), ["--i" as string]: i * 2 + dot }}
                />
              ))}
              {bin.count > RUNWAY_DOTS ? (
                <span className="tabular text-[10px] leading-none text-dim">
                  +{bin.count - RUNWAY_DOTS}
                </span>
              ) : null}
            </button>
          ) : (
            // An empty column keeps a hairline on the baseline: the runway's
            // gaps are the reassurance ("nothing lands tomorrow"), so they
            // have to be visible as gaps rather than as missing columns.
            <div
              key={i}
              aria-hidden="true"
              style={column}
              className="flex flex-col-reverse items-center pb-1"
            >
              <span className="h-px w-3" style={{ background: "var(--line-strong)" }} />
            </div>
          ),
        )}
      </div>
      <div className="mt-1 grid gap-1 text-center text-[10px] leading-snug text-dim" style={columns}>
        {bins.map((bin, i) => (
          <span key={i} className="min-w-0 truncate">
            {label(bin)}
          </span>
        ))}
      </div>
    </div>
  );
}

/** The panel's one-line figure sentence — the caption idiom, scaled up. */
function FigureLine({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted">{children}</p>;
}

/** The trailing usage hint, once per content, same sentence shape. */
function Hint({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-[11px] leading-snug text-dim">{children}</p>;
}

export function PulseDetail({
  panelRef,
  kind,
  today,
  momentum,
  age,
  deadline,
  provenance,
  onFilter,
  onClose,
}: {
  panelRef: RefObject<HTMLDivElement | null>;
  kind: PulseDetailKind;
  today: string;
  /** Filed-per-day counts, oldest first — the band's own derivation. */
  momentum: { days: number[]; thisWeek: number; lastWeek: number };
  /** Open rows per day of age (index 0 = today … index cap = the quiet
   *  overflow), plus the top of the ageing curve, named. */
  age: {
    bins: number[];
    openTotal: number;
    quiet: number;
    oldest: { company: string; age: number }[];
  };
  /** The deadline cell's own derivation, bucketed once upstairs: the counts
   *  its caption speaks, the rows it names, and those rows binned into the
   *  runway this content draws. */
  deadline: { pulse: DeadlinePulse; runway: DeadlineBin[] };
  provenance: {
    mail: number;
    hand: number;
    total: number;
    needsReview: number;
    lastFromMail: string | null;
  };
  onFilter: (filter: PulseFilter) => void;
  onClose: () => void;
}) {
  let content: ReactNode;

  if (kind === "momentum") {
    const { days, thisWeek, lastWeek } = momentum;
    const filed = days.reduce((a, b) => a + b, 0);
    const best = bestDay(days);
    const bestDate = best ? isoDaysAgo(today, best.daysAgo) : null;
    const streak = currentStreak(days);
    const windowStart = isoDaysAgo(today, days.length - 1);
    content = (
      <>
        {/* One figures line, stated once: the caption above already carries
            this-week-vs-last, so the panel adds what the cell could not fit —
            the window total, the best day by name, the live streak. */}
        <FigureLine>
          <span className="tabular text-strong">{filed}</span> filed in {days.length} days
          {best && bestDate ? (
            <>
              {" · "}best <span className="tabular text-strong">{best.count}</span> on{" "}
              {dayName(bestDate)}
            </>
          ) : null}
          {streak >= 2 ? (
            <>
              {" · "}
              <span className="tabular text-strong">{streak}</span>-day streak
            </>
          ) : null}
        </FigureLine>
        <div className="mt-3">
          <DayBars
            ariaLabel={`Filed per day, this week ${thisWeek} vs last week ${lastWeek} — select a day to filter the worklist`}
            bars={days.map((count, i) => {
              const daysAgo = days.length - 1 - i;
              const date = isoDaysAgo(today, daysAgo);
              return {
                count,
                color: i >= days.length - 7 ? "var(--viz-rules)" : "var(--text-dim)",
                name: date ? `${dayName(date)} — ${count} filed` : `${count} filed`,
                // A breath before each Monday: the weekday structure Ayush
                // asked the daily view for, drawn as space.
                gapBefore: date !== null && i > 0 && weekdayOf(date) === 0,
                onSelect:
                  date !== null ? () => onFilter({ kind: "day", date }) : undefined,
              };
            })}
          />
          <div className="mt-1 flex justify-between text-[10px] leading-snug text-dim">
            <span>{windowStart ? shortDate(windowStart) : ""}</span>
            <span>today</span>
          </div>
        </div>
        <Hint>select a day to see what you filed</Hint>
      </>
    );
  } else if (kind === "age") {
    const { bins, openTotal, quiet, oldest } = age;
    const oldestAge = oldest[0]?.age ?? 0;
    /** Rows 10–13 days old — quiet's doorstep, the actionable early warning. */
    const soonQuiet = bins.slice(QUIET_AFTER_DAYS - 4, QUIET_AFTER_DAYS).reduce((a, b) => a + b, 0);
    content = (
      <>
        <FigureLine>
          <span className="tabular text-strong">{openTotal}</span> open · oldest{" "}
          <span className="tabular text-strong">{oldestAge}</span> d
          {quiet > 0 ? (
            <span className="text-review">
              {" · "}
              <span className="tabular">{quiet}</span> quiet 2 wk+
            </span>
          ) : null}
          {soonQuiet > 0 ? (
            <>
              {" · "}
              <span className="tabular">{soonQuiet}</span> go quiet within 4 d
            </>
          ) : null}
        </FigureLine>
        <div className="mt-3">
          <DayBars
            ariaLabel="Open applications by days since filed, oldest left — select a bin to filter the worklist"
            bars={[...bins].reverse().map((count, i) => {
              const binAge = QUIET_AFTER_DAYS - i;
              if (binAge >= QUIET_AFTER_DAYS) {
                return {
                  count,
                  color: "var(--amber)",
                  name: `open 2 wk or more — ${count}`,
                  onSelect: () => onFilter({ kind: "quiet" }),
                };
              }
              const date = isoDaysAgo(today, binAge);
              return {
                count,
                color: binAge >= 7 ? "var(--text-dim)" : "var(--viz-rules)",
                name: `filed ${binAge === 0 ? "today" : `${binAge} d ago`} — ${count} open`,
                // The quiet threshold, drawn as space: the amber overflow bin
                // stands apart from the day-by-day curve.
                gapBefore: binAge === QUIET_AFTER_DAYS - 1,
                onSelect:
                  date !== null
                    ? () => onFilter({ kind: "day", date, openOnly: true })
                    : undefined,
              };
            })}
          />
          <div className="mt-1 flex justify-between text-[10px] leading-snug text-dim">
            <span>2 wk+</span>
            <span>filed today</span>
          </div>
        </div>
        {oldest.length > 0 ? (
          <div className="mt-3">
            <p className="label-caps">longest waiting</p>
            <ul className="mt-1 space-y-0.5">
              {oldest.map((row, i) => (
                <li key={i}>
                  <button
                    type="button"
                    aria-label={`${row.company}, open ${row.age} days — show it on the board`}
                    onClick={() => {
                      const date = isoDaysAgo(today, row.age);
                      if (date !== null) onFilter({ kind: "day", date, openOnly: true });
                    }}
                    className="-mx-2 flex w-[calc(100%+1rem)] items-baseline gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-surface-2 motion-reduce:transition-none"
                  >
                    <span className="min-w-0 truncate text-strong">{row.company}</span>
                    <span className="tabular ml-auto shrink-0 text-muted">{row.age} d</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <Hint>select a day or a row to see it on the board</Hint>
      </>
    );
  } else if (kind === "deadline") {
    const { pulse, runway } = deadline;
    /** Long enough to show a working week's worth of deadlines, short enough
     *  that the panel never becomes the worklist it filters. */
    const listed = pulse.rows.slice(0, 5);
    content = (
      <>
        {/* The one figure the cell's caption deliberately does not carry: how
            many deadlines this board is tracking at all. The overdue count
            keeps its place beside it because it is the one state that must not
            be missed; the soon count does NOT — the caption says it a line
            above, the runway draws it in amber and the list dates it, and a
            fourth telling was the panel reading as padding. */}
        <FigureLine>
          <span className="tabular text-strong">{pulse.total}</span> with a deadline
          {pulse.overdue > 0 ? (
            <span className="text-reject-ink">
              {" · "}
              <span className="tabular">{pulse.overdue}</span> overdue
            </span>
          ) : null}
        </FigureLine>
        <Runway
          bins={runway}
          onSelect={(bin) =>
            onFilter(
              bin.kind === "day"
                ? { kind: "dueIn", days: bin.days }
                : { kind: "due", state: bin.kind === "overdue" ? "overdue" : "ahead" },
            )
          }
        />
        <div className="mt-3">
          <p className="label-caps">what is due</p>
          <ul className="mt-1 space-y-0.5">
            {listed.map((row, i) => (
              <li key={i}>
                {/* Filtered by days-left, not by name: the worklist takes sets,
                    and "everything due the same day as this" is the honest set
                    a row belongs to — the same one its runway column counts. */}
                <button
                  type="button"
                  aria-label={`${row.company}, ${duePhrase(row.daysLeft)} — show it on the board`}
                  onClick={() => onFilter({ kind: "dueIn", days: row.daysLeft })}
                  className="-mx-2 flex w-[calc(100%+1rem)] items-baseline gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-surface-2 motion-reduce:transition-none"
                >
                  <span className="min-w-0 truncate text-strong">{row.company}</span>
                  <span
                    className={cn(
                      "tabular ml-auto shrink-0",
                      row.daysLeft < 0
                        ? "text-reject-ink"
                        : row.daysLeft <= DUE_SOON_DAYS
                          ? "text-review"
                          : "text-muted",
                    )}
                  >
                    {duePhrase(row.daysLeft)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {pulse.rows.length > listed.length ? (
            // Not a control: these are the furthest-out rows, and the runway's
            // "later" column above already opens exactly this set.
            <p className="mt-1 text-[11px] leading-snug text-dim">
              <span className="tabular">+{pulse.rows.length - listed.length}</span> more further out
            </p>
          ) : null}
        </div>
        <Hint>select a column or a row to see those applications</Hint>
      </>
    );
  } else {
    const { mail, hand, total, needsReview, lastFromMail } = provenance;
    const groups = [
      mail > 0
        ? {
            key: "mail",
            swatch: "var(--viz-setfit)",
            label: "from your mail",
            note: "filed for you from Gmail",
            count: mail,
            onSelect: () => onFilter({ kind: "source", source: "mail" as const }),
          }
        : null,
      hand > 0
        ? {
            key: "hand",
            swatch: "var(--text-dim)",
            label: "by hand",
            note: "you added these yourself",
            count: hand,
            onSelect: () => onFilter({ kind: "source", source: "hand" as const }),
          }
        : null,
    ].filter((group) => group !== null);
    content = (
      <>
        <FigureLine>
          <span className="tabular text-strong">{mail}</span> of{" "}
          <span className="tabular">{total}</span> arrived from your mail
        </FigureLine>
        {/* The cell's h-1.5 bar at reading size — same segments, same inks. */}
        <div
          role="img"
          aria-label={`${mail} of ${total} from your mail, ${hand} by hand`}
          className="mt-3 flex h-2 gap-px overflow-hidden rounded-full bg-surface-2"
        >
          {groups.map((group, i) => (
            <span
              key={group.key}
              className="pulse-seg-x h-full"
              style={{
                width: `${(group.count / total) * 100}%`,
                background: group.swatch,
                ["--i" as string]: i,
              }}
            />
          ))}
        </div>
        <ul className="mt-3 space-y-0.5">
          {groups.map((group) => (
            <li key={group.key}>
              {/* The answer to "what are the remaining 5?", made walkable:
                  each provenance group opens as the rows themselves. */}
              <button
                type="button"
                aria-label={`${group.label}, ${group.count} — show these on the board`}
                onClick={group.onSelect}
                className="-mx-2 flex w-[calc(100%+1rem)] items-baseline gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-surface-2 motion-reduce:transition-none"
              >
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 self-center rounded-full"
                  style={{ background: group.swatch }}
                />
                <span className="shrink-0 font-medium text-strong">{group.label}</span>
                <span className="min-w-0 truncate text-dim">— {group.note}</span>
                <span className="tabular ml-auto shrink-0 text-strong">{group.count}</span>
              </button>
            </li>
          ))}
          {needsReview > 0 ? (
            <li>
              <Link
                href="/dashboard#needs-classification"
                className="-mx-2 flex w-[calc(100%+1rem)] items-baseline gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors hover:bg-surface-2 motion-reduce:transition-none"
              >
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 self-center rounded-full"
                  style={{ background: "var(--amber)" }}
                />
                <span className="shrink-0 font-medium text-review">held for review</span>
                <span className="min-w-0 truncate text-dim">— mail waiting for your review</span>
                <span className="tabular ml-auto shrink-0 text-strong">{needsReview} →</span>
              </Link>
            </li>
          ) : null}
        </ul>
        {lastFromMail !== null ? (
          <p className="mt-2 text-[11px] leading-snug text-dim">
            last arrived from your mail · {shortDate(lastFromMail)}
          </p>
        ) : null}
        <Hint>select a group to see those applications</Hint>
      </>
    );
  }

  return (
    <div
      ref={panelRef}
      id="pulse-detail"
      data-testid="pulse-detail"
      role="region"
      aria-label={TITLES[kind]}
      tabIndex={-1}
      className={cn(
        "pulse-panel absolute top-full z-30 mt-2 max-h-80 w-[26rem] max-w-full overflow-y-auto rounded-xl border border-line bg-surface p-4 shadow-xl outline-none",
        ANCHOR[kind],
      )}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="label-caps min-w-0 truncate">{TITLES[kind]}</p>
        <button
          type="button"
          aria-label="Close detail"
          onClick={onClose}
          className="-m-1 shrink-0 rounded-md p-1 text-dim transition-colors hover:bg-surface-2 hover:text-strong motion-reduce:transition-none"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      {content}
    </div>
  );
}
