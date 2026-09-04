/**
 * The pure half of the dashboard's sync surface: what a scan request says,
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
 *   - `scope` is ASYMMETRIC, and it is the trap in this file. Both dispositions
 *     have to read archived mail — a scan that re-judges a row it already filed
 *     is reading mail the owner archived months ago, and a scan that can REMOVE
 *     a row must see everything it judges (an inbox-scoped rebuild once deleted
 *     two real applications whose confirmations were archived). The backend
 *     gets there two different ways: `mode="rebuild"` is FORCED to
 *     `in:anywhere` server-side and the caller gets no say, while
 *     `mode="additive"` falls through `_parse_scope`, which DEFAULTS TO
 *     `in:inbox` (gmail_oauth.py `_scan_server_side`). So a rebuild body must
 *     not carry `scope` — claiming a say it does not have — and a windowed
 *     additive body MUST carry `scope: "anywhere"` or the scan quietly reads
 *     the inbox only, files nothing, and reports a clean receipt. Same reason,
 *     opposite action; `tests/unit/sync-plan.test.mjs` asserts the pair.
 *   - The receipt renders only fields the response actually carried.
 *
 * Dependency-free on purpose (the same rule as `sync-state.ts`): no React, no
 * `@/` alias, no import of another `.ts` module — `tests/unit/` loads this
 * file directly under Node's built-in type stripping.
 */

// --- The windowed scan request ------------------------------------------------

/**
 * The depth choices the dialog offers.
 *
 * 750 WAS THE SERVER DEFAULT AND IS NOT ANY MORE. `_SYNC_DEFAULT_SCAN_TARGET`
 * is 297, because Gmail's per-user ceiling fell to 6,000 units a minute and
 * `messages.get` rose to 20, so 297 messages (three pages at `20N + 5`) is
 * what one invocation can actually read. The default here follows it, and a
 * default-depth scan is now a depth the server can finish rather than one it
 * reports as partial every time.
 *
 * THE LARGER OPTIONS STILL OVERPROMISE, and that is a known open gap rather
 * than something this constant can fix: one `/gmail/sync` invocation cannot
 * exceed a bucket, and an explicit `count` restarts from the newest message
 * rather than resuming, so pressing 2000 repeatedly re-reads the same window.
 * The path that does read deeply is the inbox mine — it pages, paces itself
 * against 429s, and files what it found. Tracked separately; the options are
 * left in place rather than silently removed, because narrowing a control is a
 * product decision and not a bug fix.
 */
export const SCAN_DEPTH_OPTIONS = [100, 200, 500, 750, 1000, 2000] as const;
export type ScanDepth = (typeof SCAN_DEPTH_OPTIONS)[number];
export const SCAN_DEFAULT_DEPTH: ScanDepth = 200;

/**
 * The window choices, mirroring the inbox's `RANGE_OPTIONS` values (restated
 * here rather than imported to keep this module loadable under `node --test`).
 * `"all"` omits the range bound entirely.
 */
export const SCAN_RANGE_OPTIONS = [
  { value: "3", label: "3 mo" },
  { value: "6", label: "6 mo" },
  { value: "9", label: "9 mo" },
  { value: "12", label: "12 mo" },
  { value: "all", label: "All time" },
] as const;
export type ScanRange = (typeof SCAN_RANGE_OPTIONS)[number]["value"];
/** Matches today's hardwired rebuild (12 months), so the default is not a change. */
export const SCAN_DEFAULT_RANGE: ScanRange = "12";

/**
 * What the scan does with an application it does NOT find in the window.
 *
 * This is the whole reason the windowed scan stopped being called "Rebuild"
 * (#474). Both dispositions re-read the window and re-judge every row they
 * find — that is what heals a row a previous, older build of the classifier
 * got wrong, and it is unreachable from the `Sync` button, which resumes from
 * a Gmail `historyId` cursor and so never re-reads a message it already
 * stored. The two differ only in what happens to the rows the scan misses:
 *
 *   - `keep` — `mode: "additive"`, upsert-only. Nothing leaves the board for
 *     being absent from a bounded scan. This is the DEFAULT, because it is the
 *     one a person actually wants when a row is stale, and because reaching it
 *     used to require running the destructive path: issue #474 records 17 rows
 *     dismissed with `reason='resync'` by owners doing exactly that.
 *   - `remove` — `mode: "rebuild"`, the purge-and-rebuild. Every Gmail-filed
 *     application the scan does not find is taken off the board (rows filed or
 *     corrected by hand are kept), listed on the receipt, and restorable there.
 *
 * `keep` still is not a promise that nothing leaves: an AUTO row whose last
 * linked email turns out to belong to a DIFFERENT employer is retired on both
 * paths (`_dismiss_rows_left_without_mail`). That is why every sentence about
 * this control is worded "rows it doesn't find" and never "removes nothing" —
 * and why the additive path gets the same receipt, with the same per-row
 * restore, when the backend names a removal.
 */
