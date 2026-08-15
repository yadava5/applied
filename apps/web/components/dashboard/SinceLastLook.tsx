"use client";

import { ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { daysBetween } from "@/lib/dashboard/age";
import { boardColumns } from "@/lib/dashboard/board";
import { dueInfo, duePhrase } from "@/lib/dashboard/deadline";
import {
  changesSince,
  groupChanges,
  momentLabel,
  momentShortLabel,
  parseLastLook,
  snapshotOf,
  type ChangeEntry,
  type ChangeRow,
} from "@/lib/dashboard/lastLook";
import {
  ownChanges,
  readLastLookRaw,
  serverLastLookRaw,
  subscribeLastLook,
  writeLastLook,
} from "@/lib/dashboard/lastLookStore";
import { STAGES } from "@/lib/dashboard/summary";
import { useLocalToday } from "@/lib/dashboard/useLocalToday";

/**
 * The change ledger — the dashboard's answer to "what happened while I was
 * away", which a board of identical cards cannot express: an overnight row and
 * a three-week-old one look exactly the same.
 *
 * It is a LEDGER, not a badge and not a filter, and that is the whole design
 * argument. A badge on every changed row makes you scan four columns and 200
 * cards to find the two that moved. A filter is a mode you have to enter,
 * remember you are in, and leave. A ledger answers the question in the place
 * you already look first, names the rows, and then gets out of the way — the
 * counts group by kind (which the board cannot show) and the entries name
 * individuals (which the counts cannot), the same two-level shape the pulse
 * strip's deadline cell already uses.
 *
 * A CHIP ON THE COMMAND ROW — the shape, and why it is this shape
 * ----------------------------------------------------------------
 * The two levels are literally two levels: the arrival CHIP carries the
 * counts, and opening it names the rows. The chip is the command row's
 * notification centre (SyncBar's `since` slot, overlaid on the row's centre
 * at `lg`+ — see the placement story below), and every state of it occupies
 * the same line box, so no state change can move the board. The dedicated
 * notice line it once held is a line the worklist got back — twice.
 *
 * THE PLATE, CENTRED ON THE BAR (#212) — the chip is a small member of the
 * row's own control chrome: a hairline `--line-strong` frame, uniform
 * rounding, `--surface` fill — the Sync button's and the `⋯`'s vocabulary
 * one size down. It wore a bespoke construction before (a 2px accent rule
 * down one edge with the corners squared along it, mirrored by the panel
 * across its top, a connector stem drawn between them), and the owner
 * rejected that on sight: NO other overlay in this app wears an accent
 * edge, a squared corner or a connector — RowActionsMenu, PulseDetail, the
 * beta pill's panel and Dialog all say "I belong to my trigger" with plain
 * chrome and proximity — so the one that drew its attachment read as
 * another product's control grafted onto the row. State is said by ink now,
 * not by construction: the loud chip carries a `--stage-applied` dot (the
 * board's own column-dot vocabulary — StageWord, the pulse panel's
 * swatches), counts in full-strength ink and a chevron; quiet and first-run
 * wear the same chip in dim ink with no dot and no chevron — the
 * notification centre in its empty condition, and the chevron's absence is
 * what says there is nothing to open.
 *
 * The overlay is the placement's fourth form, each earlier one measured out
 * of existence. Flush after the subtitle the quiet line read as the totals'
 * caption (#196). Hung off the row's far end (`ml-auto`) it read as a
 * trailing annotation on the sync cluster — the same defect mirrored.
 * Centred in the row's LEFTOVER middle it held the slot's centre perfectly
 * while wandering against the bar — 130px right of the bar's centre at
 * 1024, 137px left of it at 1280, because the flanks (title ~283px, sync
 * cluster ~556px) are that asymmetric — and the moment the row wrapped
 * (which the fixture twin does at 1024) the slot itself moved and carried
 * the plate back to a line-end. A dedicated full-width line under the row
 * held the bar's centre at last — and spent 26px of the worklist's height
 * doing it, which session-edge.spec's floor (613px at 1024×768, the #172
 * refund) rejected on the first CI run: that height is the board's, not
 * this chip's.
 *
 * So at `lg`+ the chip is out of flow entirely: SyncBar overlays it on the
 * header row (`inset-0`, so the overlay's box is the row's box), where
 * `mx-auto` centres the plate on the bar — plate centre == <main>'s centre
 * to the pixel — and the omnibox position costs the worklist nothing by
 * construction. Over the row, the plate must hold the row's OWN line, so at
 * `lg`+ it always wears its compact form ("Nothing new" / "4 changes"): the
 * `max-lg` guards on every wide rung below are that rule, and they are what
 * keep it clear of both neighbours — measured at 1024 (`next start`,
 * 2026-08-14), the compact plate stands ~72px clear of the totals and
 * ~74px clear of the cluster, against the 12px flex-gap that #196 called a
 * caption. Where a neighbour still reaches past the bar's centre — the
 * fixture twin's pill-furnished row at 1024 is the one measured case — the
 * plate yields exactly what the neighbour forces and no more (`placePlate`,
 * a 23–26px slide there), because a centred plate OVER a control is worse
 * than one standing 26px off the centre it means. For the LOUD state the
 * compact rule spends nothing the reader had — measured on ba2a653, the
 * in-row slot (≤500px at 1440) never reached the kinds rung (26rem) or the
 * moment rung (34rem), so desktop always showed "N changes" — and the
 * kinds, moment and scope note ride one press away in the panel, which says
 * all of it at every width. The QUIET moment is the exception with its own
 * three-rung ladder (see the render): compact-only shipped once and removed
 * a sentence main was showing. Below `lg` the shell is unlocked and no
 * floor applies: the same node is an in-flow line at the stacked header's
 * end, full ladder active, reserved by the server pass so hydration never
 * moves the board.
 *
 * Space inside the chip varies with the viewport and its row-mates, so the
 * loud state is container-adaptive rather than truncated: per-kind counts
 * ("2 filed · 1 moved") when the chip is wide enough to say them, the total
 * ("3 changes") when it is not — and the opened panel names the rows either
 * way, so nothing is ever clipped mid-claim.
 *
 * The NAMES are an overlay, not a reflow: opening the chip floats the panel
 * over the board (absolutely positioned under the row) instead of pushing the
 * board down. The old block grew with the news — three groups of four named
 * rows plus "+N more" is ~300px on a laptop — so the busiest morning was the
 * morning the board itself got pushed out of view. Now not even the asked-for
 * expansion moves the work surface.
 *
 * An overlay still has to say WHERE IT CAME FROM, and this one did not: it
 * took the header row's `right-0`, so a chip sitting mid-row (measured at
 * x=523 in a row ending at 1256) opened a 608px panel starting at x=648 —
 * beginning 29px to the RIGHT of the trigger's own right edge, touching
 * nothing that produced it, and swallowing the pulse band's two right-hand
 * cells whole. It is hung on the chip now: `placePanel` puts the panel's
 * CENTRE on the chip's, so the sheet drops straight out of the plate with
 * equal overhang on both sides, at the pulse panel's own 26rem measure —
 * the two sheets that can open over the band are the same width, and 26rem
 * covers less of the band than the 38rem and 30rem slabs that preceded it.
 * It still covers the band's middle, and that is the accepted trade — the
 * band is a summary of the same story the ledger is spelling out, it is one
 * press from returning, and coverage bounded to the middle beats the right
 * 60% of the band disappearing. Measured on this build at 1024, the four
 * band cells left to right (`next start`, 2026-08-14): signed-in row
 * 13/100/100/13 covered, furnished twin 33/100/94/0 (its chip rides
 * placePlate's slide, so the sheet slides with it) — the outer pair clear
 * or nearly so on both surfaces, where the 30rem sheet spent 30% of each
 * flank on the signed-in row and the old right-hung 38rem read
 * 0/27/100/100.
 *
 * Centred is the owner's call, taken over the left-edge alignment that
 * shipped first: a notification centred on the bar reads as the row's own
 * drawer when what it opens is centred under it too, and a 480px sheet
 * whose left edge alone lines up with a ~120px chip looks hung off one
 * corner of it. The beta pill does exactly this — its panel rides
 * `left-1/2 -translate-x-1/2` over its trigger — so a shared centre line is
 * already how this app says "mine" when edges cannot align. Nothing is
 * DRAWN between the two anymore; see the panel's note for why the
 * accent-rule-and-stem connector went.
 *
 * The expansion is never remembered. Restoring it on the next load would
 * re-create exactly the defect this shape removes — the server cannot know it
 * was open, so the panel would pop over the board unasked after hydration.
 *
 * Three states, all of them real:
 *
 *   · **first run** — no marker in this browser yet. It says so. It never
 *     counts the board you already have as news;
 *   · **quiet** — nothing changed, stated against the moment it is comparing
 *     from. "Nothing new since Aug 3" on August 11 is not filler: it says your
 *     pipeline has been silent for eight days. Quiet and first-run wear the
 *     dormant plate — grey rule, dim ink, no chevron (see the plate note
 *     above for the placement history: caption on the totals in #196,
 *     trailing annotation on the cluster in #212);
 *   · **changed** — the counts on the same plate, its rule in the accent, the
 *     names one press away. The contrast between a dim dormant plate and one
 *     edged in full-strength accent with counts in full ink is the signal;
 *     most opens are quiet, and the loud state has to look different from
 *     across the room.
 *
 * WHEN THE MARKER ADVANCES — the decision this feature lives or dies on:
 *
 *   1. It NEVER advances on mount while there is something to report. Advancing
 *      on mount is the classic way this ships broken: the state is consumed
 *      before the reader has read it, and every visit reports nothing.
 *   2. It advances when the reader says so ("Mark as seen"). One explicit act,
 *      which means an accidental navigation, a tab switch, a reload or a second
 *      tab can never destroy an unread digest. `pagehide`/unmount advancing was
 *      considered and rejected for exactly that: it silently spends the state,
 *      and there is no undo for information you were never shown.
 *   3. It refreshes ITS ROWS — never its moment — when the diff is empty. There
 *      is nothing to destroy in that case, and it keeps the snapshot current
 *      (rows that fell out of the loaded page, deadlines you typed yourself,
 *      status changes inside one column) without moving the "since" the reader
 *      is being told about.
 *
 * The moment is display-only and is never compared against a row's timestamp:
 * a browser clock a few minutes fast would otherwise hide the overnight rows
 * that the arrival sync files a second after this component mounts, which is
 * the single case the feature exists for. See `lib/dashboard/lastLook.ts`.
 *
 * SSR / no-JS: the marker is `localStorage`, which the server cannot read, so
 * `useSyncExternalStore`'s server snapshot is `null` and this has nothing to
 * SAY until hydration — no mismatch, and no board state depends on it. It
 * still occupies its line from the server pass; see `ArrivalLine`. With JS off
 * the dashboard is exactly the dashboard, minus one reading aid.
 */

/** The board's own accent per column word — the dot beside a stage here is the
 *  same dot as that column's heading, so a name points at where to look. */
const STAGE_COLORS = new Map(
  boardColumns(STAGES).map((column) => [column.label, column.color] as const),
);

/** The columns' own left-to-right order, for the panel's strip: the changed
 *  rows draw in the order their columns hold on the board, so the strip reads
 *  as the board in miniature rather than as a new axis to learn. */
const COLUMN_ORDER = new Map(
  boardColumns(STAGES).map((column, index) => [column.label, index] as const),
);

/** Entries later than this share one delay in the panel's entrance cascade:
 *  a 40-row morning must not spend a second arriving (25ms × the cap ≈ 300ms
 *  tail, inside the pulse bars' own ~400ms sweep), and everything past the
 *  tenth row is below the scroller's fold anyway. */
const CASCADE_CAP = 12;

function StageWord({ word }: { word: string }) {
  return (
    <span className="label-caps inline-flex shrink-0 items-center gap-1.5 text-muted">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: STAGE_COLORS.get(word) ?? "var(--stage-applied)" }}
        aria-hidden="true"
      />
      {word}
    </span>
  );
}

