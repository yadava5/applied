"use client";

import { ArrowRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { todayISO } from "@/lib/dashboard/age";
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
 * Three states, all of them real:
 *
 *   · **first run** — no marker in this browser yet. It says so, and says the
 *     next visit is when this line starts working. It never counts the board
 *     you already have as news;
 *   · **quiet** — nothing changed, stated against the moment it is comparing
 *     from. "Nothing new since Aug 3" on August 11 is not filler: it says your
 *     pipeline has been silent for eight days;
 *   · **changed** — the ledger, marked with a rule down its left edge. The
 *     contrast between one dim sentence and this block is the signal; most
 *     opens are quiet, and the loud state has to look different from across
 *     the room.
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
 * `useSyncExternalStore`'s server snapshot is `null` and this renders nothing
 * at all until hydration — no mismatch, and no board state depends on it. With
 * JS off the dashboard is exactly the dashboard, minus one reading aid.
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
 *  the card's own tag uses — never a second vocabulary for one fact. */
function DueNote({ dueAt, today }: { dueAt: string; today: string }) {
  const due = dueInfo(dueAt, today);
  if (!due) return null;
  const ink =
    due.state === "overdue" ? "text-reject" : due.state === "soon" ? "text-review" : "text-dim";
  return (
    <span className={`tabular shrink-0 font-mono text-[10px] ${ink}`}>{duePhrase(due.daysLeft)}</span>
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

  const settled = useRef(false);
  /** One clock read for the mount — the marker's label is "today"/"yesterday"
   *  relative to it. Read through a lazy initializer because the clock is
   *  impure and a render must not depend on when it happens to run. */
  const [now] = useState(() => Date.now());

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
      writeLastLook(storageKey, { ...snapshotOf(rows, scope, Date.now(), partial), seed: true });
      return;
    }
    // Rule 3: nothing to report → fold the board in, leave the moment alone.
    if (changesSince(rows, stored, ownChanges()).length === 0) {
      writeLastLook(storageKey, snapshotOf(rows, scope, stored.at, partial));
    }
  }, [rows, record, scope, storageKey, partial]);

  const today = todayISO();
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
  // read. Rendering a placeholder here would reserve space for a line that is
  // usually one sentence long.
  if (record === null) return null;

  if (seeded) {
    return (
      <section data-testid="since-last-look" aria-label="Changes since your last visit">
        <p className="text-[13px] leading-snug text-dim">
          No earlier visit recorded in this browser — from your next one, this line names what
          changed.
        </p>
      </section>
    );
  }

  const moment = momentLabel(record.at, now);

  if (groups.length === 0) {
    return (
      <section data-testid="since-last-look" aria-label="Changes since your last visit">
        <p className="text-[13px] leading-snug text-muted">
          Nothing new since <span className="font-mono text-[11px] text-dim">{moment}</span>
          {scopeNote ? <span className="text-dim"> · {scopeNote}</span> : null}
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="since-last-look"
      aria-label="Changes since your last visit"
      /* Capped to a reading measure rather than the page's width: the stage
         annotations form a right-hand column, and across 1100px the eye loses
         which name they belong to. */
      className="max-w-3xl border-l-2 border-stage-applied py-0.5 pl-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h2 className="label-caps">since you last looked</h2>
          <span className="font-mono text-[11px] text-dim">· {moment}</span>
        </div>
        <button
          type="button"
          onClick={() => writeLastLook(storageKey, snapshotOf(rows, scope, Date.now(), partial))}
          className="rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
        >
          Mark as seen
        </button>
      </div>

      {/* The count is the group's heading — it is not restated in a summary
          line above, because that line would be the same numbers twice. */}
      <dl className="mt-2.5 grid gap-x-5 gap-y-2 sm:grid-cols-[7rem_minmax(0,1fr)]">
        {groups.map((group) => {
          const shown = group.entries.slice(0, LEDGER_ROWS);
          const hidden = group.count - shown.length;
          return (
            <Fragment key={group.kind}>
              {/* Tabular, not mono: an inline count inside a phrase is the
                  same voice the pulse strip uses right below ("6 <1 wk"). Mono
                  stays for the stamps — the marker's time, a due phrase. */}
              <dt className="text-[13px] text-muted">
                <span className="tabular text-strong">{group.count}</span> {group.label}
              </dt>
              <dd className="space-y-1.5">
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

      {/* The ledger reads one bounded page, so it says which page — the same
          disclosure, in the same words, as the board and the pulse strip. */}
      {scopeNote ? (
        <p className="tabular mt-2.5 text-xs text-dim">
          reads the {scopeNote} · older rows aren&apos;t loaded
        </p>
      ) : null}
    </section>
  );
}
