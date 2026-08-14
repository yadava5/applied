/**
 * The browser edge of `lastLook.ts`: where the marker is kept, how a component
 * subscribes to it, and how a board row is projected into the shape the pure
 * derivation reasons about.
 *
 * The marker lives in `localStorage`, per device, and nothing about it touches
 * the schema — "since *I* last looked" is a reading of this browser's own
 * history, and a per-row `seen_at` column would have to be migrated by hand
 * into production with RLS re-verified for a signal that is not shared between
 * people anyway.
 *
 * Reads go through `readLastLookRaw`, which returns the raw string: React's
 * `useSyncExternalStore` compares snapshots by identity, so handing it a freshly
 * parsed object every call would loop. Parsing happens once, in the component,
 * behind a `useMemo` on that string.
 */
import { boardColumns } from "@/lib/dashboard/board";
import { filedAt } from "@/lib/dashboard/dates";
import {
  parseLastLook,
  type ChangeRow,
  type LastLookRecord,
} from "@/lib/dashboard/lastLook";
import { STAGES, stageOf, type Application } from "@/lib/dashboard/summary";

/** status → the word the board's column heading shows. Built from the board's
 *  own columns, so the ledger and the board can never use different words. */
const STAGE_WORDS = new Map(
  boardColumns(STAGES).map((column) => [column.key, column.label] as const),
);

/** The column word a row sits under — `rejected`/`withdrawn`/`ghosted` all
 *  read as `closed`, exactly as the board heads that column. */
export function stageWordOf(status: string): string {
  const key = stageOf(status);
  return STAGE_WORDS.get(key) ?? key;
}

/** Project an API row onto what the ledger reasons about. */
export function toChangeRow(app: Application): ChangeRow {
  return {
    id: app.id,
    company: app.company,
    position: app.position,
    stage: stageWordOf(app.status),
    filed: filedAt(app),
    dueAt: app.due_at ?? null,
    dueSource: app.due_source ?? null,
    source: app.source ?? null,
  };
}

// --- Storage ------------------------------------------------------------------

const listeners = new Set<() => void>();
let storageBound = false;

/**
 * Rows this reader changed themselves since the tab opened.
 *
 * The stored snapshot is patched the moment a stage write succeeds, but the
 * BOARD only catches up when `router.refresh()` lands — and in that window the
 * snapshot says "interviewing" while the rows still say "applied", which reads
 * as a move in the wrong direction. Remembering the ids for the session makes
 * those rows silent in both directions until the two agree; the patched
 * snapshot is what keeps the next visit honest.
 */
const mine = new Set<number>();

/** The rows this session owns — the ledger reports nothing about them. */
export function ownChanges(): ReadonlySet<number> {
  return mine;
}

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * Subscribe to marker changes. `storage` only fires in OTHER tabs, so writes
 * made here notify the local set directly — without that, pressing "Mark as
 * seen" would change storage and nothing on screen.
 */
export function subscribeLastLook(listener: () => void): () => void {
  listeners.add(listener);
  if (!storageBound && typeof window !== "undefined") {
    window.addEventListener("storage", notify);
    storageBound = true;
  }
  return () => {
    listeners.delete(listener);
  };
}

/** The stored record as a raw string — a stable value for `getSnapshot`. */
export function readLastLookRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** `getServerSnapshot`: there is no marker on the server, and never can be. */
export function serverLastLookRaw(): null {
  return null;
}

export function writeLastLook(key: string, record: LastLookRecord): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(record));
  } catch {
    // Storage full or blocked — the ledger simply reports nothing. It is a
    // reading aid, and no board state depends on it.
  }
  notify();
}

/**
 * Fold a stage change the USER just made into the acknowledged snapshot.
 *
 * Without this the ledger reports your own drag back at you on the next
 * render: "1 moved · Cedar Labs applied → interviewing", about a card you
 * moved yourself, with the animation still settling. The board's mutations all
 * funnel through one `changeStatus` per surface (the live transport, and the
 * demo's simulated one), which is where this is called.
 *
 * Deliberately NOT done for deadlines: every write through `setDeadline` is
 * marked `due_source: "user"`, and the ledger only ever counts a deadline the
 * classifier read out of mail.
 */
export function noteUserStageChange(key: string, id: number, status: string): void {
  mine.add(id);
  try {
    const record = parseLastLookAnyScope(window.localStorage.getItem(key));
    if (record === null || record.rows[String(id)] === undefined) return;
    const rows = { ...record.rows, [String(id)]: { ...record.rows[String(id)], s: stageWordOf(status) } };
    window.localStorage.setItem(key, JSON.stringify({ ...record, rows }));
  } catch {
    // Same as above: a marker that cannot be updated only costs one stale line.
  }
  notify();
}

/** The transport knows the row, not whose board it is; the record already
 *  names its own scope, so patching one row does not need to re-check it. */
function parseLastLookAnyScope(raw: string | null): LastLookRecord | null {
  if (typeof raw !== "string" || raw === "") return null;
  try {
    const scope = (JSON.parse(raw) as { scope?: unknown }).scope;
    return typeof scope === "string" ? parseLastLook(raw, scope) : null;
  } catch {
    return null;
  }
}
