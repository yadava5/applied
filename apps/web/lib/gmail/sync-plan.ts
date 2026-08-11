/**
 * The pure half of the dashboard's sync surface: what a rebuild request says,
 * what the running line reads, what the receipt contains, and what the dialog
 * remembers about the last run.
 *
 * The component (`components/dashboard/SyncBar.tsx`) takes every sentence and
 * every request body from here and writes none of its own, so the honesty
 * rules are assertable:
 *
 *   - There is NO percentage anywhere in this module. The server sync is one
 *     request that returns once, at the end — a percentage on that path would
 *     be a timer wearing a costume. The elapsed clock is the one number the
 *     browser truly knows.
 *   - A rebuild body never carries `scope`. The backend forces
 *     `scope="anywhere"` on every rebuild (gmail_oauth.py: a scan that can
 *     REMOVE rows must see everything it judges; an inbox-scoped rebuild once
 *     deleted two real applications whose confirmations were archived). The UI
 *     states that instead of offering a control the server would ignore.
 *   - The receipt renders only fields the response actually carried.
 *
 * Dependency-free on purpose (the same rule as `sync-state.ts`): no React, no
 * `@/` alias, no import of another `.ts` module — `tests/unit/` loads this
 * file directly under Node's built-in type stripping.
 */

// --- The rebuild request ------------------------------------------------------

/**
 * The depth choices the dialog offers. The inbox mine's `COUNT_OPTIONS`
 * vocabulary plus 750 — today's server default (`_SYNC_DEFAULT_SCAN_TARGET`) —
 * so the default rebuild behaves exactly as the old hardwired button did.
 */
export const REBUILD_DEPTH_OPTIONS = [100, 200, 500, 750, 1000, 2000] as const;
export type RebuildDepth = (typeof REBUILD_DEPTH_OPTIONS)[number];
export const REBUILD_DEFAULT_DEPTH: RebuildDepth = 750;

/**
 * The window choices, mirroring the inbox's `RANGE_OPTIONS` values (restated
 * here rather than imported to keep this module loadable under `node --test`).
 * `"all"` omits the range bound entirely.
 */
export const REBUILD_RANGE_OPTIONS = [
  { value: "3", label: "3 mo" },
  { value: "6", label: "6 mo" },
  { value: "9", label: "9 mo" },
  { value: "12", label: "12 mo" },
  { value: "all", label: "All time" },
] as const;
export type RebuildRange = (typeof REBUILD_RANGE_OPTIONS)[number]["value"];
/** Matches today's hardwired rebuild (12 months), so the default is not a change. */
export const REBUILD_DEFAULT_RANGE: RebuildRange = "12";

/**
 * Body of `POST /api/gmail/sync` for a rebuild. `range` is omitted for all
 * time (mirroring `buildInboxParams`), and `scope` is never sent — see the
 * module comment. Passing `count`/`range` on a rebuild is correct: a rebuild
 * is a windowed request by definition and does not want the incremental cursor.
 */
export function rebuildRequestBody(
  depth: RebuildDepth,
  range: RebuildRange,
): { mode: "rebuild"; count: number; range?: string } {
  return range === "all"
    ? { mode: "rebuild", count: depth }
    : { mode: "rebuild", count: depth, range };
}

// --- Sentences ----------------------------------------------------------------

/** `2000` → `2,000` — deterministic grouping, no locale consulted. */
export function formatCount(n: number): string {
  const digits = String(Math.trunc(Math.abs(n)));
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return n < 0 ? `-${grouped}` : grouped;
}

/** Elapsed milliseconds → `0:42` / `1:23` / `12:05`. Never negative. */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** The window fragment of the running line and the confirm label. */
export function rangeLabel(range: RebuildRange): string {
  return range === "all" ? "all time" : `last ${range} months`;
}

/**
 * What a running rebuild restates about itself:
 * `up to 750 messages · last 12 months · all mail`. The `all mail` fragment is
 * the server-forced scope, stated because it is true, not chosen.
 */
export function rebuildScopeLine(depth: RebuildDepth, range: RebuildRange): string {
  return `up to ${formatCount(depth)} messages · ${rangeLabel(range)} · all mail`;
}

