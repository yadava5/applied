"use client";

import { Loader2, MoreHorizontal, RefreshCw, X } from "lucide-react";
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
  rebuildConfirmLabel,
  rebuildMemoryLine,
  rebuildRequestBody,
  rebuildScopeLine,
  receiptBodyLine,
  type RebuildDepth,
  type RebuildOutcome,
  type RebuildRange,
} from "@/lib/gmail/sync-plan";
import { filedSummary, isStale, type SyncCounts } from "@/lib/gmail/sync-state";

/**
 * The one sync surface. Everything the dashboard says about Gmail flows
 * through this component: the header (title, subtitle, recency, the `Sync`
 * button, the `⋯` overflow), the persistent status/alert line, the rebuild
 * dialog, and the rebuild receipt.
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
 *     Never removes anything.
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
  | { kind: "synced"; note: string }
  | { kind: "rebuilding"; startedAt: number; scopeLine: string }
  | { kind: "receipt"; outcome: RebuildOutcome }
  | { kind: "failed"; op: "sync" | "rebuild"; notConnected: boolean };

/** Cooldown so the staleness auto-sync runs at most once per window per tab. */
const AUTOSYNC_KEY = "applied:dashboard:autosync:lastAt";
const AUTOSYNC_COOLDOWN_MS = 10 * 60 * 1000; // 10 minutes

