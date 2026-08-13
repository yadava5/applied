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
import { onRebuildRequest, requestRebuild } from "@/lib/dashboard/rebuild-bus";
import { liveSyncTransport, type SyncTransport } from "@/lib/dashboard/transport";
import {
  REBUILD_DEFAULT_DEPTH,
  REBUILD_DEFAULT_RANGE,
  REBUILD_DEPTH_OPTIONS,
  REBUILD_MEMORY_DEMO_KEY,
  REBUILD_MEMORY_KEY,
  REBUILD_RANGE_OPTIONS,
  SYNC_MEMORY_DEMO_KEY,
  SYNC_MEMORY_KEY,
  formatCount,
  formatElapsed,
  parseRebuildMemory,
  readRebuildOutcome,
  readScanEnd,
  rebuildConfirmLabel,
  rebuildMemoryLine,
  rebuildRequestBody,
  rebuildScopeLine,
  receiptBodyLine,
  scanProgressLine,
  stopKind,
  stopReasonPhrase,
  syncMemoryLine,
  syncReceiptNote,
  syncScopeLine,
  type RebuildDepth,
  type RebuildOutcome,
  type RebuildRange,
  type ScanEnd,
} from "@/lib/gmail/sync-plan";
import { filedSummary, isStale, type SyncCounts } from "@/lib/gmail/sync-state";

/**
 * The one sync surface. Everything the dashboard says about Gmail flows
 * through this component: the header cluster (subtitle, the change-ledger
 * chip, recency, the `Sync` button, the `⋯` overflow), the persistent
 * status/alert line, the rebuild dialog, and the rebuild receipt.
 *
 * Its header is the page's TOP LINE: one ~40px row carrying the route title
 * (`title` — the page's one <h1>, at every width; at `lg`+ the shell's
 * TopBar yields to this row entirely, see TopBar), the
 * subtitle, the change-ledger chip (`since`), the status/recency slot, the
 * controls, and the session edge. Sign-out therefore stays reachable from
 * the top line of the screen on the board route — inside the `⋯` menu
 * (`withSignOut`), not as a row-level button: the button was the ~97px that
 * wrapped this row to 82px at 1024 and cost the worklist the difference
 * (#172), spent on the control the owner uses least. The status
 * line never moves the page at `lg`+ — it rides in the row for exactly as
 * long as it speaks (the owner watched the board jump when "checking Gmail…"
 * used to take a line of its own), and while a sync RUNS it takes the change
 * ledger's width rather than the board's own totals: blanking
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
 * The word "Re-sync" is retired. Two named actions remain:
 *   - **Sync** — additive. Checks Gmail for new mail and adds what it finds.
 *     It removes nothing for being absent from the scan — but ONE shape of row
 *     can still leave the board (an application whose last email turned out to
 *     be a different company's), so when the backend names removals a sync gets
 *     the same receipt a rebuild does, with the same per-row restore. A board
 *     that changed silently is what let 22 removals go unnoticed for two days.
 *   - **Rebuild** — destructive, behind a dialog that states its window and
 *     lists every removed row afterward with per-row restore.
 *
 * There is deliberately NO progress percentage anywhere here: the server sync
 * is one request that returns once, so any fraction would be fabricated. What
 * runs instead is honest — the scope stated up front, a count-up clock
 * (elapsed time is the one number the browser truly knows), and the measured
 * duration of the last rebuild remembered for the next dialog.
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

type SyncPhase =
  | { kind: "idle" }
  | { kind: "syncing"; startedAt: number }
  /** Additive finished — `end` says HOW. A partial end never renders as done. */
  | { kind: "synced"; note: string; end: ScanEnd }
  | { kind: "rebuilding"; startedAt: number; scopeLine: string }
  /** A run that changed the board enough to owe a receipt. `op` is which run
   *  wrote it: a rebuild always gets one, a sync only when it removed rows. */
  | { kind: "receipt"; op: "sync" | "rebuild"; outcome: RebuildOutcome }
  /** Additive scan broke mid-flight (disconnected / unexpected mode). */
  | { kind: "interrupted"; end: ScanEnd }
  | { kind: "failed"; op: "sync" | "rebuild"; notConnected: boolean };

/** Cooldown so the staleness auto-sync runs at most once per window per tab. */
const AUTOSYNC_KEY = "applied:dashboard:autosync:lastAt";
const AUTOSYNC_COOLDOWN_MS = 10 * 60 * 1000; // 10 minutes