/** The confirm button names the choice it commits. */
export function rebuildConfirmLabel(range: RebuildRange): string {
  return range === "all" ? "Rebuild from all time" : `Rebuild from the last ${range} months`;
}

// --- Memory of the last run ---------------------------------------------------

/** What a finished rebuild records for the next dialog to report. */
export interface RebuildMemory {
  /** Wall-clock duration of the run, in milliseconds. */
  ms: number;
  /** Messages the run scanned (from the response, not estimated). */
  scanned: number;
  /** Epoch ms of completion. */
  at: number;
}

/** localStorage key for {@link RebuildMemory}. */
export const REBUILD_MEMORY_KEY = "applied:rebuild:last";

/** Parse a stored memory record; anything malformed is no record at all. */
export function parseRebuildMemory(raw: string | null | undefined): RebuildMemory | null {
  if (typeof raw !== "string" || raw === "") return null;
  try {
    const data = JSON.parse(raw) as Partial<RebuildMemory>;
    if (
      typeof data.ms !== "number" ||
      typeof data.scanned !== "number" ||
      typeof data.at !== "number" ||
      !Number.isFinite(data.ms) ||
      !Number.isFinite(data.scanned) ||
      data.ms < 0 ||
      data.scanned < 0
    ) {
      return null;
    }
    return { ms: data.ms, scanned: data.scanned, at: data.at };
  } catch {
    return null;
  }
}

/**
 * `your last rebuild scanned 512 messages in 41 s` — a report of a measured
 * past fact, not a prediction. When no record exists the dialog shows nothing;
 * "usually under a minute" claims nobody measured are not invented here.
 */
export function rebuildMemoryLine(memory: RebuildMemory): string {
  const seconds = Math.max(1, Math.round(memory.ms / 1000));
  return `your last rebuild scanned ${formatCount(memory.scanned)} messages in ${seconds} s`;
}

// --- Reading the response -----------------------------------------------------

/** One row a rebuild removed — id + company, exactly what the backend names. */
export interface RemovedRow {
  id: number;
  company: string;
  /** Set by the receipt UI once `POST /applications/{id}/restore` succeeds. */
  restored?: boolean;
}

/** The receipt-relevant slice of the backend `SyncResponse`. */
export interface RebuildOutcome {
  created: number;
  updated: number;
  scanned: number;
  purged: number;
  removed: RemovedRow[];
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/**
 * Read a `POST /gmail/sync` response body into the receipt's shape. Tolerant
 * of a partial body: nothing is ever displayed that the response did not say,
 * and a malformed `removed` entry is dropped rather than rendered blank.
 */
export function readRebuildOutcome(body: unknown): RebuildOutcome {
  const data = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const removedRaw = Array.isArray(data.removed) ? data.removed : [];
  const removed: RemovedRow[] = [];
  for (const entry of removedRaw) {
    if (typeof entry !== "object" || entry === null) continue;
    const row = entry as Record<string, unknown>;
    if (typeof row.id === "number" && Number.isInteger(row.id) && typeof row.company === "string") {
      removed.push({ id: row.id, company: row.company });
    }
  }
  return {
    created: count(data.created),
    updated: count(data.updated),
    scanned: count(data.scanned),
    purged: count(data.purged),
    removed,
  };
}

/**
 * The receipt's body line: `41 filed · 2 updated · 512 scanned`, or the
 * explicit nothing-changed sentence when a rebuild confirmed the board.
 */
export function receiptBodyLine(outcome: RebuildOutcome): string {
  if (outcome.created === 0 && outcome.updated === 0 && outcome.purged === 0) {
    return `nothing changed · ${formatCount(outcome.scanned)} scanned · every filed application matched`;
  }
  const parts: string[] = [];
  if (outcome.created > 0) parts.push(`${formatCount(outcome.created)} filed`);
  if (outcome.updated > 0) parts.push(`${formatCount(outcome.updated)} updated`);
  parts.push(`${formatCount(outcome.scanned)} scanned`);
  return parts.join(" · ");
}