/** The deadline a change brought with it, in the same words and the same ink
 *  the card's own tag uses — never a second vocabulary for one fact, and never
 *  a second day either: `today` comes from `useLocalToday`, the one read the
 *  card tag and the pulse already bucket against. Read from the UTC day
 *  instead, this line said "due in 1d" beside a card reading "due in 2d" for
 *  every reader whose day differs from UTC. */
function DueNote({ dueAt, today }: { dueAt: string; today: string }) {
  const due = dueInfo(dueAt, today);
  if (!due) return null;
  const ink =
    due.state === "overdue" ? "text-reject" : due.state === "soon" ? "text-review" : "text-dim";
  return (
    <span className={`tabular shrink-0 font-mono text-[10px] ${ink}`}>
      {duePhrase(due.daysLeft)}
    </span>
  );
}

/**
 * The band's one line — the single piece of geometry this component promises,
 * and the fix for a measured defect rather than a wrapper for its own sake.
 *
 * Measured, on `next dev` at 1440×900: rendering nothing until the marker was
 * readable put the band on screen ~70 ms after first paint and moved every
 * card on the board down — 41.9 px in the quiet state, 118.9 px in the loud
 * one. A pointer that pressed a card inside that window released above it, so
 * the browser retargeted the `click` to the column's `<ul>` — the nearest
 * common ancestor of press and release — and the card's own handler never ran.
 * The card simply did not open. Five tests across this suite hit that race in
 * CI (three red, two flaky), and a real first click landing in the same window
 * is just as dead; this is a CLS defect, not a test-harness quirk.
 *
 * `h-[1lh]` is one line box of THIS element's own type, so the server's empty
 * line and every hydrated state are the same height by construction — they
 * stay the same height if the type scale moves, and nothing inside can grow
 * the box: an icon, a stamp in another face, or a control with padding all
 * overflow invisibly instead of pushing the board. (The `lh` unit predates
 * Tailwind v4's own browser baseline, so every browser that can render this
 * stylesheet supports it.) The rest of the contract is horizontal: children
 * never wrap — one flexible part truncates, everything else is `shrink-0` —
 * because a second line at 375px is the same defect at a narrower width.
 */