/** When a running sync stops feeling instant and starts saying so. The clock
 *  beside the sentence runs from the first tick, not from here: a line that
 *  did not move for the whole 3.2s a sync takes is the other half of what was
 *  reported as frozen (#160), and elapsed is the one number the browser truly
 *  knows. This constant only changes the WORDING. */
const SLOW_SYNC_AFTER_MS = 8000;

/** How long a finished sync's resting note holds the status slot before the
 *  row goes quiet again. Long enough to read one short sentence, short enough
 *  that the change ledger is never gone for long — the board's own totals now
 *  stay put right through the run (#160), so this dwell no longer costs them. */
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

function readRebuildMemoryFromStorage(key: string) {
  try {
    return parseRebuildMemory(window.localStorage.getItem(key));
  } catch {
    return null;
  }
}

function writeRebuildMemory(key: string, ms: number, scanned: number): void {
  try {
    window.localStorage.setItem(key, JSON.stringify({ ms, scanned, at: Date.now() }));
  } catch {
    // Memory is a nicety; the dialog simply shows nothing next time.
  }
}

/**
 * "Choose a window" — the empty state's route into the rebuild dialog. Raises
 * the rebuild-bus signal answered by the mounted SyncBar; if no SyncBar is
 * listening (it always is on the connected dashboard, but a control must never
 * silently do nothing) it falls back to the inbox workbench, which has its own
 * window controls.
 */
