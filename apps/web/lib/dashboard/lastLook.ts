/**
 * "Since you last looked" — the pure derivation behind the dashboard's change
 * ledger. Given the board's current rows and a snapshot of the board the user
 * last acknowledged, it says what is DIFFERENT. Nothing here reads a clock, a
 * network or a browser API, so `node --test` can load it under type stripping
 * (import-free, same rule as `age.ts` / `board.ts` / `deadline.ts`).
 *
 * What "changed" is defined as, and what it deliberately is not
 * --------------------------------------------------------------
 * Three claims, each backed by evidence the rows actually carry:
 *
 *   · **filed**    — a row that was not on the board you last acknowledged.
 *   · **moved**    — a row whose BOARD COLUMN WORD differs from the one it sat
 *                    under last time. The caller passes the word the board
 *                    itself renders (`stageOf` → `COLUMN_LABELS`), so the
 *                    ledger can never claim a move the board does not show:
 *                    `interview` → `interviewing` is the same column and is
 *                    therefore not a change.
 *   · **deadline** — a row that gained (or was given a different) `due_at`
 *                    that the classifier read out of mail. `due_source: "user"`
 *                    is excluded on purpose: a deadline you typed is not news.
 *
 * Rejected, with reasons, because each would be a signal we cannot honestly
 * support:
 *
 *   · `updated_at` — it moves on every sync touch, so it reports "the sync
 *     ran", not "something happened". (It is also not in the web API's
 *     `Application` schema at all — only the local FastAPI surface exposes it.)
 *   · "went quiet" — nothing happening is the opposite of a change. It is a
 *     clock crossing, it would fire every day on a stale board and drown the
 *     real events, and the pulse strip's amber bucket plus the card's own
 *     "quiet Nd" tag already say it.
 *   · rows that DISAPPEARED — the board is one bounded page (`BOARD_PAGE_SIZE`),
 *     so a row's absence is not evidence it was removed; it may simply not have
 *     loaded. Silence beats a guess, and a rebuild's purge already names every
 *     row it removed, on its own receipt, with a restore beside it.
 *
 * The one clock the marker does NOT touch
 * ---------------------------------------
 * The snapshot's `at` is written with the BROWSER's clock and is **display
 * only** — it is never compared against a row's timestamp. A browser minutes
 * out of step with the server would otherwise suppress exactly the rows this
 * feature exists for: the arrival sync files overnight mail seconds after the
 * page loads, and `created_at < at` would hide it. Membership in `rows` is the
 * evidence for "filed"; `floor` (below) is the only date compared, and both
 * sides of that comparison are server-origin day strings.
 */

/** Bump when the record's shape changes; an older record reads as absent. */
export const LAST_LOOK_VERSION = 1;

/** The signed-in board's marker. The record names the user it belongs to. */
export const LAST_LOOK_KEY = "applied:lastlook";

/**
 * The /demo twin keeps its own marker, so a signed-in owner who visits the
 * demo never has fixture changes reported back as their own board's — the
 * same separation `REBUILD_MEMORY_DEMO_KEY` makes for rebuild memory.
 */
export const LAST_LOOK_DEMO_KEY = "applied:lastlook:demo";

/** Scope written into the demo's record. */
export const LAST_LOOK_DEMO_SCOPE = "demo";

/** How many rows one group of the ledger names before it says "+N more". */
export const LEDGER_ROWS = 4;

/**
 * A board row, projected to only what the ledger reasons about. The caller
 * does the projecting, which keeps stage semantics (`stageOf`, the board's
 * column labels) and the generated API schema out of this module.
 */
export interface ChangeRow {
  id: number;
  company: string;
  position: string;
  /** The word the board's column heading shows for this row's stage. */
  stage: string;
  /** The day the board stamps on the row (`filedAt`) — a server-origin string. */
  filed: string;
  /** ISO instant the row is due by, or null/undefined for none. */
  dueAt?: string | null;
  /** `"mail"` (the classifier read it) or `"user"` (you typed it). */
  dueSource?: string | null;
}

/** One row inside a snapshot: its column word, and its mail-read deadline. */
export interface LastLookRow {
  /** stage word */
  s: string;
  /** due_at, only when the classifier read it out of mail */
  d?: string;
}

/**
 * The board you last acknowledged. Deliberately holds ids and stage words
 * only — no company, no role, no note — so what sits in `localStorage` is the
 * minimum needed to answer "was this row here, and where".
 */