function ArrivalLine({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-[1lh] items-baseline gap-x-3 text-[13px] leading-snug">{children}</div>
  );
}

/**
 * One row of the ledger, in three lines: the NEWS, the role, then the record.
 *
 * The first line is who and where it landed — short, so the stage sits hard
 * against the name it describes. It used to be pushed to the panel's right
 * edge by `ml-auto` while the role ate the middle, and a row of "SimpliSafe"
 * with "● APPLIED" a hand's width away reads as two unrelated halves rather
 * than one claim; a long role pushed the stage onto a line of its own, so no
 * two entries broke in the same place. Adjacency is the fix, not alignment.
 *
 * The role gets the second line and the panel's whole measure. It wraps rather
 * than ellipsizing — its tail is what tells two requisitions at one employer
 * apart (see ApplicationCard) — and it carries no leading dash down here: the
 * line break already says it is subordinate to the name above it.
 *
 * The third line is the round-three ask made concrete ("very much details"):
 * everything else the loaded row can honestly say about this entry, and
 * nothing it cannot —
 *
 *   · **filed age** — "filed 12 d ago", the board's own stamp in the age
 *     panel's own words (`filed ${n} d ago` is DayBars' phrase verbatim). On
 *     a filed entry it is WHEN the news arrived; on a moved one it is how
 *     long the row took to get here — the one timing the diff can honestly
 *     claim, since the derivation cannot know when a move happened, only
 *     that it did (see lastLook.ts: `updated_at` was rejected as evidence);
 *   · **provenance**, filed entries only and only when `withSource` — "from
 *     your mail" / "by hand", the pulse band's exact vocabulary for the same
 *     fact. An arrival the sync filed and one you filed from another device
 *     are different news, and provenance is the one field `toChangeRow`
 *     widened for this line. The caller sets `withSource` only when the
 *     filed group is MIXED: on a board where everything arrives one way
 *     (the auto-filed account is the normal one) ten identical tails say
 *     nothing ten times, so the shared fact moves up into the group's
 *     heading and this line stays for the case where it distinguishes;
 *   · **the employer's count**, when it exceeds one — "3 at this employer".
 *     One company holds many applications here (that is the identity rule),
 *     and a new requisition at an employer you are already deep in reads
 *     differently from a first contact. Counted over the loaded rows, the
 *     same slice every claim in this panel reads (the scope note below the
 *     scroller is the shared caveat).
 *
 * All of it rides one dim 11px line, figures tabular in the text face — a
 * sentence about the row, not a machine stamp, so no mono (the moment chip
 * and DueNote keep mono because a bare timestamp is a machine value; "filed
 * 3 d ago" is prose). A row the board no longer carries (never, in practice:
 * every entry came out of `rows`) just drops the line.
 */
function EntryLine({
  entry,
  today,
  row,
  atEmployer,
  withSource,
  order,
}: {
  entry: ChangeEntry;
  today: string;
  /** The board row behind the entry — the detail line's source. */
  row: ChangeRow | undefined;
  /** Loaded applications at this entry's employer, this row included. */
  atEmployer: number;
  /** Name this arrival's provenance here (a mixed filed group). */
  withSource: boolean;
  /** Position in the panel's reading order, for the entrance cascade. */
  order: number;
}) {
  const facts: string[] = [];
  const age = row ? daysBetween(row.filed, today) : null;
  if (age !== null && age >= 0) {
    facts.push(age === 0 ? "filed today" : age === 1 ? "filed yesterday" : `filed ${age} d ago`);
  }
  if (withSource && row) {
    facts.push(row.source === "gmail" ? "from your mail" : "by hand");
  }
  if (atEmployer > 1) facts.push(`${atEmployer} at this employer`);
  return (
    <div className="ledger-entry" style={{ ["--i" as string]: Math.min(order, CASCADE_CAP) }}>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] leading-snug">
        <span className="font-medium text-strong">{entry.company}</span>
        {entry.from !== undefined ? (
          <>
            <span className="label-caps shrink-0 text-dim">{entry.from}</span>
            <ArrowRight className="h-3 w-3 shrink-0 self-center text-dim" aria-hidden />
            <span className="sr-only">to</span>
          </>
        ) : null}
        <StageWord word={entry.to} />
        {entry.dueAt ? <DueNote dueAt={entry.dueAt} today={today} /> : null}
      </p>
      <p className="text-[13px] leading-snug text-muted">{entry.position}</p>
      {facts.length > 0 ? (
        <p className="tabular mt-0.5 text-[11px] leading-snug text-dim">{facts.join(" · ")}</p>
      ) : null}
    </div>
  );
}

/** A text control at the line's own size: a bordered button would be half
 *  again as tall as the line it has to live inside. The padding is cancelled
 *  by an equal negative margin, so the press target is 26px while the box the
 *  band measures stays exactly one line. */
const LINE_CONTROL =
  "-my-1 rounded py-1 underline-offset-4 hover:text-strong hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong";

/** The chip every state wears — the row's own control chrome at line scale:
 *  hairline `--line-strong` frame, uniform rounding, `--surface` fill (the
 *  Sync button's construction one size down; `rounded-md` because the row's
 *  other 24px box, the receipt's dismiss, rounds there too). Which inks ride
 *  on it is the state's business: accent dot + full-strength counts when
 *  there is news, dim ink and no dot when there is none. The frame is
 *  `--line-strong` in BOTH registers — the panel's own measurement (see its
 *  header) applies unchanged at chip scale: `--line` composites to APCA
 *  Lc 0.0 on the dark ground (re-computed for #212), so a dormant chip
 *  framed in it would be a floating sentence, not an object. Dormant is said
 *  by the ink and the missing dot and chevron, not by a fainter frame.
 *  `-my-1`/`py-1` is LINE_CONTROL's trick with borders on: the box the band
 *  measures stays exactly one line while the chip paints ~26px, overflowing
 *  the ~38px row invisibly (ArrivalLine's contract). Its 22px of chrome
 *  (20px padding + 2px borders) is why every @container rung below sits 2rem
 *  above its pre-plate measurement — the rungs measure the SLOT, and the
 *  chip spends that before the sentence starts. */
const PLATE = "-my-1 rounded-md border border-line-strong bg-surface px-2.5 py-1";

/** Breathing room between the panel's bottom edge and the screen's, and the
 *  measure below which it stops giving way and scrolls instead. (There is no
 *  width twin of these anymore: the left-aligned panel needed a floor to
 *  decide when to stop trading width for alignment, and a CENTRED one never
 *  makes that trade — it slides along the row until it fits and only gives up
 *  width when the row itself is narrower than the sheet. See `placePanel`.) */
