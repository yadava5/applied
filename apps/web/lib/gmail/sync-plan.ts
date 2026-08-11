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

/**
 * The simulated (demo) surface remembers its rebuilds under its own key, so a
 * signed-in owner who visits /demo never has a fixture run reported back to
 * them as their own last rebuild.
 */
export const REBUILD_MEMORY_DEMO_KEY = "applied:rebuild:last:demo";

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

// --- How the scan ended -------------------------------------------------------
//
// A scan is bounded (message target, serverless time budget, page limit), so
// "the request returned" does not mean "the mailbox was covered". The backend
// says which with `stopped_by` (gmail_oauth.py `STOPPED_*`), and the UI must
// never render a finished state over a partial scan: converging a real board
// once took six presses, each reported as completion, because nothing read
// this field.

/** What the end state means for the user. */
export type StopKind = "complete" | "partial" | "broken";

/**
 * Classify a `stopped_by` value. Absent (an older backend) reads as complete —
 * the behaviour that response actually had. An unrecognised value reads as
 * PARTIAL, never complete: an end state we cannot vouch for must not claim
 * the mailbox was covered.
 */
export function stopKind(stoppedBy: string | null | undefined): StopKind {
  const reason = typeof stoppedBy === "string" ? stoppedBy.trim().toLowerCase() : "";
  if (reason === "" || reason === "complete") return "complete";
  if (reason === "disconnected" || reason === "relay") return "broken";
  return "partial";
}

/**
 * The reason in the user's terms — what stopped the scan, not the enum.
 * Deliberately number-free: "its 30-second budget" would rot the day the
 * backend tunes the deadline.
 */
export function stopReasonPhrase(stoppedBy: string | null | undefined): string {
  switch (typeof stoppedBy === "string" ? stoppedBy.trim().toLowerCase() : "") {
    case "target":
      return "hit its message limit";
    case "deadline":
      return "ran out of scan time";
    case "page_limit":
      return "hit Gmail's page limit";
    case "disconnected":
      return "lost its Gmail connection partway";
    case "relay":
      return "answered in an unexpected mode";
    default:
      return "stopped before finishing";
  }
}

/**
 * How far a partial scan got. `result_size_estimate` is Gmail's own estimate
 * and is documented as approximate, so it is worded as one — never turned
 * into a percentage or a bar (the same honesty rule as the elapsed clock).
 */
export function scanProgressLine(scanned: number, estimate: number | null): string {
  return estimate !== null && estimate > 0
    ? `scanned ${formatCount(scanned)} of roughly ${formatCount(estimate)}`
    : `scanned ${formatCount(scanned)} so far`;
}

/** The end-state facts of any sync/rebuild response, read defensively. */
export interface ScanEnd {
  stoppedBy: string;
  scanned: number;
  estimate: number | null;
}

export function readScanEnd(body: unknown): ScanEnd {
  const data = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const scanned =
    typeof data.scanned === "number" && Number.isFinite(data.scanned) && data.scanned > 0
      ? Math.floor(data.scanned)
      : 0;
  const estimate =
    typeof data.result_size_estimate === "number" &&
    Number.isFinite(data.result_size_estimate) &&
    data.result_size_estimate > 0
      ? Math.floor(data.result_size_estimate)
      : null;
  return {
    stoppedBy: typeof data.stopped_by === "string" ? data.stopped_by : "complete",
    scanned,
    estimate,
  };
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
  /** How the scan ended (`stopped_by`) — a rebuild that removed rows AND
   *  stopped early judged those removals against a partial scan, and the
   *  receipt must say so. */
  stoppedBy: string;
  /** Gmail's approximate match count, when it offered one. */
  estimate: number | null;
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
  const end = readScanEnd(body);
  return {
    created: count(data.created),
    updated: count(data.updated),
    scanned: count(data.scanned),
    purged: count(data.purged),
    removed,
    stoppedBy: end.stoppedBy,
    estimate: end.estimate,
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