export interface LastLookRecord {
  v: number;
  /** Whose board this describes: the user's id, or `"demo"`. */
  scope: string;
  /** Epoch ms the snapshot was taken. Display only — see the header. */
  at: number;
  /**
   * The oldest filed day the snapshot could SEE, when it covered only part of
   * the account; `null` when it held every row. A row that is missing from a
   * partial snapshot and is no newer than this did not arrive — it scrolled
   * into the loaded window — so it is reported as nothing at all.
   */
  floor: string | null;
  /**
   * This baseline was laid down with no earlier visit to compare against — the
   * first-run state. Only the baseline write sets it; acknowledging or folding
   * a quiet board in leaves it off, so "no earlier visit" can never be claimed
   * about a browser that has one.
   */
  seed?: boolean;
  rows: Record<string, LastLookRow>;
}

export type ChangeKind = "filed" | "moved" | "deadline";

export interface ChangeEntry {
  id: number;
  company: string;
  position: string;
  kind: ChangeKind;
  /** The column word the row left, on a `moved` entry. */
  from?: string;
  /** The column word the row sits under now. */
  to: string;
  /** A newly mail-read deadline, when the row carries one. */
  dueAt?: string;
}

/** One group of the ledger: the count IS the group's label. */
export interface ChangeGroup {
  kind: ChangeKind;
  /** "2 filed", "1 moved", "1 new deadline" — the count, then the word. */
  count: number;
  label: string;
  entries: ChangeEntry[];
}

/** Leading `YYYY-MM-DD` of a date or timestamp; anything after it is ignored.
 *  Duplicated from `dates.ts` on purpose — this module stays import-free. */
const CALENDAR_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)/;

/** The calendar-day prefix of a server-origin string, or null if unusable. */
function day(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const match = CALENDAR_PREFIX.exec(value.trim());
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
}

/**
 * The oldest day the loaded rows can see, or `null` when the rows ARE the
 * whole account (`partial: false`) and absence is therefore conclusive.
 */
export function floorOf(rows: ChangeRow[], partial: boolean): string | null {
  if (!partial) return null;
  let oldest: string | null = null;
  for (const row of rows) {
    const d = day(row.filed);
    if (d !== null && (oldest === null || d < oldest)) oldest = d;
  }
  return oldest;
}

/** Take a snapshot of the board as it stands. */
export function snapshotOf(
  rows: ChangeRow[],
  scope: string,
  at: number,
  partial: boolean,
): LastLookRecord {
  const stored: Record<string, LastLookRow> = {};
  for (const row of rows) {
    const mailDue = row.dueSource === "mail" && typeof row.dueAt === "string" ? row.dueAt : null;
    stored[String(row.id)] = mailDue === null ? { s: row.stage } : { s: row.stage, d: mailDue };
  }
  return { v: LAST_LOOK_VERSION, scope, at, floor: floorOf(rows, partial), rows: stored };
}

/**
 * Parse a stored record. Anything malformed, from another user, or written by
 * an older version is no record at all — the ledger then reports nothing and
 * the caller lays down a fresh baseline, which is the honest first-visit path.
 */
export function parseLastLook(raw: string | null | undefined, scope: string): LastLookRecord | null {
  if (typeof raw !== "string" || raw === "") return null;
  try {
    const data = JSON.parse(raw) as Partial<LastLookRecord>;
    if (data.v !== LAST_LOOK_VERSION) return null;
    if (typeof data.scope !== "string" || data.scope !== scope) return null;
    if (typeof data.at !== "number" || !Number.isFinite(data.at)) return null;
    if (data.floor !== null && typeof data.floor !== "string") return null;
    if (typeof data.rows !== "object" || data.rows === null) return null;
    const rows: Record<string, LastLookRow> = {};
    for (const [id, value] of Object.entries(data.rows)) {
      if (typeof value !== "object" || value === null) continue;
      const { s, d } = value as Partial<LastLookRow>;
      if (typeof s !== "string") continue;
      rows[id] = typeof d === "string" ? { s, d } : { s };
    }
    return {
      v: LAST_LOOK_VERSION,
      scope,
      at: data.at,
      floor: data.floor ?? null,
      ...(data.seed === true ? { seed: true } : {}),
      rows,
    };
  } catch {
    return null;
  }
}

/**
 * What changed between the acknowledged snapshot and the board as it is now.
 *
 * One entry per row, at most: a row that arrived is "filed" even if it also
 * carries a deadline (the deadline rides along on the entry), and a row that
 * moved is "moved" even if its deadline moved with it. Two entries for one row
 * would inflate every count in the ledger's own headings.
 */
