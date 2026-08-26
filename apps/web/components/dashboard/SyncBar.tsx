"use client";

import { Loader2, MoreHorizontal, RefreshCw, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { RowActionsMenu } from "@/components/dashboard/RowActionsMenu";
import { LastSynced } from "@/components/gmail/LastSynced";
import { useSignOut } from "@/components/shell/SessionControls";
import { Dialog } from "@/components/ui/Dialog";
import { Segmented } from "@/components/ui/Segmented";
import { selectClass } from "@/components/ui/formStyles";
import { onScanRequest, requestScan } from "@/lib/dashboard/scan-bus";
import { liveSyncTransport, type SyncTransport } from "@/lib/dashboard/transport";
import { publishAmbientPulse } from "@/lib/shell/ambient-bus";
import {
  SCAN_DEFAULT_DEPTH,
  SCAN_DEFAULT_DISPOSITION,
  SCAN_DEFAULT_RANGE,
  SCAN_DEPTH_OPTIONS,
  SCAN_DISPOSITION_OPTIONS,
  SCAN_RANGE_OPTIONS,
  SYNC_MEMORY_DEMO_KEY,
  SYNC_MEMORY_KEY,
  WINDOWED_MEMORY_DEMO_KEY,
  WINDOWED_MEMORY_KEY,
  formatCount,
  formatElapsed,
  parseScanMemory,
  readScanEnd,
  readScanOutcome,
  receiptBodyLine,
  scanConfirmLabel,
  scanDispositionNote,
  scanProgressLine,
  scanRequestBody,
  scanScopeLine,
  stopKind,
  stopReasonPhrase,
  syncMemoryLine,
  syncReceiptNote,
  syncRunningSentence,
  windowedMemoryLine,
  windowedOpName,
  windowedRunningWord,
  type ScanDepth,
  type ScanDisposition,
  type ScanEnd,
  type ScanMemory,
  type ScanOutcome,
  type ScanRange,
} from "@/lib/gmail/sync-plan";
import { filedSummary, isStale, type SyncCounts } from "@/lib/gmail/sync-state";

/**
 * The one sync surface. Everything the dashboard says about Gmail flows
 * through this component: the header cluster (subtitle, the change-ledger
 * chip, recency, the `Sync` button, the `⋯` overflow), the persistent
 * status/alert line, the scan dialog, and the run receipt.
 *
 * Its header is the page's TOP LINE: one ~40px row carrying the route title
 * (`title` — the page's one <h1>, at every width; at `lg`+ the shell's
 * TopBar yields to this row entirely, see TopBar), the
 * subtitle, the change-ledger chip (`since`), the status/recency slot, the
 * controls, and the session edge. Sign-out therefore stays reachable from
 * the top line of the screen on the board route — inside the `⋯` menu
 * (`signedIn`), not as a row-level button: the button was the ~97px that
 * wrapped this row to 82px at 1024 and cost the worklist the difference
 * (#172), spent on the control the owner uses least. The status
 * line never moves the page at `lg`+ — it rides in the row for exactly as
 * long as it speaks (the owner watched the board jump when "checking Gmail…"
 * used to take a line of its own), and while a sync RUNS it takes the row's
 * flexible middle rather than the board's own totals: blanking
 * `41 filed · 38 open · 0 offers` for the 11 seconds a sync and its note last
 * is what made a working sync read as frozen (#160). Only the two statuses
 * that wait on the user still borrow the subtitle's own slot; see the
 * header-row note below for which, and why. The alert and the
 * receipt DO take lines below the row when present: failures and removals
 * are rare and must not be missable.
 *
 * It replaces three things that used to speak over each other:
 *   - `ReSyncButton` — a prominent button labelled "Re-sync" that silently ran
 *     the DESTRUCTIVE rebuild;
 *   - the rail chip's unlabelled icon that ran the additive sync under the
 *     same icon;
 *   - `GmailSyncTrigger` — the staleness auto-sync, whose logic now lives in
 *     the effect below and reports through the same status line as a manual
 *     press, because the operation is the same.
 *
 * The word "Re-sync" is retired, and the vocabulary has not grown since. Two
 * named ways to START a scan remain:
 *   - **Sync** — one press, no dialog. Additive and INCREMENTAL: it resumes
 *     from Gmail's `historyId` cursor, so it reads what arrived since the last
 *     run and nothing else. It removes nothing for being absent from the scan —
 *     but ONE shape of row can still leave the board (an application whose last
 *     email turned out to be a different company's), so when the backend names
 *     removals a sync gets the same receipt a rebuild does, with the same
 *     per-row restore. A board that changed silently is what let 22 removals go
 *     unnoticed for two days.
 *   - **a windowed scan** — the `Scan a window of Gmail` dialog. Pick a window
 *     and a depth, and the backend re-reads that window from scratch (an
 *     explicit `count` drops the cursor) — INCLUDING mail it has already
 *     stored. That re-read is the only way a row filed by an older build of the
 *     classifier ever gets judged again, and until #474 it did not exist: the
 *     cursor meant a routine sync never looked at a stored message twice, and
 *     the only windowed path on this surface was the destructive one.
 *
 * **Rebuild is no longer an action you start.** It is one of two dispositions
 * inside that dialog — what happens to applications the scan does NOT find,
 * `Keep them` or `Remove them` — and `Keep them` is the default. This is a
 * removal of vocabulary, not an addition: the same two words the surface always
 * had, with the destructive one demoted from the tier you press to the tier you
 * choose, where it can no longer be reached by accident. #474 records 17 rows
 * dismissed with `reason='resync'` by owners who ran the purge because it was
 * the only windowed thing here; that is the accident this closes.
 *
 * "Scan" is not a new word. It is the one this surface has always used for the
 * operation both actions perform — `continue the scan`, `scanned`, `the scan
 * hit its message limit`, `first scan · last 12 months`, `scanProgressLine`.
 * The dialog's title just says out loud what its controls were always
 * configuring.
 *
 * There is deliberately NO progress percentage anywhere here: the server sync
 * is one request that returns once, so any fraction would be fabricated. What
 * runs instead is honest — the scope stated up front, a count-up clock
 * (elapsed time is the one number the browser truly knows), the LAST run's
 * measured duration joining the line once this run outlasts it (the mid-run
 * answer to "how long will this take", #160 — see `syncRunningSentence`), and
 * the measured duration of the last windowed run remembered for the next dialog.
 *
 * That rule was re-tested against the real board rather than assumed (#160).
 * Timed on the signed-in dashboard at 1024: `POST /api/gmail/sync` takes
 * 2.7-3.1 s, the button disables for exactly that long, the clock ticks
 * 0:00 -> 0:02, no `longtask` entry is recorded (the main thread is never
 * blocked — `transport.sync` is an awaited `fetch`) and the document height
 * never leaves `innerHeight`. It is not frozen; it was uninformative.
 *
 * The response is what settles the design:
 * `{scanned: 0, result_size_estimate: null, stopped_by: "complete"}`. With a
 * Gmail history cursor on file the backend reads only what changed, so a
 * routine sync examines NO messages and Gmail offers NO estimate — there is
 * no numerator and no denominator to advance, and a count that moved anyway
 * would be exactly the fabrication this note forbids. So the run now states
 * what it COVERS (`syncScopeLine`, from `hasCursor`), and the receipt states
 * how long it took and — on the full-scan path, where both numbers are real —
 * how far it got, clamped and worded "roughly". A percentage still appears
 * nowhere.
 */

/** The Gmail connection facts the server render hands down. `null` = unknown. */
export interface SyncGmailState {
  connected: boolean;
  lastSyncAt: string | null;
  hasCursor: boolean;
  syncStatus: string | null;
  syncError: string | null;
}

/**
 * How a run names itself, from the control that started it through to the
 * receipt that reports it — `Sync` → `sync finished`, `Scan the last 12
 * months` → `scan finished`, `Rebuild from the last 12 months` → `rebuild
 * finished`. The windowed pair is derived from the dialog's disposition by
 * `windowedOpName`, never chosen here: a receipt headed "rebuild finished"
 * over a keep-scan would send the reader looking for a purge they declined.
 */
type SyncOp = "sync" | "scan" | "rebuild";

type SyncPhase =
  | { kind: "idle" }
  | { kind: "syncing"; startedAt: number }
  /** Additive finished — `end` says HOW. A partial end never renders as done. */
  | { kind: "synced"; note: string; end: ScanEnd }
  /** A WINDOWED run is in flight. It carries the DISPOSITION rather than the
   *  op name because that is what the dialog committed to; the verb the status
   *  line wears (`scanning` / `rebuilding`) and the name the receipt will use
   *  are both derived from it, so the running line and the receipt cannot
   *  drift from the button that was pressed. */
  | {
      kind: "windowed";
      disposition: ScanDisposition;
      startedAt: number;
      scopeLine: string;
    }
  /** A run that changed the board enough to owe a receipt. `op` is which run
   *  wrote it: a windowed run always gets one, a plain sync only when it
   *  removed rows. */
  | { kind: "receipt"; op: SyncOp; outcome: ScanOutcome }
  /** Additive scan broke mid-flight (disconnected / unexpected mode). */
  | { kind: "interrupted"; end: ScanEnd }
  | { kind: "failed"; op: SyncOp; notConnected: boolean };

/** Cooldown so the staleness auto-sync runs at most once per window per tab. */
const AUTOSYNC_KEY = "applied:dashboard:autosync:lastAt";
const AUTOSYNC_COOLDOWN_MS = 10 * 60 * 1000; // 10 minutes

/** How long a finished sync's resting note holds the status slot before the
 *  row goes quiet again. Long enough to read one short sentence — the board's
 *  own totals stay put right through the run (#160), and the change ledger
 *  rides its own line now (#212), so this dwell costs neither. */
const SYNCED_NOTE_MS = 6000;

function recentlyAutoSynced(): boolean {
  try {
    const raw = window.sessionStorage.getItem(AUTOSYNC_KEY);
    return raw != null && Date.now() - Number(raw) < AUTOSYNC_COOLDOWN_MS;
  } catch {
    return false;
  }
}

function markAutoSynced(): void {
  try {
    window.sessionStorage.setItem(AUTOSYNC_KEY, String(Date.now()));
  } catch {
    // sessionStorage unavailable — degrade to the per-mount guard only.
  }
}

function readScanMemoryFromStorage(key: string) {
  try {
    return parseScanMemory(window.localStorage.getItem(key));
  } catch {
    return null;
  }
}

function writeScanMemory(key: string, ms: number, scanned: number): void {
  try {
    window.localStorage.setItem(key, JSON.stringify({ ms, scanned, at: Date.now() }));
  } catch {
    // Memory is a nicety; the dialog simply shows nothing next time.
  }
}

/**
 * "Choose a window" — the empty state's route into the scan dialog. Raises the
 * scan-bus signal answered by the mounted SyncBar; if no SyncBar is listening
 * (it always is on the connected dashboard, but a control must never silently
 * do nothing) it falls back to the inbox workbench, which has its own window
 * controls.
 *
 * The label got MORE true with #474, not less: an empty board pressing this
 * used to land in a purge dialog, and now lands in a scan that defaults to
 * keeping what it does not find — which on an empty board is the same run and
 * a much better default on any other.
 */
export function ScanWindowButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => {
        if (!requestScan()) router.push("/inbox");
      }}
      className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
    >
      Choose a window
    </button>
  );
}

