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

// --- What the dashboard sync says about itself --------------------------------
//
// Measured on the real signed-in board (1024 CSS px, #160): a routine sync is
// ONE request that takes ~2.7-3.1 s and comes back
// `{scanned: 0, result_size_estimate: null, stopped_by: "complete"}` — the
// server took the Gmail history-cursor path, so it read no messages and Gmail
// offered no estimate. There is nothing to count while that runs, and a number
// that advanced anyway would be the timer-in-a-costume this module forbids.
//
// What IS knowable is stated instead: what the run covers (below), the elapsed
// clock, and — once it returns — how long it actually took and how far it got.

/**
 * The window a CURSOR-LESS dashboard sync falls back to, mirroring the
 * backend's `_SYNC_DEFAULT_RANGE_MONTHS` (gmail_oauth.py). Restated rather
 * than imported for the same reason `REBUILD_DEFAULT_DEPTH` is: this module
 * stays dependency-free, and the sentence must name a real window or say
 * nothing at all.
 */
export const SYNC_FALLBACK_RANGE_MONTHS = 12;

/**
 * What a running sync is COVERING — the one thing about the scan the client
 * honestly knows before the response lands.
 *
 * `hasCursor` is server truth (`GET /auth/gmail/status`), and it decides which
 * path the backend takes: with a cursor it reads only what Gmail says changed
 * since the last run (fast, and usually zero messages); without one it
 * re-lists a bounded recent window. Saying which is the difference between "it
 * is doing something" and "it is doing THIS", and it costs no counts we do not
 * have.
 *
 * The one thing it cannot vouch for: a cursor Gmail has AGED OUT (404, normal
 * after about a week) makes `_incremental_scan` return None, and the backend
 * silently falls back to the full 12-month window. So "checking since last
 * sync" can be running over a wider scan than it names. It is still the best
 * statement available before the response exists, and the receipt corrects it
 * the moment one does — `stopped_by` plus the coverage line report what the
 * scan ACTUALLY did. Said out loud here rather than left as a quiet
 * overclaim.
 *
 * Both strings are width-budgeted: this line rides beside the board's totals
 * at `lg`+, where the status slot measures 208px and the sentence's share of
 * it is 140px (measured at 1024 on the signed-in board — the icon, two gaps
 * and the clock take the rest). `checking since last sync` is 128px and
 * `first scan · last 12 months` is 135px, so neither truncates at the width
 * the owner actually runs.
 */
export function syncScopeLine(hasCursor: boolean): string {
  return hasCursor
    ? "checking since last sync"
    : `first scan · last ${SYNC_FALLBACK_RANGE_MONTHS} months`;
}

/**
 * A MEASURED duration in whole seconds — `3 s`. Never a prediction and never
 * an average: it is only ever rendered about a run that already happened.
 * Floors at 1 s so a sub-second run reads as a duration rather than `0 s`.
 * Same vocabulary as {@link rebuildMemoryLine}, deliberately.
 */
export function durationLabel(ms: number): string {
  return `${Math.max(1, Math.round(Math.max(0, ms) / 1000))} s`;
}

/** When a running sync with NO measured history stops feeling instant and
 *  starts saying so. The clock beside the sentence runs from the first tick,
 *  not from here — this threshold only changes the WORDING (#160). */
export const SLOW_SYNC_AFTER_MS = 8000;

/**
 * Grace past the last measured duration before the running line says this run
 * has outlasted it. Real runs on the same account drift a few hundred ms
 * between presses; without slack, every run marginally slower than the last
 * would flip the sentence for its final fraction of a second.
 */
export const SLOW_SYNC_GRACE_MS = 2000;

/**
 * The running line's sentence, and the mid-run answer to "how long will this
 * take" (#160 — the owner's words: "no timer how long the sync will take").
 *
 * Until the run is slow it states scope ({@link syncScopeLine}). Once it IS
 * slow, the one honest forward-looking fact this client holds — the measured
 * duration of the LAST run — joins the sentence, in the past tense like every
 * duration in this module: `still checking · last run 3 s`. "Slow" is
 * relative to that same measurement (`last.ms` + {@link SLOW_SYNC_GRACE_MS}),
 * because outlasting the previous run is the moment the question changes from
 * "what is it doing" to "should it be done by now" — but never LATER than the
 * fixed {@link SLOW_SYNC_AFTER_MS}: a 41 s full-scan memory must not hold the
 * bare scope line for 40 s. No memory means no number, not an invented one.
 *
 * Width-budgeted like the scope line above: `still checking · last run 3 s`
 * lays out 138px at text-xs (measured on the production build, headless
 * Chromium, 2026-08-14) against the 304px the signed-in row's status slot
 * holds at 1024 once the chip overlay yields to a speaking status (#160) —
 * "took" was cut to keep it near the scope line's own footprint, since the
 * pill-furnished fixture twin's 137px slot truncates even that today. No e2e
 * fixture reaches this branch — the demo's simulated 1.2 s sync ends before
 * its own swap point — so it is exercised by `tests/unit/sync-plan.test.mjs`,
 * the same debt the two waiting states carry (task #96).
 */