export function changesSince(
  rows: ChangeRow[],
  record: LastLookRecord,
  /** Rows the reader changed themselves in this session — see `mine` in
   *  `lastLookStore.ts`. They report nothing at all, in either direction. */
  mine?: ReadonlySet<number>,
): ChangeEntry[] {
  const filed: ChangeEntry[] = [];
  const moved: ChangeEntry[] = [];
  const deadlines: ChangeEntry[] = [];

  for (const row of rows) {
    if (mine?.has(row.id)) continue;
    const previous = record.rows[String(row.id)];
    const mailDue = row.dueSource === "mail" && typeof row.dueAt === "string" ? row.dueAt : null;

    if (previous === undefined) {
      // Missing from a PARTIAL snapshot and no newer than what that snapshot
      // could see → it entered the loaded window, it did not arrive. Say
      // nothing: the board cannot tell those apart, so neither will we.
      const filedDay = day(row.filed);
      if (record.floor !== null && (filedDay === null || filedDay <= record.floor)) continue;
      filed.push({
        id: row.id,
        company: row.company,
        position: row.position,
        kind: "filed",
        to: row.stage,
        ...(mailDue !== null ? { dueAt: mailDue } : {}),
      });
      continue;
    }

    if (previous.s !== row.stage) {
      moved.push({
        id: row.id,
        company: row.company,
        position: row.position,
        kind: "moved",
        from: previous.s,
        to: row.stage,
        ...(mailDue !== null ? { dueAt: mailDue } : {}),
      });
      continue;
    }

    if (mailDue !== null && previous.d !== mailDue) {
      deadlines.push({
        id: row.id,
        company: row.company,
        position: row.position,
        kind: "deadline",
        to: row.stage,
        dueAt: mailDue,
      });
    }
  }

  return [...filed, ...moved, ...deadlines];
}

/** The word a group of N changes goes under. The count is rendered separately. */
function groupLabel(kind: ChangeKind, count: number): string {
  if (kind === "filed") return "filed";
  if (kind === "moved") return "moved";
  return count === 1 ? "new deadline" : "new deadlines";
}

/**
 * Group the entries for the ledger, in the order they are read: what arrived,
 * what moved, what gained a date. Empty groups are dropped, so a ledger never
 * renders a heading over nothing.
 */
export function groupChanges(entries: ChangeEntry[]): ChangeGroup[] {
  const order: ChangeKind[] = ["filed", "moved", "deadline"];
  const groups: ChangeGroup[] = [];
  for (const kind of order) {
    const own = entries.filter((entry) => entry.kind === kind);
    if (own.length === 0) continue;
    groups.push({ kind, count: own.length, label: groupLabel(kind, own.length), entries: own });
  }
  return groups;
}

// --- The moment the ledger compares against ----------------------------------
//
// This one IS rendered from a real instant in the reader's own timezone, and
// that is correct rather than a violation of the `dates.ts` rule: the marker is
// an epoch millisecond this browser wrote, it has no server counterpart to
// disagree with, and the band it appears in never server-renders (the record
// lives in localStorage). The rule those modules exist to enforce — never read
// a CALENDAR-DAY STRING through a local `Date` — is untouched here.
//
// Written by hand rather than through `Intl` so the phrasing is identical on
// every machine and in every CI locale.

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** Local calendar-day number, for the today / yesterday comparison. */
function localDayIndex(date: Date): number {
  return Math.floor(
    (date.getTime() - date.getTimezoneOffset() * 60_000) / (24 * 60 * 60 * 1000),
  );
}

function clockTime(date: Date): string {
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const suffix = hours < 12 ? "am" : "pm";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${hour12}:${minutes} ${suffix}`;
}

/**
 * "today 9:14 am" / "yesterday 6:41 pm" / "Aug 8, 6:41 pm" — the moment the
 * ledger is comparing against, in the reader's own time. A marker somewhere in
 * the future (a clock that was corrected backwards) reads as today rather than
 * as a date nobody has lived through.
 */
export function momentLabel(at: number, now: number): string {
  const then = new Date(at);
  if (!Number.isFinite(at) || Number.isNaN(then.getTime())) return "your last visit";
  const days = localDayIndex(new Date(now)) - localDayIndex(then);
  if (days <= 0) return `today ${clockTime(then)}`;
  if (days === 1) return `yesterday ${clockTime(then)}`;
  return `${MONTHS[then.getMonth()]} ${then.getDate()}, ${clockTime(then)}`;
}
