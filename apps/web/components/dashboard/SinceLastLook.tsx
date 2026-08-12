"use client";

import { ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import {
  Fragment,
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
 * The expansion is never remembered. Restoring it on the next load would
 * re-create exactly the defect this shape removes — the server cannot know it
 * was open, so the panel would pop over the board unasked after hydration.
 *
 * Three states, all of them real:
 *
 *   · **first run** — no marker in this browser yet. It says so, and says the
 *     next visit is when this line starts working. It never counts the board
 *     you already have as news;
 *   · **quiet** — nothing changed, stated against the moment it is comparing
 *     from. "Nothing new since Aug 3" on August 11 is not filler: it says your
 *     pipeline has been silent for eight days;
 *   · **changed** — the counts, marked with a rule down the left edge, and the
 *     names one press away. The contrast between one dim sentence and a ruled
 *     line of counts in full-strength ink is the signal; most opens are quiet,
 *     and the loud state has to look different from across the room.
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

function EntryLine({ entry, today }: { entry: ChangeEntry; today: string }) {
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] leading-snug">
      <span className="font-medium text-strong">{entry.company}</span>
      {/* The role wraps rather than ellipsizing — its tail is what tells two
          requisitions at one employer apart (see ApplicationCard). */}
      <span className="min-w-0 text-muted">— {entry.position}</span>
      {/* Its own line on a phone, a right-hand column from `sm` up: trailing
          after a long role, it wraps somewhere different on every entry. */}
      <span className="flex w-full items-center gap-1.5 sm:ml-auto sm:w-auto">
        {entry.from !== undefined ? (
          <>
            <span className="label-caps shrink-0 text-dim">{entry.from}</span>
            <ArrowRight className="h-3 w-3 shrink-0 text-dim" aria-hidden />
            <span className="sr-only">to</span>
          </>
        ) : null}
        <StageWord word={entry.to} />
        {entry.dueAt ? <DueNote dueAt={entry.dueAt} today={today} /> : null}
      </span>
    </p>
  );
}

/** A text control at the line's own size: a bordered button would be half
 *  again as tall as the line it has to live inside. The padding is cancelled
 *  by an equal negative margin, so the press target is 26px while the box the
 *  band measures stays exactly one line. */
const LINE_CONTROL =
  "-my-1 rounded py-1 underline-offset-4 hover:text-strong hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong";

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
              tight chip; the tail explaining what happens next is what a
              roomier one has space for. One sentence, two lengths — never
              two lines. */}
          <p className="min-w-0 truncate text-dim">
            No earlier visit recorded in this browser
            <span className="@[34rem]:hidden">.</span>
            <span className="hidden @[34rem]:inline">
              {" "}
              — from your next one, this line names what changed.
            </span>
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
          <p className="min-w-0 truncate text-muted">
            Nothing new since <span className="font-mono text-[11px] text-dim">{moment}</span>
            {/* The slice this reading covers, where the chip has room for it
                — the board and the pulse carry the same disclosure, in the
                same words, at every width. */}
            {scopeNote ? (
              <span className="hidden text-dim @[34rem]:inline"> · {scopeNote}</span>
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
      /* `@container` because the chip's room depends on its row-mates, not
         the viewport: the /demo row carries a wider cluster than the signed-in
         one at the same width, and a viewport breakpoint cannot know that.
         The blue rule is the loud state's across-the-room signal — the caps
         heading it used to carry belongs to the section's aria-label now.

         Deliberately NOT `relative`: the names panel positions against the
         HEADER ROW (SyncBar's row is the nearest positioned ancestor), not
         this chip — anchored to the chip it extended past <main>'s left edge,
         whose implicit overflow clip cut the first label off. */
      className="w-full border-l-2 border-stage-applied pl-2 @container"
    >
      <ArrivalLine>
        {/* The counts ARE the control: pressing them is what names the rows
            they count, so the affordance and the summary are one thing rather
            than a label with a "show" beside it. */}
        <button
          ref={triggerRef}
          type="button"
          aria-expanded={named}
          aria-controls={panelId}
          onClick={() => setNamed((showing) => !showing)}
          className={`${LINE_CONTROL} flex min-w-0 items-baseline gap-1.5 text-muted`}
        >
          <span className="tabular truncate">
            {/* One rendering at a time, never both: a tight chip gets the
                total, a roomy one gets the kinds. Opening it names the rows
                under their kind either way, so a reader on the total form is
                one press from everything the wide form says. */}
            <span className="@[26rem]:hidden">
              {counted} change{counted === 1 ? "" : "s"}
            </span>
            <span className="hidden @[26rem]:inline">
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
          <Chevron className="h-3 w-3 shrink-0 text-dim" aria-hidden />
          <span className="sr-only">{named ? "Hide the rows" : "Name the rows"}</span>
        </button>

        <span className="hidden shrink-0 font-mono text-[11px] text-dim @[34rem]:inline">
          · {moment}
        </span>

        <button
          type="button"
          onClick={() => writeLastLook(storageKey, snapshotOf(rows, scope, Date.now(), partial))}
          className={`${LINE_CONTROL} ml-auto shrink-0 text-muted`}
        >
          Mark as seen
        </button>
      </ArrivalLine>

      {/* Opened by the reader — and even then the board holds still: the
          panel FLOATS under the row (anchored to the chip's right edge, so it
          opens inward over the board rather than past the pane's edge). The
          one movement this feature used to make on request is now no
          movement at all. */}
      {named ? (
        <div
          ref={panelRef}
          id={panelId}
          className="absolute right-0 top-full z-30 mt-2 w-[min(38rem,85vw)] rounded-xl border border-line bg-surface p-4 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.8)]"
        >
          {/* Baseline alignment across the two columns, not a nudge: the kind
              label is 11px caps and the entries 13px, so the grid lines their
              first baselines up rather than their boxes. */}
          <dl className="grid items-baseline gap-x-5 gap-y-2 sm:grid-cols-[7rem_minmax(0,1fr)]">
            {groups.map((group) => {
              const shown = group.entries.slice(0, LEDGER_ROWS);
              const hidden = group.count - shown.length;
              return (
                <Fragment key={group.kind}>
                  {/* The kind, not the count: the chip is already the counts
                      (and on its total form, the entries under each kind ARE
                      the count) — the same number twice is the thing this
                      dashboard removed everywhere else. */}
                  <dt className="label-caps">{group.label}</dt>
                  <dd className="space-y-1.5">
                    {shown.map((entry) => (
                      <EntryLine key={entry.id} entry={entry} today={today} />
                    ))}
                    {hidden > 0 ? <p className="tabular text-xs text-dim">+{hidden} more</p> : null}
                  </dd>
                </Fragment>
              );
            })}
          </dl>

          {/* The ledger reads one bounded page, so it says which page — the
              same disclosure, in the same words, as the board and the pulse
              band. */}
          {scopeNote ? (
            <p className="tabular mt-2.5 text-xs text-dim">
              reads the {scopeNote} · older rows aren&apos;t loaded
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