export function SyncBar({
  subtitle,
  gmail,
  since,
  title,
  trailing,
  signedIn = false,
  children,
  transport = liveSyncTransport,
}: {
  /** The page's one honest line of state — `214 filed · 32 open · 1 offer`. */
  subtitle: string;
  gmail: SyncGmailState | null;
  /** The change-ledger chip (`SinceLastLook`) — one line by that component's
   *  own contract, mounted as an overlay on the bar's centre at `lg`+ and as
   *  the stacked header's own line below: the dashboard's notification
   *  centre (#212). Every in-FLOW desktop placement failed in sequence —
   *  flush after the subtitle it read as the totals' caption (#196), hung
   *  off the far side it read as a trailing annotation on the sync cluster,
   *  centred in the row's leftover middle it wandered against the bar
   *  (130px right of the bar's centre at 1024, 137px left at 1280 — the
   *  flanks are that asymmetric) and got carried to a line-end whenever the
   *  row wrapped, and a dedicated line under the row held the centre but
   *  spent 26px the worklist owns (#172's refund; session-edge.spec's floor
   *  caught it). Out of the row's flow, over its empty middle, is the one
   *  placement that is centred on the bar AND free. See the notification
   *  overlay below for the mechanics. A slot rather than an import: the
   *  ledger's rows/scope are the caller's business, and the error/empty
   *  pages pass nothing. */
  since?: ReactNode;
  /** The route title. Rendered as the page's ONE <h1>, at every width — the
   *  shell's TopBar renders no title on this route (see TopBar), so the
   *  document outline holds exactly one heading and no CSS-hidden twin ever
   *  exists for a locator to trip over. At `lg`+ this row is also the
   *  screen's top line, TopBar having yielded entirely. */
  title?: string;
  /** Row-level chrome at the session edge — the demo pill on the fixture
   *  twin, and nothing else: a row-level button here is what wrapped the row
   *  at 1024 (#172). The signed-in sign-out rides in the `⋯` menu via
   *  `signedIn` instead. `lg`+ only. */
  trailing?: ReactNode;
  /** Render the SIGNED-IN arrangement of this row. Two things ride on it,
   *  both below: `Sign out` folds into the row's `⋯` menu — menu chrome, not
   *  a row-level control (see `trailing`) — and the recency slot carries the
   *  live `LastSynced` instead of the fixture frame, because a stand-in that
   *  keeps that frame's extra 69px is not standing in for this row's geometry
   *  at all (see that slot for the measurement). It also makes the menu render
   *  when Gmail is NOT connected: at `lg`+ the shell's TopBar yields on the
   *  board route, so this menu is the route's only sign-out. The fixture twin
   *  passes nothing — no session, no item — unless it is deliberately standing
   *  in for the signed-in row (/demo/shell?session=1), which is the one place
   *  this prop is true off the signed-in page. */
  signedIn?: boolean;
  /** The compact `+` (AddApplicationForm) — stays rightmost in the cluster. */
  children?: ReactNode;
  /** How sync requests reach data — Gmail via the proxy by default; the demo
   *  passes a simulated transport so this same state machine runs on fixtures. */
  transport?: SyncTransport;
}) {
  const router = useRouter();
  const { signOut } = useSignOut();
  const [phase, setPhase] = useState<SyncPhase>({ kind: "idle" });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [range, setRange] = useState<ScanRange>(SCAN_DEFAULT_RANGE);
  const [depth, setDepth] = useState<ScanDepth>(SCAN_DEFAULT_DEPTH);
  /** What the dialog will do with rows the scan doesn't find. Reset to the
   *  safe default every time the dialog OPENS (`openDialog`), never merely
   *  initialised here: a destructive choice that survives in component state
   *  is a destructive default for the next press. */
  const [disposition, setDisposition] = useState<ScanDisposition>(SCAN_DEFAULT_DISPOSITION);
  const [memoryLine, setMemoryLine] = useState<string | null>(null);
  /** The last measured sync — duration, coverage, when. Feeds the Sync
   *  button's tooltip tail (`Your last sync took 3 s.`) and the running
   *  line's outlasted swap (see `syncRunningSentence`, #160). Held in state
   *  rather than read during render because localStorage does not exist on
   *  the server pass. */
  const [lastSync, setLastSync] = useState<ScanMemory | null>(null);
  /** Ticks while any run is in flight so the elapsed clock stays honest. */
  const [nowMs, setNowMs] = useState(() => Date.now());
  const autoRan = useRef(false);
  /** The last windowed run's full request — what "continue the scan" and the
   *  failure line's "try again" re-issue. The DISPOSITION is part of it: a
   *  retry that quietly changed what happens to unfound rows would be a
   *  different operation wearing the same button. */
  const lastWindowed = useRef<{
    depth: ScanDepth;
    range: ScanRange;
    disposition: ScanDisposition;
  } | null>(null);

  const connected = gmail?.connected === true;
  const hasCursor = gmail?.hasCursor === true;
  const lastSyncAt = gmail?.lastSyncAt ?? null;
  const reduceMotion = useReducedMotion();
  const simulated = transport.mode === "simulated";
  const memoryKey = simulated ? WINDOWED_MEMORY_DEMO_KEY : WINDOWED_MEMORY_KEY;
  const syncMemoryKey = simulated ? SYNC_MEMORY_DEMO_KEY : SYNC_MEMORY_KEY;
  const busy = phase.kind === "syncing" || phase.kind === "windowed";

  const runSync = useCallback(async () => {
    const startedAt = Date.now();
    setPhase({ kind: "syncing", startedAt });
    // Additive, and deliberately NO `count`/`range`: either of those makes
    // the backend treat the call as an explicit window request and disable
    // the incremental cursor (`_history_cursor_for`), restoring the full
    // rescan this surface exists to remove.
    const res = await transport.sync({ mode: "additive" });
    if (!res.ok) {
      setPhase({
        kind: "failed",
        op: "sync",
        notConnected: res.status === 409,
      });
      return;
    }
    const data = res.body as Partial<SyncCounts>;
    const end = readScanEnd(res.body);
    // Timed and remembered HERE, before the interrupted/receipt branches
    // return: a run that broke mid-scan or took rows off the board still took
    // real wall-clock time, and leaving those out made the button's tooltip
    // report an older run as if it were the last one.
    const elapsedMs = Date.now() - startedAt;
    writeScanMemory(syncMemoryKey, elapsedMs, end.scanned);
    setLastSync({ ms: elapsedMs, scanned: end.scanned, at: Date.now() });
    // The rail's ambient field is a status surface (ambient-bus): a run that
    // actually changed the board — filed, updated or removed rows — surges
    // it, sized to the news, and this covers the staleness auto-sync too
    // because that funnels through here. Hoisted above the interrupted
    // branch: a scan that broke mid-flight still filed what it found. A
    // "no new mail" pass publishes nothing — a field that stirred for
    // nothing would train the eye to ignore it.
    const outcome = readScanOutcome(res.body);
    const changed = outcome.created + outcome.updated + outcome.removed.length;
    if (changed > 0) publishAmbientPulse(changed);
    // Disconnected / unexpected mid-scan is not "press again" — it is
    // "something is wrong", and it gets the alert, not a resting note.
    if (stopKind(end.stoppedBy) === "broken") {
      setPhase({ kind: "interrupted", end });
      router.refresh();
      return;
    }
    // Cursored zero case: the scan only looked at what arrived since the
    // last one, so "nothing to file · N scanned" would imply a claim about a
    // window it never checked. Only a COMPLETE scan may say it — a partial
    // one cannot vouch that nothing new exists.
    // A sync that took rows OFF the board owes the same receipt a rebuild
    // owes — named rows, one click to restore each. It is rare (only a row
    // whose last email turned out to belong to another employer), and a
    // resting note like "2 filed" would not mention it at all.
    if (outcome.removed.length > 0) {
      setPhase({ kind: "receipt", op: "sync", outcome });
      router.refresh();
      return;
    }
    const nothingFiled = (data.created ?? 0) <= 0 && (data.updated ?? 0) <= 0;
    // When the scan read messages AND Gmail offered an estimate, the coverage
    // fragment `syncReceiptNote` appends is where `scanned` gets said. Hand
    // `filedSummary` the counts without it so the same number is not reported
    // twice in two different vocabularies.
    const reportsCoverage = end.scanned > 0 && end.estimate !== null;
    const base =
      nothingFiled && hasCursor && stopKind(end.stoppedBy) === "complete"
        ? // Shortened from "no new application mail since your last sync",
          // which measured 231px in this row's 208px status slot and was
          // CLIPPED mid-word — the owner's screen read "…since your last".
          "no new mail since last sync"
        : filedSummary(
            reportsCoverage ? { created: data.created, updated: data.updated } : data,
          );
    setPhase({ kind: "synced", note: syncReceiptNote(base, end, elapsedMs), end });
    router.refresh();
  }, [hasCursor, router, syncMemoryKey, transport]);

  /**
   * The WINDOWED run — both dispositions, one code path, because they are one
   * operation that differs only in how the backend merges the result. Every
   * difference between them is derived from `disp` at the edges: the request
   * body (`scanRequestBody` — additive carries `scope: "anywhere"`, rebuild
   * does not), the status verb, and the name on the receipt.
   *
   * It cannot become an incremental sync by accident: `scanRequestBody` always
   * sends `count`, which is what tells the backend to drop the Gmail history
   * cursor and re-list the window from scratch. That re-list is the entire
   * point — a cursored sync never re-reads a stored message, so a row a
   * previous build of the classifier judged wrongly is unreachable from `Sync`
   * no matter how many times it is pressed (#474).
   */
  const runScan = useCallback(
    async (d: ScanDepth, r: ScanRange, disp: ScanDisposition) => {
      lastWindowed.current = { depth: d, range: r, disposition: disp };
      const op = windowedOpName(disp);
      const startedAt = Date.now();
      setPhase({
        kind: "windowed",
        disposition: disp,
        startedAt,
        scopeLine: scanScopeLine(d, r),
      });
      const res = await transport.sync(scanRequestBody(d, r, disp));
      if (!res.ok) {
        setPhase({
          kind: "failed",
          op,
          notConnected: res.status === 409,
        });
        return;
      }
      const outcome = readScanOutcome(res.body);
      writeScanMemory(memoryKey, Date.now() - startedAt, outcome.scanned);
      // Same news contract as runSync: the ambient field surges by what the
      // run actually changed, never for the run's own sake. A keep-scan that
      // re-judged three stale rows counts as three — that is exactly the news
      // this path exists to deliver.
      const changed = outcome.created + outcome.updated + outcome.removed.length;
      if (changed > 0) publishAmbientPulse(changed);
      // A windowed run ALWAYS gets a receipt, on either disposition — unlike a
      // plain sync, which only owes one when it removed rows. The owner asked
      // for a re-read of a specific window and is owed the answer to "what did
      // that find", even when the answer is nothing.
      setPhase({ kind: "receipt", op, outcome });
      router.refresh();
    },
    [memoryKey, router, transport],
  );

  // The staleness auto-sync (absorbed from the old GmailSyncTrigger): one
  // attempt per mount, gated on server truth (`last_sync_at`) and the per-tab
  // cooldown. It reports through the same status line as a manual press — the
  // initiator is not displayed because the operation is the same.
  useEffect(() => {
    if (autoRan.current) return;
    autoRan.current = true;
    // The demo's simulated account never auto-syncs: a visitor should pull the
    // lever themselves, and the e2e walks the states from a known idle start.
    if (!connected || simulated) return;
    // Deferred off the effect body (house rule — no synchronous setState in an
    // effect): the staleness check and the sync kick off in a macrotask.
    const id = window.setTimeout(() => {
      if (!isStale(lastSyncAt, Date.now()) || recentlyAutoSynced()) return;
      // Stamp before the request so a rapid re-navigation cannot double-fire.
      markAutoSynced();
      void runSync();
    }, 0);
    return () => window.clearTimeout(id);
  }, [connected, simulated, lastSyncAt, runSync]);

  // The empty state's "Choose a window" button opens the same dialog.
  useEffect(() => onScanRequest(() => setDialogOpen(true)), []);

  // The remembered duration of the last sync, read once per mount. Nothing
  // shows until a run has actually been timed — an unmeasured "usually quick"
  // is the kind of claim this surface does not make.
  useEffect(() => {
    // Deferred off the effect body (house rule — no synchronous setState in
    // an effect), which also keeps the read off the server pass entirely.
    const id = window.setTimeout(() => {
      setLastSync(readScanMemoryFromStorage(syncMemoryKey));
    }, 0);
    return () => window.clearTimeout(id);
  }, [syncMemoryKey]);

  // Elapsed clock: tick only while something runs. The clock is aria-hidden —
  // announcing a ticking number every second is noise, and the sentence
  // beside it already carries the state.
  useEffect(() => {
    if (!busy) return;
    // No synchronous tick: the first paint of a fresh run computes a ≤0
    // elapsed, which formatElapsed clamps to 0:00 — no stale value shows.
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  // A finished run's note is a RECEIPT, not a state, so it decays. It has to:
  // at `lg`+ that note takes the row's middle (see the header-row note
  // below), and `synced` had no exit but the receipt dialog — which a
  // plain sync never opens. So one press hid the board's totals for the rest
  // of the session, on the signed-in dashboard as well as the demo. A
  // partial scan is excluded on purpose: it carries a
  // "continue the scan" control, and a control must not vanish under the
  // cursor.
  useEffect(() => {
    if (phase.kind !== "synced") return;
    if (stopKind(phase.end.stoppedBy) === "partial") return;
    const id = window.setTimeout(() => setPhase({ kind: "idle" }), SYNCED_NOTE_MS);
    return () => window.clearTimeout(id);
  }, [phase]);

  function openDialog() {
    setMemoryLine(() => {
      const memory = readScanMemoryFromStorage(memoryKey);
      return memory ? windowedMemoryLine(memory) : null;
    });
    // Window and depth persist across opens — they are preferences, and
    // re-picking "6 mo" every time would be a chore. The DISPOSITION does not:
    // it is a decision about this run, and a `Remove them` left standing from
    // ten minutes ago would be a destructive default wearing a fresh dialog.
    // Every open starts safe.
    setDisposition(SCAN_DEFAULT_DISPOSITION);
    setDialogOpen(true);
  }

  function restoreSucceeded(id: number) {
    setPhase((p) => {
      if (p.kind !== "receipt") return p;
      return {
        ...p,
        outcome: {
          ...p.outcome,
          removed: p.outcome.removed.map((row) =>
            row.id === id ? { ...row, restored: true } : row,
          ),
        },
      };
    });
    router.refresh();
  }

  // --- Status / alert content -------------------------------------------------
  // One persistent `role="status"` element and one `role="alert"` sibling,
  // always in the DOM (mounting live regions on demand drops announcements).
  let statusContent: ReactNode = null;
  let alertContent: ReactNode = null;

  if (phase.kind === "syncing") {
    const elapsed = nowMs - phase.startedAt;
    statusContent = (
      <>
        {/* `lg:hidden`: at `lg`+ this line sits flush against the Sync button
            (see the motion.span below) and the button's own icon is already
            spinning — two spinners a gap apart read as two operations. Below
            `lg` the line is on its own wrap-line, where the spinner is the
            state's one moving mark besides the clock. */}
        <Loader2
          className="h-3 w-3 shrink-0 animate-spin motion-reduce:animate-none lg:hidden"
          aria-hidden
        />
        {/* Beside the totals at `lg`+ this line cannot wrap, so it has to say
            what gives first: the SENTENCE does, with an ellipsis. Measured at
            1024 on the signed-in board, where the row's spare width runs out
            mid-clock. */}
        {/* What the run COVERS, not just that one is happening. `hasCursor`
            is server truth and picks the backend's path, so this is the one
            honest thing about the scan that is knowable before it returns —
            measured: a cursored sync comes back `scanned: 0` with no
            estimate, so there is nothing to count while it runs and any
            advancing number would be invented. Once the run outlasts the
            LAST measured one, the sentence answers "how long" with that
            measurement — past tense, never a forecast. See
            `syncRunningSentence` for both halves and the width budget. */}
        <span className="lg:min-w-0 lg:truncate">
          {syncRunningSentence(hasCursor, elapsed, lastSync)}
        </span>
        {/* The clock from the first tick, not only once the run is slow: a
            typical sync is ~3s, so under the old gate nothing in this line
            ever changed before it was over. Never shrinks — it is the one
            thing here that MOVES, and a sync with nothing moving is what was
            reported as frozen. aria-hidden: the sentence carries the state,
            and announcing a number every second is noise. */}
        <span className="tabular shrink-0 font-mono text-[11px]" aria-hidden>
          · {formatElapsed(elapsed)}
        </span>
      </>
    );
  } else if (phase.kind === "windowed") {
    statusContent = (
      <>
        <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
        {/* `scanning` or `rebuilding` — the verb the pressed button committed
            to, so a keep-scan never announces itself as a purge. Same scope
            fragment either way: the two runs read the same mail. */}
        {windowedRunningWord(phase.disposition)} · {phase.scopeLine}
        <span className="tabular font-mono text-[11px]" aria-hidden>
          · {formatElapsed(nowMs - phase.startedAt)}
        </span>
      </>
    );
  } else if (phase.kind === "synced") {
    // A partial scan must never read as a resting "done": it says it stopped,
    // why, how far it got, and offers continue as the one action — the state
    // that used to cost six presses, each reported as completion.
    statusContent =
      stopKind(phase.end.stoppedBy) === "partial" ? (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>{phase.note}</span>
          <span className="text-review">
            · the scan {stopReasonPhrase(phase.end.stoppedBy)} ·{" "}
            {scanProgressLine(phase.end.scanned, phase.end.estimate)}
          </span>
          <button
            type="button"
            onClick={() => void runSync()}
            className="rounded border border-review/50 px-2 py-0.5 text-xs font-medium text-strong transition-colors hover:border-review"
          >
            continue the scan
          </button>
        </span>
      ) : (
        // Truncating, not clipping. Beside the totals this box is
        // `lg:overflow-hidden`, which cut the note off mid-word with no
        // ellipsis — measured at 1024 on the signed-in board, the finished
        // sentence overflowed its 208px slot by 23px and read "…since your
        // last". The note is shorter now AND degrades to an ellipsis, so a
        // longer receipt can never again look like the sentence broke.
        //
        // `title` because one receipt still cannot fit: a COMPLETED full scan
        // reports its coverage too ("3 filed, 1 already known · scanned 412 of
        // roughly 1,200 · 3 s" measures 313px in the 208px slot). That is the
        // first-sync path, not the routine one — the cursored sync this issue
        // is about fits at 169px — and the ellipsis is recoverable on hover
        // rather than a number silently lost. The duration is also kept in the
        // Sync button's own tooltip, so it survives the truncation regardless.
        <span className="lg:min-w-0 lg:truncate" title={phase.note}>
          {phase.note}
        </span>
      );
  } else if (phase.kind === "idle" && connected && gmail?.syncStatus === "error") {
    // Resting after a failed run: the backend keeps `last_sync_at` at the last
    // good sync, so recency and this line are two facts, both shown.
    statusContent = (
      <span className="text-reject-ink">
        last sync failed{gmail.syncError ? ` · ${gmail.syncError}` : ""}{" "}
        <button
          type="button"
          onClick={() => void runSync()}
          className="text-muted underline-offset-2 hover:text-strong hover:underline"
        >
          try again
        </button>
      </span>
    );
  }

  if (phase.kind === "interrupted") {
    alertContent =
      phase.end.stoppedBy === "disconnected" ? (
        <>
          the scan lost its Gmail connection partway · what it found so far is filed{" "}
          <Link
            href="/settings"
            className="text-muted underline-offset-2 hover:text-strong hover:underline"
          >
            reconnect in settings →
          </Link>
        </>
      ) : (
        // `relay` (or anything else broken): this surface never relays items,
        // so the response shape itself is wrong — retrying will not help.
        <>the scan answered in an unexpected mode · your board shows what was filed so far</>
      );
  }

  if (phase.kind === "failed") {
    alertContent = phase.notConnected ? (
      <>
        Gmail is not connected · nothing was changed{" "}
        <Link
          href="/settings"
          className="text-muted underline-offset-2 hover:text-strong hover:underline"
        >
          connect in settings →
        </Link>
      </>
    ) : (
      <>
        {/* This line used to claim "nothing was changed. Your board is exactly
            as it was", on the stated grounds that "the backend applies a
            rebuild transactionally or not at all; if that ever stops being
            true this copy must change with it". It is not true, and appears
            never to have been: BOTH merges call
            `upsert_applications_for_user`, which runs its own
            `session.commit()` (applications.py) before either caller reaches
            its final one. On the rebuild path the purge is flushed BEFORE that
            call, so a failure in the window after it leaves rows dismissed and
            not re-filed — the state in which "your board is exactly as it was"
            is not merely imprecise but the opposite of what the reader is
            looking at.
            So the line says the one thing that is true on every path and at
            every failure point, and the button beside it carries the action.
            The `409` branch above keeps its stronger claim, and may: the
            backend returns it before any scan or merge begins. */}
        {phase.op} failed · anything it filed or removed before stopping stays that way{" "}
        <button
          type="button"
          onClick={() => {
            // A retry re-issues the SAME request, disposition included —
            // never a different operation under the same word.
            if (phase.op !== "sync" && lastWindowed.current) {
              const { depth: d, range: r, disposition: disp } = lastWindowed.current;
              void runScan(d, r, disp);
            } else {
              void runSync();
            }
          }}
          className="text-muted underline-offset-2 hover:text-strong hover:underline"
        >
          try again
        </button>
      </>
    );
  }

  // Recency and the status line never say two things at once. The simulated
  // surface has no recency to claim, so its slot carries the one honest frame
  // instead — every other sentence in the machine stays the product's own.
  const showRecency = connected && statusContent === null && alertContent === null;

  // Who yields to a speaking status at `lg`+.
  //
  // The change ledger no longer competes at all: it rides its own line below
  // the row (#212), so the row's middle is the status line's alone — hiding
  // the ledger while a sync spoke was a width contest that no longer exists.
  // The board's own totals yield only to the two statuses that WAIT ON THE
  // USER — the stopped-early scan (it carries "continue the scan") and the
  // resting "last sync failed". Those hold the row indefinitely, they are
  // long, and no fixture exercises them; the header wrapping to two lines
  // costs the worklist ~30px against a 7px floor margin, so they keep the
  // slot to themselves until task #96 gives them one.
  //
  // Everything routine rides ALONGSIDE the totals instead: the running sync
  // and a finished sync's short note. That is #160 — the board's own
  // `41 filed · 38 open · 0 offers` disappeared behind one sentence for the
  // whole 11 seconds a sync plus its note lasts, and losing the numbers you
  // were reading is what a working sync felt like when it was called frozen.
  // An ALLOWLIST on purpose: a status added later defaults to owning the
  // slot, which is the safe side of the wrap. The `windowed` run is deliberately
  // not in it — its line restates verb, window, depth and scope, and is the
  // widest status this row has.
  const statusRidesAlongTotals =
    phase.kind === "syncing" ||
    (phase.kind === "synced" && stopKind(phase.end.stoppedBy) !== "partial");
  const statusTakesSlot = statusContent !== null;
  const statusOwnsSlot = statusTakesSlot && !statusRidesAlongTotals;

  return (
    // `data-sync-surface` scopes assertions (e.g. "no percentage anywhere in
    // the sync UI") to this surface without leaning on copy or classes.
    // `relative` guards the alert region below, which wears `sr-only` while
    // silent. Tailwind's `.sr-only` is `position: absolute`, so without a
    // positioned ancestor it resolves against the INITIAL containing block —
    // escaping every `overflow` above it and planting a box at document scale.
    // That is exactly how the board's own review queue made the whole shell
    // scroll (#149); measured here, this node's `offsetParent` really was
    // `body`. It is inert today only because Tailwind pins `sr-only` to 1×1 at
    // the top of the content column, which is a coincidence of position, not a
    // guarantee — the same node one flex-column lower is the same bug.
    <div className="relative flex flex-col gap-2" data-sync-surface="">
      {/* --- The header row -------------------------------------------------
          At `lg`+ in the shell this IS the screen's top line: TopBar yields
          on the board route, so the title, the state, the sync controls and
          the session edge share one ~40px row instead of a 48px bar with an
          empty middle plus a second row under it. (The change ledger rides
          its own line just below — #212, see the notification-line note.)

          ZERO LAYOUT SHIFT is a requirement of this row (the owner watched
          the whole page jump when "checking Gmail…" appeared): at `lg`+ the
          status line does not get a line of its own — it takes the row's
          flexible middle for exactly as long as it has something to say, so
          idle → checking → result → idle never changes the row's height. "As
          long as it has something to say" is enforced by the decay above, not
          merely intended: a note that never expired held this slot for the
          rest of the session. Riding beside the totals it is also pinned
          `nowrap` at `lg`+: a status that wrapped inside its own box would
          grow this row just as surely as one on its own line.
          The totals themselves no longer go with it — a sync blanked them for
          11 seconds and that read as the page breaking (#160). Two statuses
          still take the subtitle's slot, both because they wait on the user
          with a control and have no end of their own: the stopped-early scan
          and the resting "last sync failed". They are unchanged here; task
          #96 owes them a fixture before that can be. Below `lg` the row
          stacks and the status keeps its own line, as before. */}
      {/* `relative` is historical now that the ledger's panel anchors to its
          own line below (#212) — kept because removing a containing block
          silently re-parents any future absolute child (see the sr-only
          lesson on the wrapper above).

          `data-sync-header-row` names the row for the one assertion that is
          ABOUT the row itself — "does it still hold one line at 1024"
          (`tests/e2e/session-edge.spec.ts`). Same reasoning as
          `data-sync-surface` above: a geometry assertion that had to find
          this box by its class list would go quietly vacuous the first time
          the flex utilities were touched, and this row's height is exactly
          what #172 was about. */}
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2" data-sync-header-row="">
        {title ? (
          <h1 className="shrink-0 text-sm font-semibold tracking-tight text-strong">{title}</h1>
        ) : null}
        <p
          data-sync-subtitle=""
          className={`tabular shrink-0 text-[13px] text-muted ${statusOwnsSlot ? "lg:hidden" : ""}`}
        >
          {subtitle}
        </p>
        {/* The change ledger used to ride here, in the row's flexible middle.
            It overlays the row now (#212) — mounted below as the row's last
            child — which also ends the width contest between it and the
            status: the row's middle is the status line's alone. */}
        {/* The status live region — persistent (mounting live regions on
            demand drops announcements), sr-only while silent. When it speaks
            it takes the subtitle's slot at `lg`+ (see the row note above) and
            its own wrap-line below `lg`. The inner span is keyed by the
            machine's state so each transition slides its sentence in — the
            state CHANGE is visible, not just the state. */}
        <p
          role="status"
          aria-live="polite"
          // Named for the specs: the surface holds a SECOND role="status"
          // now — the filing receipt inside the `+` (AddApplicationForm,
          // #81) — so "the sync status line" must be addressable without
          // resolving to both.
          data-sync-status=""
          className={
            statusContent === null
              ? "sr-only"
              : `min-w-0 text-xs text-muted max-lg:order-last max-lg:basis-full lg:flex-1 ${
                  // Beside the totals the row has no spare height to give: at
                  // `lg`+ this box clips rather than wraps. Clipping the tail
                  // of a sentence the totals now carry the state for is the
                  // cheaper failure — the row growing is the one the owner
                  // reported.
                  statusRidesAlongTotals ? "lg:overflow-hidden" : ""
                }`
          }
        >
          <motion.span
            key={phase.kind}
            initial={reduceMotion ? false : { opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            // `lg:justify-end` for the riding statuses is #196's second half:
            // the running counter and the finished note used to sit at the
            // slot's LEFT edge — visually a tail on the totals, a full row
            // away from the button that was pressed. Right-anchored, the
            // sentence lands flush against the action cluster, exactly where
            // the recency phrase (hidden while a status speaks) otherwise
            // sits — feedback co-located with the control, in the same slot
            // geometry, so the zero-shift contract above is untouched. The
            // slot-owning statuses keep the left edge: they replace the
            // subtitle, and a right-anchored "continue the scan" would strand
            // its sentence mid-row.
            className={`flex flex-wrap items-center gap-2 ${
              statusRidesAlongTotals ? "lg:flex-nowrap lg:justify-end lg:whitespace-nowrap" : ""
            }`}
          >
            {statusContent}
          </motion.span>
        </p>
        {/* Below `sm` the action cluster takes its own full-width line under
            the state, anchored LEFT — flex-wrap + justify-end orphaned "File
            an application" on its own right-aligned line with a dead gap
            beside it. The recency phrase drops to a quiet line of its own
            down there (`order-last`), so the controls read as one bar. */}
        {/* `data-sync-subtitle` / `data-sync-cluster` name the chip's two
            row-neighbours for measurement — the overlaid plate keeps a
            measured clearance from both (see SinceLastLook's placePlate and
            shell.spec's gate), and a class-list selector for either would go
            vacuous the first time the utilities moved. */}
        <div
          data-sync-cluster=""
          className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto sm:justify-end"
        >
          {connected ? (
            <>
              {showRecency ? (
                simulated && !signedIn ? (
                  // The fixture frame, and why `signedIn` excludes it.
                  // A row asked for the signed-in session edge is standing in
                  // for the signed-in row — that is the whole contract of
                  // /demo/shell's `?session=1` — and this frame is 69px wider
                  // than the recency phrase the live row carries. Measured at
                  // 1024 on the twin (headless Chromium, `next start`):
                  // "simulated account · nothing is read" lays out at 184.5px
                  // against 115.17px for "synced 3 minutes ago", and that
                  // difference alone wraps this row to two lines with the
                  // session edge in EITHER arrangement — so the twin reported
                  // a wrap that the surface it stands in for does not have,
                  // and the one measurement #172 rests on was unmeasurable
                  // through it. With the real component in the slot the same
                  // rig separates them cleanly: 38px on one line here, 82px
                  // wrapped with a row-level sign-out.
                  // Nothing is fabricated by the swap: the fixture state's
                  // `lastSyncAt` is null, so `LastSynced` says "not synced
                  // yet", which is exactly true of a simulated account that
                  // reads no mail — and is a state the signed-in page renders
                  // too. One reachable state does undercut that, and is worth
                  // stating rather than defending: press Sync with the knob on
                  // and the run reports a real receipt ("2 filed, 3 already
                  // known"), then seconds later this slot reads "not synced
                  // yet" again, because `DEMO_GMAIL` is a static const and the
                  // simulated transport writes nothing back to it — true of a
                  // fixture account, false inside the fiction that receipt just
                  // told. The fix is a follow-up and not this branch's: hold
                  // the gmail state in `DemoDashboard`'s store and set
                  // `lastSyncAt` on a simulated sync.
                  // Only the knob reaches this branch; /demo and the
                  // twin's own default still carry the frame.
                  // One honesty badge per row (#212): where the trailing
                  // pill is on the row (`lg`+ — the slot is lg-only), this
                  // phrase is the SECOND element saying "these are fixtures"
                  // on one line, and its 184.5px is exactly the middle the
                  // bar-centred notification chip needs — measured, the
                  // centred plate overlapped this phrase by 63px at 1280 on
                  // the default twin. So the phrase yields to the pill at
                  // `lg`+ and carries the signage alone below it, where the
                  // pill is gone; session-edge.spec asserts both halves, so
                  // stripping either stays red. A surface that passed no
                  // `trailing` would keep the phrase at every width — none
                  // ships today: /demo mounts the shell twin (pill in the
                  // slot) since the consolidation.
                  <span
                    className={`order-last w-full text-xs text-dim sm:order-none sm:w-auto${
                      trailing ? " lg:hidden" : ""
                    }`}
                  >
                    simulated account · nothing is read
                  </span>
                ) : (
                  // A phrase, so the product voice — the machine-readable
                  // instant already rides in the <time> element's dateTime and
                  // title. Compact ("synced 3 minutes ago"): the Sync button
                  // beside it carries the noun, and on the shared command row
                  // every word here is width the ledger's news needs.
                  <LastSynced
                    at={gmail?.lastSyncAt ?? null}
                    compact
                    className="order-last w-full text-xs text-dim sm:order-none sm:w-auto"
                  />
                )
              ) : null}
              <button
                type="button"
                onClick={() => void runSync()}
                disabled={busy}
                aria-label="Sync new mail from Gmail"
                // The remembered duration rides HERE and nowhere else: the
                // tooltip costs the header row no width, and at 1024 this row
                // has none to give — spending ~97px of it is how sign-out
                // wrapped the row (#172). Absent until a run has been timed.
                title={`Checks Gmail for new mail and adds what it finds. Never removes anything.${
                  lastSync ? ` ${syncMemoryLine(lastSync)}` : ""
                }`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              >
                {/* The pressed control is the first place feedback lands
                    (#196/#160): while ITS run is in flight the icon spins in
                    place — same box, so the button never changes width — and
                    the counter line sits right beside it. A windowed run disables
                    this button but keeps the still icon: a spinner here would
                    claim a sync that is not running. */}
                {phase.kind === "syncing" ? (
                  <Loader2
                    className="h-4 w-4 animate-spin motion-reduce:animate-none"
                    aria-hidden
                  />
                ) : (
                  <RefreshCw className="h-4 w-4" aria-hidden />
                )}
                Sync
              </button>
            </>
          ) : gmail !== null ? (
            // S0 — known not-connected. An unknown status (failed probe)
            // renders nothing rather than a guessed state.
            <Link
              href="/settings"
              className="text-xs text-dim underline-offset-2 hover:text-strong hover:underline"
            >
              gmail not connected · connect in settings →
            </Link>
          ) : null}
          {/* The `⋯` menu — OUTSIDE the connected branch, because with
              `signedIn` it is the board route's only sign-out at `lg`+
              (TopBar yields there) and a session must stay endable with Gmail
              disconnected. The sync-owned items still require a connection: a
              menu must not offer a scan that can only 409. Sign-out is
              last and unhinted — the label is the whole action. The trigger's
              name follows its contents: the session edge makes it more than
              sync options, and the demo (no session) keeps the old name its
              specs assert. */}
          {connected || signedIn ? (
            <RowActionsMenu
              label={signedIn ? "More actions" : "Sync options"}
              disabled={busy}
              triggerClassName="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              triggerContent={<MoreHorizontal className="h-4 w-4" aria-hidden />}
              items={[
                ...(connected
                  ? [
                      {
                        // The hint names what the SCAN does that `Sync`
                        // cannot — re-read mail already filed — because that
                        // is the reason anyone comes here (a row judged by an
                        // older build, #474), and then names the default
                        // disposition so the destructive one is never a
                        // surprise waiting inside. "keeps rows it doesn't
                        // find" and not "removes nothing": an AUTO row whose
                        // last email turns out to be another employer's is
                        // still retired on this path, and the receipt still
                        // says so.
                        key: "scan-window",
                        label: "Scan a window of Gmail…",
                        hint: "re-reads mail already filed · keeps rows it doesn't find",
                        onSelect: openDialog,
                      },
                      {
                        key: "inbox",
                        label: "Open inbox workbench",
                        hint: "mine, inspect and file mail by hand",
                        onSelect: () => router.push("/inbox"),
                      },
                    ]
                  : []),
                ...(signedIn
                  ? [
                      {
                        key: "sign-out",
                        label: "Sign out",
                        // Real label, real width, real menu chrome — that
                        // geometry IS what `session-edge.spec.ts` measures, so
                        // the item may not be special-cased into a different
                        // shape on the fixture twin. What it may not do there
                        // is END A SESSION: `/demo/shell?session=1` mounts this
                        // edge over fixtures with no session behind it, and a
                        // `supabase.auth.signOut()` from an anonymous visitor
                        // can only bounce them to /login — the dead end
                        // `DemoFixturePill` exists to prevent. It leaves for
                        // the demo overview instead: the pill's own
                        // destination, so the control still does something
                        // true rather than silently nothing.
                        // `simulated` is the transport's own word for "these
                        // are fixtures" and already gates exactly this class of
                        // decision here (the staleness auto-sync never runs on
                        // it, and the recency slot says so out loud). The live
                        // dashboard passes the live transport, so the signed-in
                        // page is untouched by this branch.
                        onSelect: simulated ? () => router.push("/demo") : () => void signOut(),
                      },
                    ]
                  : []),
              ]}
            />
          ) : null}
          {children}
        </div>
        {/* The notification overlay (#212): the change ledger, centred on
            the BAR. At `lg`+ it is absolutely positioned over this row —
            `inset-0`, so its box IS the row's box at every wrap state, and
            the chip's `mx-auto` centre is the bar's centre exactly. Out of
            flow, it costs the worklist nothing: a dedicated line under the
            row read best but spent 26px of the fold's #172 refund, and
            session-edge.spec's floor (613px at 1024×768) caught it at 594 —
            that height is the worklist's, not this chip's to spend. The
            chip wears its compact form at `lg`+ (see its ladder), which is
            what keeps it clear of the totals on its left and the cluster on
            its right — measured clearances in that component's header.

            `pointer-events-none` because the overlay blankets the row; the
            plate and the opened panel opt back in individually, so the
            title, totals and every control stay clickable through it.
            `pt-2.5` drops the 18px chip line to the vertical centre of the
            row's one-line band ((38 − 18) / 2); on the fixture twin's
            wrapped 82px row that same offset pins it to LINE ONE, whose
            right side is free past the totals.

            Below `lg` the shell unlocks and there is no floor: the same
            node becomes an in-flow full-width line at the row's end
            (`order-last`), the stacked header's own notification bar, and
            the server pass reserves it there so hydration moves nothing.

            `relative` below `lg` / `absolute` at `lg`+ also makes this the
            names panel's containing block in BOTH schemes: `top-full` is
            the row's bottom at `lg`+ (below every control, wrapped or not —
            the #172 sheet-over-the-Sync-button failure cannot recur) and
            the chip line's bottom in the stack below `lg`.

            While the status line SPEAKS, the overlay yields the row
            (`lg:hidden`, #160): the plate is centred over the same middle a
            speaking status uses, and it sits ABOVE it — measured on this
            build (headless Chromium, `next start`, 2026-08-14), the centred
            plate covered 34px of the head of `checking since last sync ·
            0:00` at 1024 in the signed-in arrangement, and 109px/73px at
            1024/1280 on the pill-furnished twin, so the sync's one line of
            life read "…ng since last sync". placePlate cannot absorb that:
            it re-measures on resize only (a status appearing mid-run is
            invisible to it), and its slide is bounded by the totals-win
            rule (#196) long before 34px of clearance exists at 1024. One
            transient statement at a time is already this row's law — the
            recency phrase yields to the same statuses — and the ledger's
            news is durable: the chip returns the moment the note decays
            (~9s for a routine run). Below `lg` chip and status hold
            separate stacked lines, so both stay. */}
        {since ? (
          <div
            className={`relative max-lg:order-last max-lg:w-full lg:pointer-events-none lg:absolute lg:inset-0 lg:pt-2.5${
              statusTakesSlot ? " lg:hidden" : ""
            }`}
            /* `--chip-tight`: the overlay tells the chip when the row is
               FURNISHED — the trailing pill spends 167px of right flank the
               live board does not have, and with it on the row the window
               between the totals and the cluster measures 169px at 1024:
               smaller than any moment-bearing quiet plate (its short form
               is 179px before clearances), so no nudge can save it. The
               chip's `lg`→`xl` moment span reads this var and keeps the
               bare claim instead (see SinceLastLook). A CSS var rather
               than a Tailwind group-data variant because the base `hidden`
               and a stacked-variant `inline` on one span would leave the
               outcome to stylesheet order; `display: var(...)` inside the
               one media window is deterministic. Surfaces without the pill
               — the live dashboard, ?session=1, /demo — never set it. */
            style={trailing ? ({ "--chip-tight": "none" } as React.CSSProperties) : undefined}
          >
            {since}
          </div>
        ) : null}
        {trailing ? <div className="hidden shrink-0 items-center lg:flex">{trailing}</div> : null}
      </div>

      {/* The alert live region — persistent for the same announcement reason,
          its own line below the row when it speaks. A failure pushing the
          board down is deliberate: it is rare, it is red, and it must not be
          possible to miss. */}
      <p
        role="alert"
        className={`text-xs text-reject-ink ${alertContent === null ? "sr-only" : ""}`}
      >
        {alertContent}
      </p>

      {phase.kind === "receipt" ? (
        <div>
          <ScanReceipt
            op={phase.op}
            outcome={phase.outcome}
            transport={transport}
            onDismiss={() => setPhase({ kind: "idle" })}
            onRestored={restoreSucceeded}
            onContinue={() => {
              if (phase.op === "sync") {
                void runSync();
              } else if (lastWindowed.current) {
                const { depth: d, range: r, disposition: disp } = lastWindowed.current;
                void runScan(d, r, disp);
              }
            }}
          />
        </div>
      ) : null}

      {/* The windowed-scan dialog. Three questions in the order a person asks
          them — how far back, how deep, and what happens to what it misses —
          then the commit. The third is the one #474 added, and it is last on
          purpose: it sits directly above the confirm button whose verb it
          changes, so the choice and its consequence are read together. */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Scan a window of Gmail"
        description="Reads the window you choose again from scratch, including mail Applied has already filed — which is how a row it got wrong the first time gets a second look. Rows you filed or corrected by hand are left alone."
      >
        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <span className="label-caps">window</span>
            <Segmented<ScanRange>
              ariaLabel="Time window"
              options={SCAN_RANGE_OPTIONS}
              value={range}
              onChange={setRange}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="label-caps" htmlFor="scan-depth">
              depth
            </label>
            <select
              id="scan-depth"
              aria-label="Number of messages to scan"
              className={`${selectClass} w-40 py-1.5 text-xs`}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value) as ScanDepth)}
            >
              {SCAN_DEPTH_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {formatCount(n)} messages
                </option>
              ))}
            </select>
          </div>
          {/* Stated, not offered, on BOTH dispositions — but for two different
              reasons, and the sentence has to be true of each. The backend
              forces `scope="anywhere"` on a rebuild because a scan that can
              remove rows must see everything it judges (an inbox-scoped
              rebuild once deleted two applications whose ATS confirmations
              were archived); `scanRequestBody` asks for the same scope on the
              additive path because the mail that would correct a stale row is,
              by the time anyone notices, archived. Either way there is no
              honest control to put here. The leading clause is verbatim from
              the rebuild dialog — demo.spec matches on it. */}
          <p className="text-xs text-muted">
            scans all mail, including archive — a scan that re-judges filed rows has to be able
            to read them
          </p>
          {/* The disposition. Amber only on the destructive choice, and only
              on this one line: the label, the control and the confirm verb
              carry the rest, so the dialog stays quiet until the moment it
              stops being safe. */}
          <div className="flex flex-col gap-1.5 border-t border-line-soft pt-4">
            <span className="label-caps">rows it doesn&apos;t find</span>
            <Segmented<ScanDisposition>
              ariaLabel="What to do with applications this scan doesn't find"
              options={SCAN_DISPOSITION_OPTIONS}
              value={disposition}
              onChange={setDisposition}
            />
            <p
              className={`text-xs ${disposition === "remove" ? "text-review" : "text-muted"}`}
            >
              {scanDispositionNote(disposition)}
            </p>
          </div>
          {memoryLine ? <p className="text-xs text-dim">{memoryLine}</p> : null}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line-soft pt-4">
            <button
              type="button"
              onClick={() => setDialogOpen(false)}
              className="rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                setDialogOpen(false);
                void runScan(depth, range, disposition);
              }}
              className="rounded-lg bg-strong px-3 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
            >
              {scanConfirmLabel(range, disposition)}
            </button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

// --- The receipt --------------------------------------------------------------

/**
 * A run that removed rows must say WHICH, and every removal must be
 * reversible right here: each row is a dismissal the backend can restore
 * (`POST /applications/{id}/restore`), which is what makes the purge
 * auditable rather than final. Amber border when rows were removed or the
 * scan stopped early (needs attention; nothing failed), red when it broke,
 * quiet otherwise. The entrance is a fast fade-rise (0.18s) that pulls the
 * eye to the receipt without ever delaying reading it; reduced motion
 * renders it statically.
 *
 * The heading is the end state, not a pleasantry: a run that stopped early did
 * NOT finish, and one that removed rows on a partial scan judged those
 * removals against mail it never read — both are said outright, with continue
 * as the one action. `op` names the run in that heading, and it is the same
 * word the control that started it used — "rebuild finished" over a removal an
 * ordinary sync made would send the reader looking for a rebuild they never
 * ran, and over a keep-scan it would name them an action they declined.
 */
function ScanReceipt({
  op,
  outcome,
  transport,
  onDismiss,
  onRestored,
  onContinue,
}: {
  op: SyncOp;
  outcome: ScanOutcome;
  transport: SyncTransport;
  onDismiss: () => void;
  onRestored: (id: number) => void;
  /** Re-runs the same operation (a windowed run keeps its window, depth AND
   *  disposition — see `lastWindowed`). */
  onContinue: () => void;
}) {
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [failedId, setFailedId] = useState<number | null>(null);
  const reduceMotion = useReducedMotion();

  async function restore(id: number) {
    setRestoringId(id);
    setFailedId(null);
    try {
      if (!(await transport.restore(id))) {
        setFailedId(id);
        return;
      }
      onRestored(id);
    } catch {
      setFailedId(id);
    } finally {
      setRestoringId(null);
    }
  }

  const removedRows = outcome.removed;
  const endKind = stopKind(outcome.stoppedBy);
  const border =
    endKind === "broken"
      ? "border-reject/40"
      : endKind === "partial" || outcome.purged > 0 || outcome.dropped > 0
        ? "border-review/40"
        : "border-line-soft";
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className={`rounded-xl border bg-surface px-4 py-3 ${border}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          {endKind === "complete" ? (
            <p className="text-xs text-live">{`${op} finished · just now`}</p>
          ) : endKind === "partial" ? (
            <p className="text-xs text-review">{`${op} stopped early · just now`}</p>
          ) : (
            <p className="text-xs text-reject-ink">
              {op} interrupted · the scan {stopReasonPhrase(outcome.stoppedBy)}
            </p>
          )}
          <p className="mt-1 text-xs text-muted">{receiptBodyLine(outcome)}</p>
          {endKind === "partial" ? (
            <div className="mt-1 space-y-1">
              <p className="text-xs text-muted">
                the scan {stopReasonPhrase(outcome.stoppedBy)} ·{" "}
                {scanProgressLine(outcome.scanned, outcome.estimate)}
              </p>
              {outcome.purged > 0 ? (
                <p className="text-xs text-review">
                  removals were judged against this partial scan
                </p>
              ) : null}
              <button
                type="button"
                onClick={onContinue}
                className="rounded border border-review/50 px-2 py-0.5 text-xs font-medium text-strong transition-colors hover:border-review"
              >
                continue the scan
              </button>
            </div>
          ) : null}
          {endKind === "broken" && outcome.stoppedBy === "disconnected" ? (
            <p className="mt-1 text-xs text-muted">
              what it found so far is kept ·{" "}
              <Link
                href="/settings"
                className="underline-offset-2 hover:text-strong hover:underline"
              >
                reconnect in settings →
              </Link>
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss sync report"
          className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      {removedRows.length > 0 ? (
        <ul className="mt-2 space-y-1 border-t border-line-soft pt-2">
          {removedRows.map((row) => (
            <li key={row.id} className="flex items-center gap-3 py-0.5">
              <span className="min-w-0 truncate text-sm text-strong">{row.company}</span>
              <span className="text-xs text-dim">removed</span>
              {row.restored ? (
                <span className="ml-auto text-xs text-dim">restored</span>
              ) : (
                <span className="ml-auto flex items-center gap-2">
                  {failedId === row.id ? (
                    <span role="alert" className="text-xs text-reject-ink">
                      couldn&apos;t restore — still removed
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void restore(row.id)}
                    disabled={restoringId !== null}
                    aria-label={`Restore ${row.company}`}
                    className="text-xs font-medium text-muted underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
                  >
                    {restoringId === row.id ? "restoring…" : "restore"}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </motion.div>
  );
}