export type ScanDisposition = "keep" | "remove";

/** The segmented control's two choices, in the order they are offered. */
export const SCAN_DISPOSITION_OPTIONS = [
  { value: "keep", label: "Keep them" },
  { value: "remove", label: "Remove them" },
] as const satisfies readonly { value: ScanDisposition; label: string }[];

/** Safe by default: the destructive disposition is never the resting state. */
export const SCAN_DEFAULT_DISPOSITION: ScanDisposition = "keep";

/**
 * Body of `POST /api/gmail/sync` for a WINDOWED scan — the dialog's only
 * request builder, for both dispositions.
 *
 * Three things are load-bearing, and each of them has a way of going quietly
 * wrong:
 *
 *   - `count` is always sent, on both paths. It is what makes the backend
 *     treat this as an explicit window request and drop the incremental cursor
 *     (`_history_cursor_for`: `payload.range is not None or payload.count is
 *     not None`). Omit it and an additive body is just the `Sync` button —
 *     it resumes from the cursor, re-reads nothing, and heals nothing.
 *   - `range` is ALWAYS sent, including `"all"`. This endpoint is not the
 *     inbox mine and does not behave like it: `GET /gmail/inbox` reads
 *     `_parse_range_months(range)` with no fallback, so omitting it there
 *     means all-time, but `POST /gmail/sync` (`_scan_server_side`) reads
 *     `_SYNC_DEFAULT_RANGE_MONTHS if payload.range is None else
 *     _parse_range_months(payload.range)` — a MISSING range there is 12
 *     months, and only the literal `"all"` reaches `_parse_range_months` and
 *     comes back unbounded. Omitting it (which this builder used to do,
 *     "mirroring `buildInboxParams`") made `Rebuild from all time` run a
 *     12-month rebuild while the running line said `all time` and the receipt
 *     reported a clean finish: exactly the overclaim this module exists to
 *     prevent, and for the heal it is fatal — a 14-month-old rejection is
 *     unreachable by the one control that promises to reach it.
 *   - `scope` is sent on the additive path and NOT on the rebuild path. See
 *     the module comment: the server forces `anywhere` for a rebuild and
 *     defaults to `inbox` for everything else, so this asymmetry is what makes
 *     both dispositions read archived mail. Every stale row this feature
 *     exists to heal is an old rejection, and old mail is archived mail.
 */