export function syncRunningSentence(
  hasCursor: boolean,
  elapsedMs: number,
  last: RebuildMemory | null,
): string {
  const slowAfterMs =
    last === null ? SLOW_SYNC_AFTER_MS : Math.min(SLOW_SYNC_AFTER_MS, last.ms + SLOW_SYNC_GRACE_MS);
  if (elapsedMs < slowAfterMs) return syncScopeLine(hasCursor);
  return last === null ? "still checking" : `still checking · last run ${durationLabel(last.ms)}`;
}

/**
 * Gmail's `resultSizeEstimate` drifts between pages of the same query, so a
 * client using it as a denominator must never let it sit BELOW what has
 * already been read — a total smaller than its own numerator is worse than no
 * total. The backend clamps within one response (`_full_scan`); this clamps
 * again at the point of display, because that is where the two numbers are
 * finally rendered side by side.
 */
export function clampEstimate(scanned: number, estimate: number | null): number | null {
  return estimate === null ? null : Math.max(estimate, scanned);
}

/**
 * A finished sync's one-line receipt: what it did, how far it got when the
 * scan can say, and how long it took.
 *
 * `base` is the caller's already-composed outcome sentence (`filedSummary`,
 * or the cursored-zero sentence). Coverage is appended ONLY when all three
 * hold:
 *
 *   - the run actually read messages, and
 *   - Gmail offered an estimate (the full-scan path; the incremental path
 *     offers neither, so it gets no `scanned 0 of roughly 0`), and
 *   - the scan ended COMPLETE. A partial end already renders its own
 *     `scanProgressLine` beside "the scan hit its message limit" and a
 *     "continue the scan" control, so adding it here printed the same
 *     `scanned 412 of roughly 1,200` twice in one sentence — caught by
 *     rendering an injected full-scan response on the real board.
 *
 * The duration is always appended: it is the direct answer to "how long will
 * this take", stated as the measured fact it is rather than the forecast it
 * is not.
 */
export function syncReceiptNote(base: string, end: ScanEnd, elapsedMs: number): string {
  const parts = [base];
  if (end.scanned > 0 && end.estimate !== null && stopKind(end.stoppedBy) === "complete") {
    parts.push(scanProgressLine(end.scanned, clampEstimate(end.scanned, end.estimate)));
  }
  parts.push(durationLabel(elapsedMs));
  return parts.join(" · ");
}

/** localStorage key for the last SYNC's measured duration (see below). */
export const SYNC_MEMORY_KEY = "applied:sync:last";

/** The demo's own key, so a fixture run is never reported as a real one —
 *  same separation {@link REBUILD_MEMORY_DEMO_KEY} makes for rebuilds. */
export const SYNC_MEMORY_DEMO_KEY = "applied:sync:last:demo";

/**
 * `Your last sync took 3 s.` — the Sync button's tooltip tail, and the closest
 * honest answer to "when will it complete": a measurement of the previous run,
 * worded in the past tense so it cannot be read as a promise about this one.
 * It rides in `title`, which costs the header row no width — the row already
 * wraps at 1024 (#172) and must not be made worse.
 *
 * Reuses {@link RebuildMemory}: a run's duration + what it scanned + when, on
 * either path.
 */
export function syncMemoryLine(memory: RebuildMemory): string {
  return `Your last sync took ${durationLabel(memory.ms)}.`;
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
  /**
   * Messages the classifier called a job-application category and the pipeline
   * then discarded for scoring too low to file OR to queue. Zero on a healthy
   * sync.
   *
   * It is on the receipt because of what the receipt used to say without it.
   * On 2026-08-21 four Microsoft confirmations were thrown away by that drop
   * and the owner was shown `nothing changed - N scanned - every filed
   * application matched`, whose last clause was simply untrue. "We found
   * nothing" and "we discarded four of your applications" have to be different
   * sentences.
   */
  dropped: number;
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
    dropped: count(data.dropped),
    removed,
    stoppedBy: end.stoppedBy,
    estimate: end.estimate,
  };
}

/**
 * The receipt's body line: `41 filed · 2 updated · 512 scanned`, or the
 * explicit nothing-changed sentence when a rebuild confirmed the board.
 *
 * THE NOTHING-CHANGED SENTENCE IS A CLAIM, and it may only be made when the
 * sync really did account for everything it read. `every filed application
 * matched` was shown to the owner on a run that had just discarded four
 * Microsoft application confirmations, which is how a real product defect
 * reached him as "the sync works, you must not have applied". A run with
 * anything in `dropped` takes the itemised branch instead and names the number.
 */
export function receiptBodyLine(outcome: RebuildOutcome): string {
  const boardUnchanged =
    outcome.created === 0 && outcome.updated === 0 && outcome.purged === 0;
  if (boardUnchanged && outcome.dropped === 0) {
    return `nothing changed · ${formatCount(outcome.scanned)} scanned · every filed application matched`;
  }
  const parts: string[] = [];
  if (outcome.created > 0) parts.push(`${formatCount(outcome.created)} filed`);
  if (outcome.updated > 0) parts.push(`${formatCount(outcome.updated)} updated`);
  parts.push(`${formatCount(outcome.scanned)} scanned`);
  // Last, and worded as what it is: mail that looked like it was about a job
  // application and did not make it onto the board or into the queue. Not
  // "skipped" (which reads as deliberate) and not "failed" (which reads as an
  // error the user caused).
  if (outcome.dropped > 0) {
    parts.push(`${formatCount(outcome.dropped)} too unclear to file`);
  }
  return parts.join(" · ");
}