export function RebuildWindowButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => {
        if (!requestRebuild()) router.push("/inbox");
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
  withSignOut = false,
  children,
  transport = liveSyncTransport,
}: {
  /** The page's one honest line of state — `214 filed · 32 open · 1 offer`. */
  subtitle: string;
  gmail: SyncGmailState | null;
  /** The change-ledger chip (`SinceLastLook`) — one line by that component's
   *  own contract, mounted right after the subtitle so state and news read as
   *  one sentence. A slot rather than an import: the ledger's rows/scope are
   *  the caller's business, and the error/empty pages pass nothing. */
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
   *  `withSignOut` instead. `lg`+ only. */
  trailing?: ReactNode;
  /** Folds `Sign out` into the row's `⋯` menu — the signed-in page's session
   *  edge. Menu chrome, not a row-level control (see `trailing`), and it also
   *  makes the menu render when Gmail is NOT connected: at `lg`+ the shell's
   *  TopBar yields on the board route, so this menu is the route's only
   *  sign-out. The fixture twin passes nothing — no session, no item. */
  withSignOut?: boolean;
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
  const [range, setRange] = useState<RebuildRange>(REBUILD_DEFAULT_RANGE);
  const [depth, setDepth] = useState<RebuildDepth>(REBUILD_DEFAULT_DEPTH);
  const [memoryLine, setMemoryLine] = useState<string | null>(null);
  /** `Your last sync took 3 s.` — the Sync button's tooltip tail once a run
   *  has been timed. Held in state rather than read during render because
   *  localStorage does not exist on the server pass. */
  const [syncMemory, setSyncMemory] = useState<string | null>(null);
  /** Ticks while a sync/rebuild runs so the elapsed clock stays honest. */
  const [nowMs, setNowMs] = useState(() => Date.now());
  const autoRan = useRef(false);
  const lastRebuild = useRef<{
    depth: RebuildDepth;
    range: RebuildRange;
  } | null>(null);

  const connected = gmail?.connected === true;
  const hasCursor = gmail?.hasCursor === true;
  const lastSyncAt = gmail?.lastSyncAt ?? null;
  const reduceMotion = useReducedMotion();
  const simulated = transport.mode === "simulated";
  const memoryKey = simulated ? REBUILD_MEMORY_DEMO_KEY : REBUILD_MEMORY_KEY;
  const syncMemoryKey = simulated ? SYNC_MEMORY_DEMO_KEY : SYNC_MEMORY_KEY;
  const busy = phase.kind === "syncing" || phase.kind === "rebuilding";

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
    writeRebuildMemory(syncMemoryKey, elapsedMs, end.scanned);
    setSyncMemory(syncMemoryLine({ ms: elapsedMs, scanned: end.scanned, at: Date.now() }));
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
    const outcome = readRebuildOutcome(res.body);
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

  const runRebuild = useCallback(
    async (d: RebuildDepth, r: RebuildRange) => {
      lastRebuild.current = { depth: d, range: r };
      const startedAt = Date.now();
      setPhase({
        kind: "rebuilding",
        startedAt,
        scopeLine: rebuildScopeLine(d, r),
      });
      const res = await transport.sync(rebuildRequestBody(d, r));
      if (!res.ok) {
        setPhase({
          kind: "failed",
          op: "rebuild",
          notConnected: res.status === 409,
        });
        return;
      }
      const outcome = readRebuildOutcome(res.body);
      writeRebuildMemory(memoryKey, Date.now() - startedAt, outcome.scanned);
      setPhase({ kind: "receipt", op: "rebuild", outcome });
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
  useEffect(() => onRebuildRequest(() => setDialogOpen(true)), []);

  // The remembered duration of the last sync, read once per mount. Nothing
  // shows until a run has actually been timed — an unmeasured "usually quick"
  // is the kind of claim this surface does not make.
  useEffect(() => {
    // Deferred off the effect body (house rule — no synchronous setState in
    // an effect), which also keeps the read off the server pass entirely.
    const id = window.setTimeout(() => {
      const memory = readRebuildMemoryFromStorage(syncMemoryKey);
      setSyncMemory(memory ? syncMemoryLine(memory) : null);
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
  // at `lg`+ that note takes the subtitle + ledger slot (see the header-row
  // note below), and `synced` had no exit but the receipt dialog — which a
  // plain sync never opens. So one press hid the board's totals and the
  // change ledger for the rest of the session, on the signed-in dashboard as
  // well as the demo. A partial scan is excluded on purpose: it carries a
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
      const memory = readRebuildMemoryFromStorage(memoryKey);
      return memory ? rebuildMemoryLine(memory) : null;
    });
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
        <Loader2 className="h-3 w-3 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
        {/* Beside the totals at `lg`+ this line cannot wrap, so it has to say
            what gives first: the SENTENCE does, with an ellipsis. Measured at
            1024 on the signed-in board, where the row's spare width runs out
            mid-clock. */}
        {/* What the run COVERS, not just that one is happening. `hasCursor`
            is server truth and picks the backend's path, so this is the one
            honest thing about the scan that is knowable before it returns —
            measured: a cursored sync comes back `scanned: 0` with no
            estimate, so there is nothing to count while it runs and any
            advancing number would be invented. See `syncScopeLine`. */}
        <span className="lg:min-w-0 lg:truncate">
          {elapsed >= SLOW_SYNC_AFTER_MS ? "still checking" : syncScopeLine(hasCursor)}
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
  } else if (phase.kind === "rebuilding") {
    statusContent = (
      <>
        <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
        rebuilding · {phase.scopeLine}
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
        {/* Both sentences are true because the backend applies a rebuild
            transactionally or not at all; if that ever stops being true this
            copy must change with it. */}
        {phase.op === "rebuild"
          ? "rebuild failed · nothing was changed. Your board is exactly as it was."
          : "sync failed · Gmail did not answer. Your board is unchanged."}{" "}
        <button
          type="button"
          onClick={() => {
            if (phase.op === "rebuild" && lastRebuild.current) {
              void runRebuild(lastRebuild.current.depth, lastRebuild.current.range);
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
  // The change-ledger chip always yields: it is news, and the status is now.
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
  // slot, which is the safe side of the wrap. `rebuilding` is deliberately
  // not in it — its line restates window, depth and scope, and is the widest
  // status this row has.
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
          on the board route, so the title, the state, the change ledger, the
          sync controls and the session edge share one ~40px row instead of a
          48px bar with an empty middle plus a second row under it.

          ZERO LAYOUT SHIFT is a requirement of this row (the owner watched
          the whole page jump when "checking Gmail…" appeared): at `lg`+ the
          status line does not get a line of its own — it takes the change
          ledger's width for exactly as long as it has something to say, so
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
      {/* `relative`: the change ledger's names panel anchors to THIS row
          (its own chip sits mid-row, where an anchored overlay ran past
          <main>'s left edge and got clipped). */}
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2">
        {title ? (
          <h1 className="shrink-0 text-sm font-semibold tracking-tight text-strong">{title}</h1>
        ) : null}
        <p
          className={`tabular shrink-0 text-[13px] text-muted ${statusOwnsSlot ? "lg:hidden" : ""}`}
        >
          {subtitle}
        </p>
        {/* The ledger chip takes the slack between state and controls — its
            own fixed flex-basis, so hydration can never re-wrap the row (the
            board below must not move when the ledger finds its words). */}
        {since ? (
          <div className={`min-w-0 flex-1 basis-40 ${statusTakesSlot ? "lg:hidden" : ""}`}>
            {since}
          </div>
        ) : null}
        {/* The status live region — persistent (mounting live regions on
            demand drops announcements), sr-only while silent. When it speaks
            it takes the subtitle's slot at `lg`+ (see the row note above) and
            its own wrap-line below `lg`. The inner span is keyed by the
            machine's state so each transition slides its sentence in — the
            state CHANGE is visible, not just the state. */}
        <p
          role="status"
          aria-live="polite"
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
            className={`flex flex-wrap items-center gap-2 ${
              statusRidesAlongTotals ? "lg:flex-nowrap lg:whitespace-nowrap" : ""
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
        <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto sm:justify-end">
          {connected ? (
            <>
              {showRecency ? (
                simulated ? (
                  <span className="order-last w-full text-xs text-dim sm:order-none sm:w-auto">
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
                  syncMemory ? ` ${syncMemory}` : ""
                }`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className="h-4 w-4" aria-hidden />
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
              `withSignOut` it is the board route's only sign-out at `lg`+
              (TopBar yields there) and a session must stay endable with Gmail
              disconnected. The sync-owned items still require a connection: a
              menu must not offer a rebuild that can only 409. Sign-out is
              last and unhinted — the label is the whole action. The trigger's
              name follows its contents: the session edge makes it more than
              sync options, and the demo (no session) keeps the old name its
              specs assert. */}
          {connected || withSignOut ? (
            <RowActionsMenu
              label={withSignOut ? "More actions" : "Sync options"}
              disabled={busy}
              triggerClassName="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              triggerContent={<MoreHorizontal className="h-4 w-4" aria-hidden />}
              items={[
                ...(connected
                  ? [
                      {
                        key: "rebuild",
                        label: "Rebuild from Gmail…",
                        hint: "replaces Gmail-filed rows · lists every removal",
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
                ...(withSignOut
                  ? [{ key: "sign-out", label: "Sign out", onSelect: () => void signOut() }]
                  : []),
              ]}
            />
          ) : null}
          {children}
        </div>
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
          <RebuildReceipt
            op={phase.op}
            outcome={phase.outcome}
            transport={transport}
            onDismiss={() => setPhase({ kind: "idle" })}
            onRestored={restoreSucceeded}
            onContinue={() => {
              if (phase.op === "sync") {
                void runSync();
              } else if (lastRebuild.current) {
                void runRebuild(lastRebuild.current.depth, lastRebuild.current.range);
              }
            }}
          />
        </div>
      ) : null}

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Rebuild from Gmail"
        description="A rebuild scans the window you choose and replaces every application that was filed from Gmail with what it finds. Rows you filed or corrected by hand are kept. Anything removed is listed afterward and can be restored."
      >
        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <span className="label-caps">window</span>
            <Segmented<RebuildRange>
              ariaLabel="Time window"
              options={REBUILD_RANGE_OPTIONS}
              value={range}
              onChange={setRange}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="label-caps" htmlFor="rebuild-depth">
              depth
            </label>
            <select
              id="rebuild-depth"
              aria-label="Number of messages to scan"
              className={`${selectClass} w-40 py-1.5 text-xs`}
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value) as RebuildDepth)}
            >
              {REBUILD_DEPTH_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {formatCount(n)} messages
                </option>
              ))}
            </select>
          </div>
          {/* The backend forces `scope="anywhere"` on every rebuild — a scan
              that can remove rows must see everything it judges (an
              inbox-scoped rebuild once deleted two applications whose ATS
              confirmations were archived). So this is stated, not offered. */}
          <p className="text-xs text-muted">
            scans all mail, including archive — a rebuild must see everything it judges
          </p>
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
                void runRebuild(depth, range);
              }}
              className="rounded-lg bg-strong px-3 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
            >
              {rebuildConfirmLabel(range)}
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
 * as the one action. `op` names the run in that heading, because "rebuild
 * finished" over a removal an ordinary sync made would send the reader looking
 * for a rebuild they never ran.
 */
function RebuildReceipt({
  op,
  outcome,
  transport,
  onDismiss,
  onRestored,
  onContinue,
}: {
  op: "sync" | "rebuild";
  outcome: RebuildOutcome;
  transport: SyncTransport;
  onDismiss: () => void;
  onRestored: (id: number) => void;
  /** Re-runs the same operation (a rebuild keeps its window and depth). */
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
      : endKind === "partial" || outcome.purged > 0
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