export function scanRequestBody(
  depth: ScanDepth,
  range: ScanRange,
  disposition: ScanDisposition,
): { mode: "additive" | "rebuild"; count: number; range: string; scope?: "anywhere" } {
  return disposition === "remove"
    ? { mode: "rebuild", count: depth, range }
    : { mode: "additive", count: depth, range, scope: "anywhere" };
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
export function rangeLabel(range: ScanRange): string {
  return range === "all" ? "all time" : `last ${range} months`;
}

/**
 * What a running windowed scan restates about itself:
 * `up to 200 messages · last 12 months · all mail`. Identical on both
 * dispositions, because the scan itself is: `all mail` is forced by the server
 * on the rebuild path and asked for by {@link scanRequestBody} on the additive
 * one (see the module comment). It is stated rather than offered either way —
 * a scan that re-judges filed rows has to be able to read archived mail, so
 * there is no honest control to put here.
 */
export function scanScopeLine(depth: ScanDepth, range: ScanRange): string {
  return `up to ${formatCount(depth)} messages · ${rangeLabel(range)} · all mail`;
}

/**
 * The confirm button names the act it commits, and names it the same way the
 * receipt will report it afterwards ({@link windowedOpName}): press
 * `Scan the last 12 months` and the receipt says `scan finished`; press
 * `Rebuild from the last 12 months` and it says `rebuild finished`. A control
 * whose name changes on the way to its own result is how a removal gets read
 * as somebody else's doing.
 */
export function scanConfirmLabel(range: ScanRange, disposition: ScanDisposition): string {
  if (disposition === "remove") {
    return range === "all" ? "Rebuild from all time" : `Rebuild from the last ${range} months`;
  }
  return range === "all" ? "Scan all time" : `Scan the last ${range} months`;
}

/**
 * What the disposition COMMITS TO, spelled out in the dialog under the
 * control. Both sentences are about the rows the scan does not find, because
 * that is the only thing the choice decides — what it does with the rows it
 * DOES find (re-read them, re-judge them, leave anything you touched alone) is
 * the same either way and is said once, in the dialog's description.
 */
export function scanDispositionNote(disposition: ScanDisposition): string {
  return disposition === "remove"
    ? "Applications filed from Gmail that this scan doesn't find are taken off the board. Each one is named on the receipt afterwards and can be restored from there."
    : "Applications this scan doesn't find stay on the board. Nothing is removed for being outside the window.";
}

/**
 * The verb a running windowed scan wears in the status line — `scanning` or
 * `rebuilding`. Present tense here, past tense on the receipt
 * ({@link windowedOpName}); the same act, so the same word.
 */
export function windowedRunningWord(disposition: ScanDisposition): string {
  return disposition === "remove" ? "rebuilding" : "scanning";
}

/** How the receipt names the run that wrote it — `scan finished · just now`. */
export function windowedOpName(disposition: ScanDisposition): "scan" | "rebuild" {
  return disposition === "remove" ? "rebuild" : "scan";
}

// --- Memory of the last run ---------------------------------------------------

/** What a finished run records for the next dialog to report. */
export interface ScanMemory {
  /** Wall-clock duration of the run, in milliseconds. */
  ms: number;
  /** Messages the run scanned (from the response, not estimated). */
  scanned: number;
  /** Epoch ms of completion. */
  at: number;
}

/** localStorage key for the last WINDOWED run's {@link ScanMemory} — either
 *  disposition, since what the dialog reports is how long a scan of that depth
 *  took, which is a fact about the scan and not about the merge. The string
 *  still says `rebuild` on purpose: it is a storage key, and renaming it would
 *  silently discard every record already on the owner's machine. */
export const WINDOWED_MEMORY_KEY = "applied:rebuild:last";

/**
 * The simulated (demo) surface remembers its windowed runs under its own key,
 * so a signed-in owner who visits /demo never has a fixture run reported back
 * to them as their own last scan.
 */
export const WINDOWED_MEMORY_DEMO_KEY = "applied:rebuild:last:demo";

/** Parse a stored memory record; anything malformed is no record at all. */
export function parseScanMemory(raw: string | null | undefined): ScanMemory | null {
  if (typeof raw !== "string" || raw === "") return null;
  try {
    const data = JSON.parse(raw) as Partial<ScanMemory>;
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
 * `your last windowed scan read 512 messages in 41 s` — a report of a measured
 * past fact, not a prediction. When no record exists the dialog shows nothing;
 * "usually under a minute" claims nobody measured are not invented here.
 *
 * "windowed scan" rather than "rebuild": this dialog writes the record on
 * BOTH dispositions now, and reporting a keep-scan back as a rebuild would
 * name the owner an action they deliberately did not take.
 */
export function windowedMemoryLine(memory: ScanMemory): string {
  const seconds = Math.max(1, Math.round(memory.ms / 1000));
  return `your last windowed scan read ${formatCount(memory.scanned)} messages in ${seconds} s`;
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
  // `rate_limited` falls through to "partial" deliberately, and NOT to
  // "broken": the mailbox is healthy and the connection is intact — Gmail
  // simply asked for less for a minute, so the window is under-covered rather
  // than the sync being faulty. Calling it broken would send a user to
  // reconnect an account that has nothing wrong with it.
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
    case "rate_limited":
      // Number-free, like its neighbours: "waited 60 seconds" would rot the
      // day the backend tunes Retry-After.
      return "paused because Gmail asked for fewer requests";
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
 * than imported for the same reason `SCAN_DEFAULT_DEPTH` is: this module
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
 * Same vocabulary as {@link windowedMemoryLine}, deliberately.
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
  last: ScanMemory | null,
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
 *  same separation {@link WINDOWED_MEMORY_DEMO_KEY} makes for rebuilds. */
export const SYNC_MEMORY_DEMO_KEY = "applied:sync:last:demo";

/**
 * `Your last sync took 3 s.` — the Sync button's tooltip tail, and the closest
 * honest answer to "when will it complete": a measurement of the previous run,
 * worded in the past tense so it cannot be read as a promise about this one.
 * It rides in `title`, which costs the header row no width — the row already
 * wraps at 1024 (#172) and must not be made worse.
 *
 * Reuses {@link ScanMemory}: a run's duration + what it scanned + when, on
 * either path.
 */
export function syncMemoryLine(memory: ScanMemory): string {
  return `Your last sync took ${durationLabel(memory.ms)}.`;
}

// --- Reading the response -----------------------------------------------------

/** One row a run took off the board — id + company, exactly what the backend
 *  names. Any of the three runs can produce these: a rebuild purges what it
 *  did not find, and both additive paths retire a row whose last email turned
 *  out to belong to another employer. */
export interface RemovedRow {
  id: number;
  company: string;
  /** Set by the receipt UI once `POST /applications/{id}/restore` succeeds. */
  restored?: boolean;
}

/** The receipt-relevant slice of the backend `SyncResponse`. */
export interface ScanOutcome {
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
export function readScanOutcome(body: unknown): ScanOutcome {
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
 * explicit nothing-changed sentence when a run confirmed the board unchanged.
 *
 * THE NOTHING-CHANGED SENTENCE IS A CLAIM, and it may only be made when the
 * sync really did account for everything it read. `every filed application
 * matched` was shown to the owner on a run that had just discarded four
 * Microsoft application confirmations, which is how a real product defect
 * reached him as "the sync works, you must not have applied". A run with
 * anything in `dropped` takes the itemised branch instead and names the number.
 */
export function receiptBodyLine(outcome: ScanOutcome): string {
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