const PANEL_GUTTER = 16;
const PANEL_MIN_HEIGHT = 160;

export function SinceLastLook({
  rows,
  total,
  scope,
  storageKey,
}: {
  /** The loaded board, projected by `toChangeRow`. */
  rows: ChangeRow[];
  /** The account's true row count, when it can exceed what loaded. Omitted
   *  where the given rows ARE everything (the demo store) — same rule as
   *  `PipelineBoard`. */
  total?: number;
  /** Whose board this is: the user's id, or `"demo"`. A record written for
   *  someone else reads as no record, so a shared browser never reports one
   *  person's pipeline as another's. */
  scope: string;
  storageKey: string;
}) {
  const raw = useSyncExternalStore(
    subscribeLastLook,
    () => readLastLookRaw(storageKey),
    serverLastLookRaw,
  );
  /** Parsed once per stored string: `getSnapshot` has to return a stable value,
   *  so the store hands back the raw text and the parse happens here. */
  const record = useMemo(() => parseLastLook(raw, scope), [raw, scope]);
  /** The day a named row's deadline is measured against — the reader's own,
   *  swapped in as part of hydration exactly as the board does it. Read here
   *  rather than beside the render below because it is a hook, and hooks run
   *  before this component's early returns. */
  const today = useLocalToday();

  const settled = useRef(false);
  /** One clock read for the mount — the marker's label is "today"/"yesterday"
   *  relative to it. Read through a lazy initializer because the clock is
   *  impure and a render must not depend on when it happens to run. */
  const [now] = useState(() => Date.now());
  /** Whether the names are showing. Deliberately not persisted — see the
   *  header: a remembered panel would pop over the board unasked on the next
   *  load, because the server pass cannot know about it. */
  const [named, setNamed] = useState(false);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const plateRef = useRef<HTMLElement | null>(null);

  /**
   * Centre on the BAR; yield only what a neighbour forces — measured.
   *
   * `mx-auto` puts the plate on the bar's centre, which is the invariant.
   * But the overlay shares the row's line with the totals and the sync
   * cluster, and their widths are content ("214 filed · 32 open · 1 offer"
   * is 41px wider than the usual subtitle; the fixture twin's pill spends
   * 167px of right flank the real board does not have) — so the centred
   * position is checked against both neighbours here, placePanel-style,
   * and the plate slides exactly as far as the nearer one forces, never
   * further. Measured on the default twin at 1024 (`next start`,
   * 2026-08-14): the centred loud plate ends 3px past the cluster's left
   * edge, so it yields 26px (23 on the quiet form); every other measured arrangement yields 0 and
   * keeps the centre to the pixel. When both neighbours bind at once the
   * totals win — #196 is the defect with a number on it.
   *
   * A transform rather than a margin: it never re-enters layout, so the
   * @container measure and the row's wrap cannot feed back. Below `lg` the
   * chip is an in-flow line and this is a no-op (the transform is cleared,
   * then the guard returns). The panel follows the nudged plate because
   * `placePanel` reads bounding rects, which include transforms.
   */
  const placePlate = useCallback((plate: HTMLElement | null) => {
    plateRef.current = plate;
    if (!plate) return;
    // Cleared first so the measurement reads the stylesheet's own centred
    // position, not the slide a previous pass applied.
    plate.style.transform = "";
    const overlay = plate.closest("section")?.parentElement;
    const row = overlay?.parentElement;
    if (!overlay || !row || getComputedStyle(overlay).position !== "absolute") return;
    /** What the plate keeps from a same-line neighbour. Under the gate's
     *  24px floor for the arrangement that fits (the neighbours there are
     *  70px+ away and never bind); the crowded fixture twin is gated at 12. */
    const CLEAR = 16;
    const p = plate.getBoundingClientRect();
    const sameLine = (el: Element | null) => {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return b.width > 0 && p.top < b.bottom && b.top < p.bottom ? b : null;
    };
    const cluster = sameLine(row.querySelector("[data-sync-cluster]"));
    const totals = sameLine(row.querySelector("[data-sync-subtitle]"));
    let dx = 0;
    if (cluster) dx = Math.min(dx, cluster.left - CLEAR - p.right);
    if (totals) dx = Math.max(dx, totals.right + CLEAR - p.left);
    if (dx !== 0) plate.style.transform = `translateX(${dx}px)`;
  }, []);

  // Re-place on resize: both neighbours' edges are content-sized readings.
  // Form/state changes re-run the ref callback on their own.
  useEffect(() => {
    const onResize = () => placePlate(plateRef.current);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [placePlate]);

  /**
   * Centre the panel on the chip, and bound it to the row and the screen.
   *
   * The panel is anchored to the NOTIFICATION OVERLAY — the wrapper SyncBar
   * mounts this chip in (#212): `inset-0` over the header row at `lg`+, so
   * `top-full` is the ROW's bottom at every wrap state, and an in-flow line
   * at the stacked header's end below `lg`. It anchored to the header row
   * itself while the chip lived inside that row, because hanging it on the
   * chip's own line put a z-30 sheet over the Sync button whenever the row
   * wrapped (#172); the overlay's box IS the row's box, so the same
   * guarantee holds by construction. Before that it took the row's
   * `right-0` — a panel against the far right edge, 29px clear of the
   * trigger that opened it and detached from anything.
   *
   * This puts the panel's CENTRE on the PLATE's (`triggerRef` — the whole
   * plate is the trigger and its border box IS the chip's box), so the sheet
   * carries the same overhang either side of the chip and drops straight out
   * of it. It aligned LEFT EDGE to left edge until the owner overruled it
   * (see the header): a 480px sheet lining up with one corner of a ~120px
   * chip reads as hung off that corner, where the chip is a notification
   * centred on the bar and what it opens should be centred under it.
   *
   * The order is centre, CLAMP, then cap the width — not the left-aligned
   * build's "give up width before alignment", which a centred panel never
   * has to do: it slides along the row until it fits. `left` is bounded to
   * `[0, rowWidth - width]`, so the sheet can never run off either end, and
   * the width cap only bites where the ROW itself is narrower than the sheet
   * (below `lg`, where `calc(100vw-2rem)` has usually already done it).
   * Measured at `lg`+, the clamp is slack in every arrangement: a 416px
   * sheet centred at ~488 in a 976px row (1024, `next start`, 2026-08-14)
   * lands at left ≈ 280 with ~280px to spare on the right, so the centre is
   * exact and any nonzero delta is a defect, not a tolerance. It measured
   * exact on this build: |panel centre − chip centre| ≤ 0.01px at
   * 1024/1280/1440 on both demo surfaces (the signed-in arrangement
   * `?session=1` and the furnished twin), the 0.01 being the chip's own
   * fractional width. The clamp only engages below `lg` (a 416px sheet in a
   * 327px row at 375: left 0, and the two centres still coincide because
   * the stacked chip is centred on that row too).
   *
   * Height is capped against what is left of the screen, so a busy morning
   * scrolls inside the panel instead of running off the bottom of a shell
   * that must never scroll (#149). Everything is read against one
   * `offsetParent`, so there is no viewport arithmetic to disagree with a
   * scroll.
   *
   * A ref callback rather than a layout effect: it runs after insertion and
   * before paint (so the panel never flashes at the line's left edge first),
   * and it costs no `useLayoutEffect`, which warns on the server pass.
   */
  const placePanel = useCallback((panel: HTMLDivElement | null) => {
    panelRef.current = panel;
    const plate = triggerRef.current;
    // `offsetParent` is the notification overlay (SyncBar's wrapper); `row`
    // kept as the name because at `lg`+ its box IS the header row's.
    const row = panel?.offsetParent;
    if (!panel || !plate || !(row instanceof HTMLElement)) return;
    // Cleared first so this reads the measure the STYLESHEET asks for, not the
    // cap a previous pass left behind — the 26rem lives in one place.
    panel.style.maxWidth = "";
    // Bounding rects, not offsetLeft: the plate may be riding a translateX
    // from placePlate, which offsets ignore — measured on the fixture twin
    // at 1024, offsetLeft put the panel 26px right of the plate it centres on.
    const plateBox = plate.getBoundingClientRect();
    const centre = plateBox.left + plateBox.width / 2 - row.getBoundingClientRect().left;
    const rowWidth = row.clientWidth;
    // Read before the cap is re-applied, so this is the stylesheet's measure.
    const width = Math.min(panel.offsetWidth, rowWidth);
    const left = Math.max(0, Math.min(centre - width / 2, rowWidth - width));
    panel.style.left = `${left}px`;
    panel.style.maxWidth = `${rowWidth - left}px`;
    panel.style.maxHeight = `${Math.max(
      PANEL_MIN_HEIGHT,
      window.innerHeight - panel.getBoundingClientRect().top - PANEL_GUTTER,
    )}px`;
  }, []);

  // Re-place on resize: every number above is a measurement, and the row
  // re-wraps at `lg`. Listening only while the panel is open, like the
  // dismissal handlers below.
  useEffect(() => {
    if (!named) return;
    const onResize = () => placePanel(panelRef.current);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [named, placePanel]);

  // The panel is an overlay, so it gets an overlay's exits — the same three
  // RowActionsMenu earned the hard way (see its header): Escape (which hands
  // focus back to the trigger, for the keyboard user who opened it), a click
  // anywhere outside (which does NOT move focus — yanking it from whatever
  // the reader just clicked is hostile), and the toggle itself. Listeners
  // exist only while the panel is open; both pointerdown and mousedown are
  // registered because environments differ in which they deliver first.
  useEffect(() => {
    if (!named) return;
    const onOutside = (event: Event) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setNamed(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNamed(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onOutside, true);
    document.addEventListener("mousedown", onOutside, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onOutside, true);
      document.removeEventListener("mousedown", onOutside, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [named]);

  const partial = total !== undefined && rows.length < total;
  const entries = useMemo(
    // `ownChanges()` is a live set, not a dependency: every write that adds to
    // it also rewrites the stored record, which is what re-runs this.
    () => (record === null ? [] : changesSince(rows, record, ownChanges())),
    [rows, record],
  );
  const groups = useMemo(() => groupChanges(entries), [entries]);

  useEffect(() => {
    if (settled.current) return;
    settled.current = true;
    // Read storage rather than trusting the rendered `record`: on the hydration
    // pass `useSyncExternalStore` is still serving the server's `null`, and
    // laying a fresh baseline over a real marker would silently destroy the
    // digest it exists to protect.
    const stored = parseLastLook(readLastLookRaw(storageKey), scope);
    if (stored === null) {
      writeLastLook(storageKey, {
        ...snapshotOf(rows, scope, Date.now(), partial),
        seed: true,
      });
      return;
    }
    // Rule 3: nothing to report → fold the board in, leave the moment alone.
    if (changesSince(rows, stored, ownChanges()).length === 0) {
      writeLastLook(storageKey, snapshotOf(rows, scope, stored.at, partial));
    }
  }, [rows, record, scope, storageKey, partial]);

  const scopeNote = partial ? `newest ${rows.length} of ${total} rows` : null;

  /**
   * This browser had no marker until this very visit: the only record on disk
   * is the baseline THIS mount laid down (`seed`, written no earlier than this
   * render's clock read). Derived rather than held in state — a `setState` in
   * an effect is an eslint error here, and deferring it off the effect body
   * does not survive: the write re-runs the effect, whose cleanup then cancels
   * the very update it was deferring. Reading the record answers the question
   * directly, and reading `at` as well is what keeps a seed record from a
   * PREVIOUS visit from flashing "no earlier visit" before the effect folds it
   * in.
   */
  const seeded = record !== null && record.seed === true && record.at >= now;

  // Nothing to say yet: the server pass, and the instant before the marker is
  // read. The line is still held open — rendering nothing here is what moved
  // the whole board after first paint (see `ArrivalLine`). Storage that is
  // blocked outright never resolves past this, and one invisible line is the
  // whole cost of that case.
  if (record === null) {
    return (
      <div data-testid="since-last-look-reserve" aria-hidden="true">
        <ArrivalLine>&nbsp;</ArrivalLine>
      </div>
    );
  }

  if (seeded) {
    return (
      <section
        data-testid="since-last-look"
        aria-label="Changes since your last visit"
        className="w-full @container"
      >
        <ArrivalLine>
          {/* The clause that carries the fact is the whole sentence on a
              tight chip. One sentence, two lengths — never two lines — and
              the short rung a prefix of the long, so no width gets a
              differently-worded claim.

              The rung earned its keep when this chip lived inside the header
              row, whose wrap boundaries collapsed the slot to 168px at 1080
              and 161px at 1240 (8px sweep, 2026-08-13) and cost a fixed
              sentence up to 66px to the ellipsis ("…in this brows"). On its
              own full-width line (#212) the container is the bar and clears
              every rung at `lg`+; the ladder now works below `lg`, where the
              bar is a phone's. The old @34rem tail ("— from your next one,
              this line names what changed") went in the #200 sweep: roadmap
              prose explaining the control.

              The rung is 2rem above its pre-plate measurement (@[16rem] →
              @[18rem]): the rungs measure the CONTAINER, and the plate
              spends 23px of it on chrome before the sentence starts —
              re-swept at 8px steps, 1024→1440 plus 375/768, after the move
              (`next start`, headless Chrome, 2026-08-14): 0px lost at every
              step on both rungs.

              The dormant chip, centred on the bar (#212 — see the header):
              the same object as the loud chip, dim ink, no dot, no chevron
              because there is nothing to open. */}
          <p ref={placePlate} className={`${PLATE} mx-auto min-w-0 truncate text-dim`}>
            {/* `max-lg` on every wide rung here and below: at `lg`+ the chip
                overlays the row's own line, where only a compact form has
                measured clearance from the totals and the cluster — the
                container is the full bar there, so width alone would say yes
                to sentences the row cannot host. For THIS tail the
                arithmetic is terminal: the full sentence is ~250px of text
                (273 with the plate's chrome) against the 244px between the
                totals and the cluster at 1024 — it cannot fit even at zero
                clearance, so the overlay keeps the complete shorter claim
                and the qualifier stays implicit. The quiet state's moment,
                which unlike this tail has no other desktop home, gets its
                own short form instead — see below. */}
            No earlier visit
            <span className="hidden @[18rem]:max-lg:inline"> recorded in this browser</span>.
          </p>
        </ArrivalLine>
      </section>
    );
  }

  const moment = momentLabel(record.at, now);

  if (groups.length === 0) {
    return (
      <section
        data-testid="since-last-look"
        aria-label="Changes since your last visit"
        className="w-full @container"
      >
        <ArrivalLine>
          {/* The dormant chip, centred — same object as the first-run line
              above and as the loud chip below (#212, see the header for the
              placement history: caption on the totals in #196, trailing
              annotation on the cluster after it). */}
          <p ref={placePlate} className={`${PLATE} mx-auto min-w-0 truncate text-muted`}>
            {/* Same ladder as the first-run line above (rungs re-based +2rem
                for the plate's 23px of chrome, re-swept 2026-08-14), and the
                moment rides the SAME rung as the clause that introduces it:
                "Nothing new since" with the moment ellipsised is a sentence
                whose object has been cut off, which is the defect this pass
                exists to remove — not a shorter way of saying it. Measured
                pre-plate, this line lost 33px at 1240 and 26px at 1080.
                `18rem` minus the chrome clears the longest moment
                `momentLabel` can build ("yesterday 12:56 pm") as well as
                today's, with room to spare. */}
            Nothing new
            {/* The moment survives the overlay (#212 round 4): the quiet
                sentence's whole value is its SINCE, and the quiet plate has
                no press that could recover a dropped one — the first
                overlay build kept only "Nothing new" at `lg`+ and shipped a
                claim with its scope removed at exactly the widths where
                main had been showing the full sentence (measured on
                ba2a653: the wrapped twin at 1024 and the signed-in row at
                1280 both rendered it; the signed-in row at 1024 did not —
                its 220px slot never reached the old 16rem rung).
                Three renderings of one moment now, so no width says less
                than main said there:
                  · below `lg` — the container ladder, `momentLabel` whole;
                  · `lg`→`xl` — `momentShortLabel` on the loud chip's own
                    stamp idiom ("Nothing new · 4:32 am"): the day-word is
                    elided exactly where the rest still implies it (a bare
                    clock is today's), and the "·" is not a nicety — with
                    " since " kept, the WORST clock string ("12:58 am";
                    CI's timezone projects draw these) measured 196.6px
                    against a 244.5px window at 1024 and left 22.7px where
                    the #196 guard demands 24. The stamp saves ~24px and
                    holds the floor with ~9px to spare at the worst
                    string — a lesson in measuring the worst case, not the
                    clock you happened to load at;
                  · `xl`+ — `momentLabel` whole again: the window is 476px+
                    on every measured arrangement and the full sentence
                    centres with clearance to spare. */}
            <span className="hidden @[18rem]:max-lg:inline">
              {" "}
              since <span className="font-mono text-[11px] text-dim">{moment}</span>
            </span>
            {/* `--chip-tight` (set by SyncBar's overlay on the furnished
                twin, whose 169px window at 1024 cannot hold ANY moment
                form — the arithmetic is in that comment): there the bare
                claim stands in for this span, which is also what main
                rendered on that twin's unwrapped widths. */}
            <span className="hidden lg:max-xl:[display:var(--chip-tight,inline)]">
              {" "}
              ·{" "}
              <span className="font-mono text-[11px] text-dim">
                {momentShortLabel(record.at, now)}
              </span>
            </span>
            <span className="hidden xl:inline">
              {" "}
              since <span className="font-mono text-[11px] text-dim">{moment}</span>
            </span>
            {/* The slice this reading covers, where the chip has room for it
                — the board and the pulse carry the same disclosure, in the
                same words, at every width. */}
            {scopeNote ? (
              <span className="hidden text-dim @[36rem]:max-lg:inline"> · {scopeNote}</span>
            ) : null}
          </p>
        </ArrivalLine>
      </section>
    );
  }

  const Chevron = named ? ChevronUp : ChevronDown;
  /** The narrow chip's one number, summed from the same groups the wider chip
   *  prints one by one — two renderings of one reading, never two readings. */
  const counted = groups.reduce((sum, group) => sum + group.count, 0);

  // The panel's own derivations — plain per-render work (a board page is at
  // most a few hundred rows), placed here rather than in hooks so they cannot
  // collide with the early returns above.
  /** The board row behind each entry: the detail lines read the row itself
   *  (filed day, provenance), never a copy the entry would have to carry. */
  const rowById = new Map(rows.map((row) => [row.id, row] as const));
  /** Loaded applications per employer, for "N at this employer". */
  const perEmployer = new Map<string, number>();
  for (const row of rows) perEmployer.set(row.company, (perEmployer.get(row.company) ?? 0) + 1);
  /** The changed rows in board-column order — the strip's units, then run-
   *  length folded into its caption. `sort` is stable, so entries inside one
   *  column keep the groups' filed → moved → deadline reading order. */
  const landed = [...entries].sort(
    (a, b) =>
      (COLUMN_ORDER.get(a.to) ?? STAGES.length) - (COLUMN_ORDER.get(b.to) ?? STAGES.length),
  );
  const landedCounts: { label: string; count: number }[] = [];
  for (const entry of landed) {
    const last = landedCounts[landedCounts.length - 1];
    if (last !== undefined && last.label === entry.to) last.count += 1;
    else landedCounts.push({ label: entry.to, count: 1 });
  }
  /** Where each group starts in the panel's reading order — the entrance
   *  cascade runs across the whole list, not per group, so the third group's
   *  first row cannot land before the first group's last. */
  const groupStarts: number[] = [];
  {
    let acc = 0;
    for (const group of groups) {
      groupStarts.push(acc);
      acc += group.count;
    }
  }

  return (
    <section
      data-testid="since-last-look"
      aria-label="Changes since your last visit"
      /* `@container` works below `lg`, where the chip is an in-flow line and
         the bar is a phone's — at `lg`+ every wide rung carries a `max-lg`
         guard (the overlay must hold the row's own line; see the header), so
         the container's width is moot there. Full-width on purpose even
         though the plate inside is centred: an inline-size container cannot
         size from its content, so a shrink-wrapped section would collapse to
         nothing — the section keeps the bar's measure and the plate floats
         on its centre.

         Deliberately NOT `relative`: the names panel positions against the
         NOTIFICATION OVERLAY (SyncBar's wrapper is the nearest positioned
         ancestor), not this chip — anchored to the chip itself it once
         extended past <main>'s left edge, whose implicit overflow clip cut
         the first label off (see `placePanel` for the anchor's history). The
         plate supplies the horizontal anchor only, and `placePanel` measures
         it. */
      className="w-full @container"
    >
      <ArrivalLine>
        {/* The whole plate is the control, and the counts are its face:
            pressing them is what names the rows they count, so the affordance
            and the summary are one thing rather than a label with a "show"
            beside it. "Mark as seen" rides in the panel it opens, not beside
            the plate: a second control hanging off a centred chip is the
            trailing-annotation read again (#212), and putting the spend
            behind the open means the names are on screen when the reader
            destroys the digest — rule 2's own spirit. */}
        <button
          ref={(el) => {
            triggerRef.current = el;
            placePlate(el);
          }}
          type="button"
          aria-expanded={named}
          aria-controls={panelId}
          onClick={() => setNamed((showing) => !showing)}
          /* `lg:pointer-events-auto`: the overlay wrapper blankets the row
             with pointer-events off so the row stays clickable through it —
             the plate (and the panel below) opt back in. */
          className={`${PLATE} mx-auto flex min-w-0 items-baseline gap-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong lg:pointer-events-auto`}
        >
          {/* The news dot — the board's own column-dot vocabulary (StageWord,
              the pulse panel's swatches) saying "unread" the way every
              notification surface says it. This, the full-ink counts and the
              chevron are what separate the loud chip from the dormant one;
              the frame never changes. 9.65:1 against the chip's own ground
              (`--stage-applied` #b3b9c2 on `--surface` #0f1011, APCA Lc
              −65.6; 9.93:1 / Lc +93.1 on paper) — computed 2026-08-14. */}
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 shrink-0 self-center rounded-full bg-stage-applied"
          />
          <span className="tabular truncate">
            {/* One rendering at a time, never both: a tight chip gets the
                total, a roomy one gets the kinds — rung re-based +2rem for
                the plate's chrome, same as the quiet ladder. Opening it names
                the rows under their kind either way, so a reader on the total
                form is one press from everything the wide form says. */}
            <span className="@[28rem]:max-lg:hidden">
              <span className="text-strong">{counted}</span> change{counted === 1 ? "" : "s"}
            </span>
            <span className="hidden @[28rem]:max-lg:inline">
              {groups.map((group, i) => (
                <Fragment key={group.kind}>
                  {i > 0 ? <span className="text-dim"> · </span> : null}
                  <span className="whitespace-nowrap">
                    <span className="text-strong">{group.count}</span> {group.label}
                  </span>
                </Fragment>
              ))}
            </span>
          </span>
          <span className="hidden shrink-0 font-mono text-[11px] text-dim @[36rem]:max-lg:inline">
            · {moment}
          </span>
          <Chevron className="h-3 w-3 shrink-0 text-dim" aria-hidden />
          <span className="sr-only">{named ? "Hide the rows" : "Name the rows"}</span>
        </button>
      </ArrivalLine>

      {/* Opened by the reader — and even then the board holds still: the panel
          FLOATS under the row. The one movement this feature used to make on
          request is now no movement at all.

          THE SHEET IS A FAMILY MEMBER, and that is the whole style
          ---------------------------------------------------------
          This app already has a panel idiom, and the pulse band one row down
          is where it is strongest: `rounded-xl border bg-surface p-4
          shadow-xl`, hung `mt-2` under the cell that opened it (PulseDetail)
          — the same construction RowActionsMenu, the beta pill's panel and
          Dialog use at their own sizes, and none of them DRAWS its
          attachment: proximity and a shared axis are the whole claim. This
          sheet wore a bespoke construction instead — top corners squared
          under a 2px accent cap, a connector stem ruled up to the chip — and
          the owner rejected it on sight: the one overlay that drew its
          attachment read as another product's. So it is a plain family
          member now, at the pulse panel's own 26rem, centred on the chip
          (`placePanel`; the beta pill centres the same way), and the loud
          chip's accent dot is the only accent either object carries.

          ROUND THREE — the sheet is a READING surface (owner, verbatim: "i
          should just read messages or other like it used to do before! …
          very much details and nice way to view things! and a small kind of
          animation or graph as well within it!"). The construction stays
          exactly the family's — same 26rem, same chrome, same centring: the
          band-coverage trade above was accepted ON this width, so the
          richness is spent DOWN the sheet, where placePanel's height cap
          already bounds it, never across the band. What changed is inside
          the frame: the header states the whole claim, a strip draws where
          the changed rows sit now, every row is named (the "+N more" cap is
          gone), and each entry carries a third line of record. Each block
          below carries its own why. It also wears `pulse-panel` now — the
          family's one entrance (a 0.18s settle), which the dropdown restyle
          left off this sheet only.

          One measured deviation from PulseDetail's `border-line`, kept from
          the last round because the measurement still binds: the panel's
          ground (`--surface` #0f1011) is 1.04:1 against both the page behind
          it (#0a0a0b) and the worklist rows it covers (`--surface-2`
          #141517), and `--line` composites to #252626 — 1.26:1 on the
          surface, APCA Lc 0.0, invisible (re-computed 2026-08-14) — so a
          sheet bordered in it has no boundary at all on the dark theme,
          which is what "out of focus" was. `--line-strong` (#3f4041,
          1.83:1 / Lc −9.7 on the surface, 1.90:1 against the page) is the
          best border the system has and is what Dialog and the pulse
          tooltip wear for the same job. On a near-black UI the edge does
          the work a drop shadow physically cannot; `shadow-xl` rides along
          for the light theme, where shadows still exist. */}
      {named ? (
        <div
          ref={placePanel}
          id={panelId}
          style={{ left: 0 }}
          className="pulse-panel pointer-events-auto absolute top-full z-30 mt-2 flex w-[min(26rem,calc(100vw-2rem))] flex-col rounded-xl border border-line-strong bg-surface p-4 shadow-xl"
        >
          {/* The panel's header is the digest's whole claim in one sentence —
              "4 changes since yesterday 6:41 pm" — with the one act that
              spends the state on the right. The moment is said nowhere else
              on a real board (the chip only prints it from `@[36rem]` up,
              which the signed-in slot never reaches), and the count joined it
              in round three: restating the chip's number is the point, not a
              slip — the sheet is the reading surface now, and it has to say
              everything at every width, the same contract the kinds and the
              scope note already ride here under. Set in the text face rather
              than the chip's mono: there the moment is a bare stamp, here it
              is the object of a sentence. "Mark as seen" lives here rather
              than on the chip (#212): the centred plate has to read as one
              object, and a reader can only destroy the digest with the named
              rows in front of them — see the trigger's note. */}
          <div className="flex shrink-0 items-baseline justify-between gap-3">
            <p className="text-xs text-muted">
              <span className="tabular font-medium text-strong">{counted}</span> change
              {counted === 1 ? "" : "s"} since <span className="tabular">{moment}</span>
            </p>
            <button
              type="button"
              onClick={() => {
                // Close first: `named` survives the re-render, and a panel
                // left "open" would pop unasked the next time news arrives.
                setNamed(false);
                writeLastLook(storageKey, snapshotOf(rows, scope, Date.now(), partial));
              }}
              className={`${LINE_CONTROL} shrink-0 text-xs text-muted`}
            >
              Mark as seen
            </button>
          </div>

          {/* THE GRAPH — the changed rows drawn where they sit NOW, one unit
              per row in its column's own ink, in the columns' own left-to-
              right order: the board in miniature, saying the one thing no
              count above it says (the groups are KINDS; this is the outcome).
              A unit strip rather than a proportional wash for the runway's
              own reason — three changes are units you can recount, not a
              ratio — and even a morning that draws all-grey is a true claim:
              everything that happened is sitting in applied, nothing has
              advanced. Units, not days: the diff knows WHERE every change
              landed but only knows WHEN for arrivals (lastLook.ts rejected
              `updated_at` as evidence), so a changes-per-day sparkline would
              be a graph the data cannot honestly back.

              The strip is `aria-hidden` decoration over the caption beneath
              it — the band's own contract ("micro-bars are decoration over
              the numbers") — and the caption doubles as its legend: the same
              column dots the entries below already wear, so the strip's inks
              are named in the panel's one dot vocabulary. Fills measured on
              this sheet's `--surface` (WCAG 1.4.11 floor 3:1, computed
              2026-08-14): dark ground worst case `--viz-embeddings` 7.00:1 /
              `--red` 6.89:1; light worst `--viz-rules` 4.10:1 — every column
              ink clears both themes. It draws in once, left to right
              (`ledger-unit`, globals.css), and holds still. */}
          <div className="shrink-0" data-testid="ledger-landed">
            <div
              aria-hidden="true"
              className="mt-3 flex h-2 gap-px overflow-hidden rounded-full bg-surface-2"
            >
              {landed.map((entry, index) => (
                <span
                  key={entry.id}
                  className="ledger-unit h-full min-w-0 flex-1"
                  style={{
                    background: STAGE_COLORS.get(entry.to) ?? "var(--stage-applied)",
                    ["--i" as string]: Math.min(index, 20),
                  }}
                />
              ))}
            </div>
            <p className="tabular mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px] leading-snug text-dim">
              {landedCounts.map((column, index) => (
                <Fragment key={column.label}>
                  {index > 0 ? <span aria-hidden="true">·</span> : null}
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <span
                      aria-hidden="true"
                      className="h-1.5 w-1.5 rounded-full"
                      style={{
                        background: STAGE_COLORS.get(column.label) ?? "var(--stage-applied)",
                      }}
                    />
                    <span>
                      <span className="text-muted">{column.count}</span> in {column.label}
                    </span>
                  </span>
                </Fragment>
              ))}
            </p>
          </div>

          {/* The groups scroll, the frame does not: `max-height` is measured
              against the screen in `placePanel`, so the busiest morning is
              bounded here instead of running off the bottom of a shell that
              must never scroll (#149). The scroller is this inner box so the
              header, the strip and the scope caveat stay pinned.

              Every row is named now. The old LEDGER_ROWS cap ("+4 more") was
              a residue of the in-flow block this overlay replaced — a growth
              bound for a sheet that pushed the board as it grew. This one
              cannot grow past the screen (the height cap IS the bound), and
              a "+9 more" with nothing to press was the panel saying that the
              one thing it exists to say is somewhere else — the round-three
              complaint nearly verbatim. */}
          <div className="mt-3 min-h-0 overflow-y-auto overscroll-contain">
            <dl className="space-y-3.5">
              {groups.map((group, groupIndex) => {
                /* Provenance's one honest home per shape. A MIXED filed
                   group names it per entry (that is where it distinguishes);
                   a uniform one — every board in practice, since the account
                   is auto-filed — collapses the shared fact into the heading
                   ("all from your mail") instead of saying it N times, in
                   the auto-filed cell's own words. The deadline group's
                   provenance is uniform by definition (the derivation only
                   counts mail-read deadlines), so its heading always carries
                   it and its entries never do. */
                const mailFiled =
                  group.kind === "filed"
                    ? group.entries.filter((entry) => rowById.get(entry.id)?.source === "gmail")
                        .length
                    : 0;
                const mixedFiled = group.kind === "filed" && mailFiled > 0 && mailFiled < group.count;
                const shared =
                  group.kind === "deadline"
                    ? "read from your mail"
                    : group.kind === "filed" && !mixedFiled
                      ? `${group.count === 1 ? "" : "all "}${mailFiled > 0 ? "from your mail" : "by hand"}`
                      : null;
                return (
                  <Fragment key={group.kind}>
                    {/* The kind leads and its count rides after it in dim
                        figures. The count is NEW here as of round three, not
                        a duplication: at `lg`+ the chip always wears its
                        compact total (the in-row slot never reached the
                        28rem kinds rung — measured on ba2a653), so the
                        per-kind numbers were said nowhere on desktop; and
                        with every row named, a long group's size should not
                        have to be counted by scrolling it. The word stays
                        its own element so the panel's accessible claim
                        ("filed", exactly) is the group's word, as the e2e
                        locates it.

                        A run-in heading, ruled to the panel's full width, so
                        each kind reads as one block. It used to be a 7rem
                        column beside a 5rem gutter, which marooned a 11px
                        caps label ~180px from the rows it named. The rule is
                        an `after:` pseudo rather than a child so the
                        heading's text nodes stay exactly the word, the
                        figure and the shared fact. */}
                    <dt className="label-caps flex min-w-0 items-center gap-1.5 after:ml-1.5 after:h-px after:min-w-3 after:flex-1 after:bg-line after:content-['']">
                      <span>{group.label}</span>
                      <span className="tabular text-[11px] text-dim">{group.count}</span>
                      {shared !== null ? (
                        <span className="min-w-0 truncate text-[10px] font-normal normal-case tracking-normal text-dim">
                          · {shared}
                        </span>
                      ) : null}
                    </dt>
                    <dd className="mt-2 space-y-3">
                      {group.entries.map((entry, index) => (
                        <EntryLine
                          key={entry.id}
                          entry={entry}
                          today={today}
                          row={rowById.get(entry.id)}
                          atEmployer={perEmployer.get(entry.company) ?? 1}
                          withSource={mixedFiled}
                          order={groupStarts[groupIndex] + index}
                        />
                      ))}
                    </dd>
                  </Fragment>
                );
              })}
            </dl>
          </div>

          {/* The ledger reads one bounded page, so it says which page — the
              same disclosure, in the same words, as the board and the pulse
              band. Deliberately OUTSIDE the scroller: it is the caveat on
              everything above it, and a caveat that can scroll out of view is
              one the reader can miss entirely. */}
          {scopeNote ? (
            <p className="tabular mt-3.5 shrink-0 border-t border-line pt-2.5 text-xs text-dim">
              reads the {scopeNote} · older rows aren&apos;t loaded
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
