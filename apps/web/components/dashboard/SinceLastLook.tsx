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

import { boardColumns } from "@/lib/dashboard/board";
import { dueInfo, duePhrase } from "@/lib/dashboard/deadline";
import {
  changesSince,
  groupChanges,
  LEDGER_ROWS,
  momentLabel,
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
 * counts, and opening it names the rows. The chip lives on the dashboard's
 * one command row (SyncBar's `since` slot, between the subtitle and the sync
 * controls), inside a wrapper whose flex-basis is FIXED — so hydration can
 * never re-wrap the row, and every state of this chip occupies the same line
 * box. The dedicated notice line it used to hold is a line the worklist got
 * back.
 *
 * THE PLATE, ON ITS OWN LINE, CENTRED ON THE BAR (#212) — the chip is a
 * miniature of its own panel. Every state renders the same small plate:
 * square left corners, rounded right, hairline frame, a 2px rule down the
 * left edge — the panel's exact construction at chip scale, so the thing you
 * press and the thing that opens read as one object in two sizes. The loud
 * state's rule is the `--stage-applied` accent in full-strength ink; the
 * quiet and first-run states wear the SAME plate with the rule one register
 * down (`--line-strong`) and no chevron — the notification centre in its
 * empty condition, and the chevron's absence is what says there is nothing
 * to open.
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
 * caption. This spends nothing the reader had: before #212 the real board's
 * slot never reached the wide rungs at these widths either, so desktop
 * showed exactly these compact forms — the moment, the kinds and the scope
 * note live one press away in the panel, which now says all of it at every
 * width. Below `lg` the shell is unlocked and no floor applies: the same
 * node is an in-flow line at the stacked header's end, full ladder active,
 * reserved by the server pass so hydration never moves the board.
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
 * cells whole. It is hung on the chip now: `placePanel` measures the chip's
 * left edge onto the panel's, the accent rule runs unbroken from one into the
 * other, and a 30rem measure both reads better than a 38rem slab and hands the
 * band's last cell back. It still covers the band's middle, and that is the
 * accepted trade — the band is a summary of the same story the ledger is
 * spelling out, it is one press from returning, and coverage bounded to the
 * middle beats the right 60% of the band disappearing.
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
 * One row of the ledger, in two lines: the NEWS, then the detail.
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
 */
function EntryLine({ entry, today }: { entry: ChangeEntry; today: string }) {
  return (
    <div>
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
    </div>
  );
}

/** A text control at the line's own size: a bordered button would be half
 *  again as tall as the line it has to live inside. The padding is cancelled
 *  by an equal negative margin, so the press target is 26px while the box the
 *  band measures stays exactly one line. */
const LINE_CONTROL =
  "-my-1 rounded py-1 underline-offset-4 hover:text-strong hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong";

/** The plate every state of the chip wears — the panel's own construction at
 *  chip scale (square left corners, rounded right, hairline frame, a 2px rule
 *  down the left edge), so the chip and the sheet it opens read as one object
 *  at two sizes. Which inks ride on it is the state's business: accent rule +
 *  full-strength counts when there is news, `--line-strong` rule + dim ink
 *  when there is none. The frame is `--line-strong` in BOTH registers — the
 *  panel's own measurement (see its header) applies unchanged at plate scale:
 *  `--line` composites to APCA Lc 0.0 on the dark ground (re-computed for
 *  #212), so a dormant plate framed in it would be a floating sentence, not
 *  an object. Dormant is said by the rule's ink and the missing chevron, not
 *  by a fainter frame. `-my-1`/`py-1` is LINE_CONTROL's trick with borders on:
 *  the box the band measures stays exactly one line while the plate paints
 *  ~26px, overflowing the ~38px row invisibly (ArrivalLine's contract). Its
 *  23px of chrome (20px padding + 3px borders) is why every @container rung
 *  below sits 2rem above its pre-plate measurement — the rungs measure the
 *  SLOT, and the plate spends 23px of it before the sentence starts. */
const PLATE = "-my-1 rounded-r-md border border-l-2 border-line-strong bg-surface px-2.5 py-1";

/** Breathing room between the panel's bottom edge and the screen's, and the
 *  measures below which it stops giving way and scrolls instead. */
const PANEL_GUTTER = 16;
const PANEL_MIN_HEIGHT = 160;
const PANEL_MIN_WIDTH = 320;

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

  /**
   * Hang the panel on the chip's OWN rule, and bound it to the screen.
   *
   * The panel is anchored to the NOTIFICATION OVERLAY — the wrapper SyncBar
   * mounts this chip in (#212): `inset-0` over the header row at `lg`+, so
   * `top-full` is the ROW's bottom at every wrap state, and an in-flow line
   * at the stacked header's end below `lg`. It anchored to the header row
   * itself while the chip lived inside that row, because hanging it on the
   * chip's own line put a z-30 sheet over the Sync button whenever the row
   * wrapped (#172); the overlay's box IS the row's box, so the same
   * guarantee holds by construction. Before that it took the row's
   * `right-0` — a panel against the
   * far right edge, 29px clear of the trigger that opened it and detached
   * from anything. This puts its left edge on the PLATE's (`triggerRef` —
   * the whole plate is the trigger and its border box IS the chip's box), so
   * the 2px accent down this panel's left side is collinear with the one
   * down the plate and the two read as one stroke.
   *
   * The plate's own left offset is not a constant — it is whatever the
   * centring and the plate's container-adaptive width leave — so the fit is
   * MEASURED here rather than assumed. When the 30rem measure would run past
   * the line, the panel gives up WIDTH before it gives up alignment: sliding
   * it left instead would break the one stroke that says which chip opened
   * it, and the alignment is the whole repair. Below `PANEL_MIN_WIDTH` there
   * is no alignment left worth protecting, so it slides instead and takes
   * the room. Height is capped the same way, against what is left of the
   * screen, so a busy morning scrolls inside the panel instead of running
   * off the bottom of a shell that must never scroll (#149).
   * Everything is read against one `offsetParent`, so there is no viewport
   * arithmetic to disagree with a scroll.
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
    // cap a previous pass left behind — the 30rem lives in one place.
    panel.style.maxWidth = "";
    const room = row.clientWidth - plate.offsetLeft;
    const left =
      room >= PANEL_MIN_WIDTH ? plate.offsetLeft : Math.max(0, row.clientWidth - panel.offsetWidth);
    panel.style.left = `${left}px`;
    panel.style.maxWidth = `${row.clientWidth - left}px`;
    // The gap the accent has to jump to reach the plate. It is ~14px on the
    // row's one line — and was 62px back when sign-out wrapped the row at
    // 1024 (#172) — so the connector is drawn from the measurement, never a
    // guess.
    panel.style.setProperty(
      "--stem",
      `${Math.max(0, panel.offsetTop - (plate.offsetTop + plate.offsetHeight))}px`,
    );
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

              The dormant plate, centred on the bar (#212 — see the header):
              the same object as the loud chip and its panel, rule one
              register down, no chevron because there is nothing to open. */}
          <p className={`${PLATE} mx-auto min-w-0 truncate border-l-line-strong text-dim`}>
            {/* `max-lg` on every wide rung here and below: at `lg`+ the chip
                overlays the row's own line, where only the compact form has
                measured clearance from the totals and the cluster — the
                container is the full bar there, so width alone would say yes
                to sentences the row cannot host. See the header. */}
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
          {/* The dormant plate, centred — same object as the first-run line
              above and as the loud chip below (#212, see the header for the
              placement history: caption on the totals in #196, trailing
              annotation on the cluster after it). */}
          <p className={`${PLATE} mx-auto min-w-0 truncate border-l-line-strong text-muted`}>
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
            <span className="hidden @[18rem]:max-lg:inline">
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
          ref={triggerRef}
          type="button"
          aria-expanded={named}
          aria-controls={panelId}
          onClick={() => setNamed((showing) => !showing)}
          /* `lg:pointer-events-auto`: the overlay wrapper blankets the row
             with pointer-events off so the row stays clickable through it —
             the plate (and the panel below) opt back in. */
          className={`${PLATE} mx-auto flex min-w-0 items-baseline gap-1.5 border-l-stage-applied text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong lg:pointer-events-auto`}
        >
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

          WHAT MAKES IT LOOK ATTACHED, and why a shadow could not
          -------------------------------------------------------
          `left` is measured onto the chip (see `placePanel`), so this panel
          and the chip that opened it stand on one vertical line — the 2px
          `--stage-applied` rule runs down the chip, jumps the row's own gap
          through `--stem`, and continues down the panel's full left edge. The
          left corners stay square so that stroke reads as a straight line
          rather than bending away at the top.
          That rule is also the only edge on this thing that can be SEEN.
          Measured on the dark theme: the panel's ground (`--surface` #0f1011)
          is 1.04:1 against both the page behind it (#0a0a0b) and the worklist
          rows it covers (`--surface-2` #141517), and the `--line` border it
          used to wear composites to #252626 — 1.30:1 and 1.20:1, APCA Lc 0.0,
          which is invisible. The 50px black drop shadow contributed nothing
          either: there is no darkening a #0a0a0b page. So the sheet had no
          boundary at all, which is what "out of focus" was. `--line-strong`
          (#3f4041, 1.90:1 / 1.76:1) is the best border the system has and is
          what Dialog uses for the same job; the accent rule measures 10.02:1,
          APCA Lc -64.1, and does the rest. On a near-black UI the edge has to
          do the work the shadow physically cannot. */}
      {named ? (
        <div
          ref={placePanel}
          id={panelId}
          style={{ left: 0 }}
          className="pointer-events-auto absolute top-full z-30 mt-2 flex w-[min(30rem,calc(100vw-2rem))] flex-col rounded-r-xl border border-l-2 border-line-strong border-l-stage-applied bg-surface p-4 shadow-[0_16px_36px_-16px_rgba(0,0,0,0.9)] before:absolute before:bottom-full before:-left-0.5 before:w-0.5 before:bg-stage-applied before:content-[''] before:h-[var(--stem,0px)]"
        >
          {/* The panel's header: since WHEN on the left, the one act that
              spends the state on the right. The moment is said nowhere else
              on a real board — the chip only prints it from `@[36rem]` up,
              which the signed-in slot never reaches — and it is set in the
              text face rather than the chip's mono: there it is a bare stamp,
              here it is the object of a sentence. "Mark as seen" lives here
              rather than on the chip (#212): the centred plate has to read as
              one object, and a reader can only destroy the digest with the
              named rows in front of them — see the trigger's note. */}
          <div className="flex shrink-0 items-baseline justify-between gap-3">
            <p className="text-xs text-dim">
              since <span className="tabular text-muted">{moment}</span>
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

          {/* The groups scroll, the frame does not: `max-height` is measured
              against the screen in `placePanel`, so the busiest morning is
              bounded here instead of running off the bottom of a shell that
              must never scroll (#149). The scroller is this inner box so the
              stem above stays outside a clip. */}
          <div className="mt-3 min-h-0 overflow-y-auto overscroll-contain">
            <dl className="space-y-3.5">
              {groups.map((group) => {
                const shown = group.entries.slice(0, LEDGER_ROWS);
                const hidden = group.count - shown.length;
                return (
                  <Fragment key={group.kind}>
                    {/* The kind, not the count: the chip is already the counts
                        (and on its total form, the entries under each kind ARE
                        the count) — the same number twice is the thing this
                        dashboard removed everywhere else.

                        A run-in heading, ruled to the panel's full width, so
                        each kind reads as one block. It used to be a 7rem
                        column beside a 5rem gutter, which marooned a 11px caps
                        label ~180px from the rows it named and left "+N more"
                        hanging under nothing. The rule is an `after:` pseudo
                        rather than a child so this element's text stays
                        exactly the group's word. */}
                    <dt className="label-caps flex items-center after:ml-3 after:h-px after:flex-1 after:bg-line after:content-['']">
                      {group.label}
                    </dt>
                    <dd className="mt-2 space-y-2.5">
                      {shown.map((entry) => (
                        <EntryLine key={entry.id} entry={entry} today={today} />
                      ))}
                      {hidden > 0 ? (
                        <p className="tabular text-xs text-dim">+{hidden} more</p>
                      ) : null}
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