/** The additive clock only appears once a sync stops feeling instant. */
const SLOW_SYNC_AFTER_MS = 8000;

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
  children,
  transport = liveSyncTransport,
}: {
  /** The page's one honest line of state — `214 filed · 32 in motion · 1 offer`. */
  subtitle: string;
  gmail: SyncGmailState | null;
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
  const lastRebuild = useRef<{ depth: RebuildDepth; range: RebuildRange } | null>(null);

  const connected = gmail?.connected === true;
  const hasCursor = gmail?.hasCursor === true;
  const lastSyncAt = gmail?.lastSyncAt ?? null;
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
      setPhase({ kind: "failed", op: "sync", notConnected: res.status === 409 });
      return;
    }
    const data = res.body as Partial<SyncCounts>;
    // Cursored zero case: the scan only looked at what arrived since the
    // last one, so "nothing to file · N scanned" would imply a claim about a
    // window it never checked.
    const nothingFiled = (data.created ?? 0) <= 0 && (data.updated ?? 0) <= 0;
    const note =
      nothingFiled && hasCursor
        ? "no new application mail since your last sync"
        : filedSummary(data);
    setPhase({ kind: "synced", note });
    router.refresh();
  }, [hasCursor, router, transport]);

  const runRebuild = useCallback(
    async (d: RebuildDepth, r: RebuildRange) => {
      lastRebuild.current = { depth: d, range: r };
      const startedAt = Date.now();
      setPhase({ kind: "rebuilding", startedAt, scopeLine: rebuildScopeLine(d, r) });
      const res = await transport.sync(rebuildRequestBody(d, r));
      if (!res.ok) {
        setPhase({ kind: "failed", op: "rebuild", notConnected: res.status === 409 });
        return;
      }
      const outcome = readRebuildOutcome(res.body);
      writeRebuildMemory(memoryKey, Date.now() - startedAt, outcome.scanned);
      setPhase({ kind: "receipt", outcome });
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
        kind: "receipt",
        outcome: {
          ...p.outcome,
          removed: p.outcome.removed.map((row) => (row.id === id ? { ...row, restored: true } : row)),
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
            <span className="tabular" aria-hidden>
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
        <span className="tabular" aria-hidden>
          · {formatElapsed(nowMs - phase.startedAt)}
        </span>
      </>
    );
  } else if (phase.kind === "synced") {
    statusContent = <>{phase.note}</>;
  } else if (phase.kind === "idle" && connected && gmail?.syncStatus === "error") {
    // Resting after a failed run: the backend keeps `last_sync_at` at the last
    // good sync, so recency and this line are two facts, both shown.
    statusContent = (
      <span className="text-reject">
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

  if (phase.kind === "failed") {
    alertContent = phase.notConnected ? (
      <>
        Gmail is not connected · nothing was changed{" "}
        <Link href="/settings" className="text-muted underline-offset-2 hover:text-strong hover:underline">
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

  return (
    // `data-sync-surface` scopes assertions (e.g. "no percentage anywhere in
    // the sync UI") to this surface without leaning on copy or classes.
    <div className="space-y-2" data-sync-surface="">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Pipeline</h1>
          <p className="mt-1 font-mono text-xs text-dim">{subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {connected ? (
            <>
              {showRecency ? (
                simulated ? (
                  <span className="font-mono text-[11px] text-dim">
                    simulated account · nothing is read
                  </span>
                ) : (
                  <LastSynced at={gmail?.lastSyncAt ?? null} className="font-mono text-[11px] text-dim" />
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
              className="font-mono text-[11px] text-dim underline-offset-2 hover:text-strong hover:underline"
            >
              gmail not connected · connect in settings →
            </Link>
          ) : null}
          {children}
        </div>
      </header>

      {/* Persistent live regions — visually empty when idle. */}
      <p
        role="status"
        aria-live="polite"
        className={`flex items-center gap-2 font-mono text-[11px] text-muted ${
          statusContent === null ? "sr-only" : ""
        }`}
      >
        {statusContent}
      </p>
      <p
        role="alert"
        className={`font-mono text-[11px] text-reject ${alertContent === null ? "sr-only" : ""}`}
      >
        {alertContent}
      </p>

      {phase.kind === "receipt" ? (
        <RebuildReceipt
          outcome={phase.outcome}
          transport={transport}
          onDismiss={() => setPhase({ kind: "idle" })}
          onRestored={restoreSucceeded}
        />
      ) : null}

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Rebuild from Gmail"
        description="A rebuild scans the window you choose and replaces every application that was filed from Gmail with what it finds. Rows you filed or corrected by hand are kept. Anything removed is listed afterward and can be restored."
      >
        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <span className="label-mono">window</span>
            <Segmented<RebuildRange>
              ariaLabel="Time window"
              options={REBUILD_RANGE_OPTIONS}
              value={range}
              onChange={setRange}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="label-mono" htmlFor="rebuild-depth">
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
          <p className="font-mono text-[11px] text-muted">
            scans all mail, including archive — a rebuild must see everything it judges
          </p>
          {memoryLine ? <p className="font-mono text-[11px] text-dim">{memoryLine}</p> : null}
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
 * A rebuild that removed rows must say WHICH, and every removal must be
 * reversible right here: each row is a dismissal the backend can restore
 * (`POST /applications/{id}/restore`), which is what makes the purge
 * auditable rather than final. Amber border when rows were removed (needs
 * attention; nothing failed), quiet otherwise. No entrance animation — this
 * panel's job is to be read.
 */
function RebuildReceipt({
  outcome,
  transport,
  onDismiss,
  onRestored,
}: {
  outcome: RebuildOutcome;
  transport: SyncTransport;
  onDismiss: () => void;
  onRestored: (id: number) => void;
}) {
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [failedId, setFailedId] = useState<number | null>(null);

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
  return (
    <div
      className={`rounded-xl border bg-surface px-4 py-3 ${
        outcome.purged > 0 ? "border-review/40" : "border-line-soft"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] text-live">rebuild finished · just now</p>
          <p className="mt-1 font-mono text-[11px] text-muted">{receiptBodyLine(outcome)}</p>
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
              <span className="font-mono text-[11px] text-dim">removed</span>
              {row.restored ? (
                <span className="ml-auto font-mono text-[11px] text-dim">restored</span>
              ) : (
                <span className="ml-auto flex items-center gap-2">
                  {failedId === row.id ? (
                    <span role="alert" className="font-mono text-[11px] text-reject">
                      couldn&apos;t restore — still removed
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void restore(row.id)}
                    disabled={restoringId !== null}
                    aria-label={`Restore ${row.company}`}
                    className="font-mono text-[11px] text-muted underline-offset-2 hover:text-strong hover:underline disabled:opacity-50"
                  >
                    {restoringId === row.id ? "restoring…" : "restore"}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
