"use client";

import { Loader2, MoreHorizontal, RefreshCw, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { RowActionsMenu } from "@/components/dashboard/RowActionsMenu";
import { LastSynced } from "@/components/gmail/LastSynced";
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
 * controls, and the session edge (`trailing`). Sign-out therefore stays on
 * the top line of the screen, in this row, on the board route. The status
 * line never moves the page at `lg`+ — it swaps into the subtitle's own slot
 * for exactly as long as it speaks (the owner watched the board jump when
 * "checking Gmail…" used to take a line of its own). The alert and the
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

/** The additive clock only appears once a sync stops feeling instant. */
const SLOW_SYNC_AFTER_MS = 8000;

/** How long a finished sync's resting note keeps the status slot before the
 *  row goes back to the board's own totals. Long enough to read one short
 *  sentence, short enough that the totals are never gone for long. */
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
  /** The session-edge control for the same case — SignOutButton on the
   *  signed-in page, the demo pill on the fixture twin. `lg`+ only. */
  trailing?: ReactNode;
  /** The compact `+` (AddApplicationForm) — stays rightmost in the cluster. */
  children?: ReactNode;
  /** How sync requests reach data — Gmail via the proxy by default; the demo
   *  passes a simulated transport so this same state machine runs on fixtures. */
  transport?: SyncTransport;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<SyncPhase>({ kind: "idle" });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [range, setRange] = useState<RebuildRange>(REBUILD_DEFAULT_RANGE);
  const [depth, setDepth] = useState<RebuildDepth>(REBUILD_DEFAULT_DEPTH);
  const [memoryLine, setMemoryLine] = useState<string | null>(null);
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
  const busy = phase.kind === "syncing" || phase.kind === "rebuilding";

  const runSync = useCallback(async () => {
    setPhase({ kind: "syncing", startedAt: Date.now() });
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
    const note =
      nothingFiled && hasCursor && stopKind(end.stoppedBy) === "complete"
        ? "no new application mail since your last sync"
        : filedSummary(data);
    setPhase({ kind: "synced", note, end });
    router.refresh();
  }, [hasCursor, router, transport]);

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
        <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
        {elapsed >= SLOW_SYNC_AFTER_MS ? (
          <>
            still checking
            <span className="tabular font-mono text-[11px]" aria-hidden>
              {" "}
              · {formatElapsed(elapsed)}
            </span>
          </>
        ) : (
          <>checking Gmail for new mail…</>
        )}
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
        <>{phase.note}</>
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

  // Whether the status borrows the subtitle + ledger slot at `lg`+. Kept as
  // "the status is speaking at all", deliberately: narrowing it (so a partial
  // scan or a resting failure keeps its own line instead) un-hides the
  // subtitle and the ledger in states where a long status ALSO sits on the
  // row, and the header wrapping to two lines costs the worklist ~30px
  // against a 7px floor margin. No test exercises those states, so that
  // change cannot be made safely without a fixture for them first — task #96.
  const statusTakesSlot = statusContent !== null;

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
          status line does not get a line of its own — it takes over the
          subtitle + ledger slot for exactly as long as it has something to
          say, so idle → checking → result → idle never changes the row's
          height. "As long as it has something to say" is enforced by the
          decay above, not merely intended: a note that never expired held
          this slot for the rest of the session.
          Two statuses still have no end of their own and so still hold it —
          the stopped-early scan (it carries a "continue the scan" control)
          and the resting "last sync failed". Both wait on the user, and both
          therefore keep the totals hidden while they wait; see task #96,
          which owes them a fixture before that can be changed. Below `lg` the
          row stacks and the status keeps its own line, as before. */}
      {/* `relative`: the change ledger's names panel anchors to THIS row
          (its own chip sits mid-row, where an anchored overlay ran past
          <main>'s left edge and got clipped). */}
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2">
        {title ? (
          <h1 className="shrink-0 text-sm font-semibold tracking-tight text-strong">{title}</h1>
        ) : null}
        <p
          className={`tabular shrink-0 text-[13px] text-muted ${statusTakesSlot ? "lg:hidden" : ""}`}
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
              : "min-w-0 text-xs text-muted max-lg:order-last max-lg:basis-full lg:flex-1"
          }
        >
          <motion.span
            key={phase.kind}
            initial={reduceMotion ? false : { opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="flex flex-wrap items-center gap-2"
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
                title="Checks Gmail for new mail and adds what it finds. Never removes anything."
                className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className="h-4 w-4" aria-hidden />
                Sync
              </button>
              <RowActionsMenu
                label="Sync options"
                disabled={busy}
                triggerClassName="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
                triggerContent={<MoreHorizontal className="h-4 w-4" aria-hidden />}
                items={[
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
                ]}
              />
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
