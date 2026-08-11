"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { filedSummary, isStale, type SyncCounts } from "@/lib/gmail/sync-state";

/**
 * Keeps the dashboard current with connected Gmail, without the user asking.
 *
 * The rule used to be `total === 0`: this only ever rendered on an EMPTY board,
 * so an account with rows never auto-synced and new mail never appeared until
 * the user pressed Re-sync — which re-scanned a 12-month window from scratch.
 * That is the "I have to re-sync again and again, and again when a new email
 * arrives" complaint. The rule is now STALENESS: if the backend's
 * `last_sync_at` is older than `STALE_AFTER_MS` (30 minutes), one additive
 * sync runs on this visit. Never synced counts as stale, so the connect-time
 * backfill still happens.
 *
 * Two gates keep that cheap:
 *   - the staleness check itself, against server truth (`last_sync_at`), so a
 *     board another tab just synced is not synced again;
 *   - the existing per-tab `sessionStorage` cooldown, which covers the window
 *     between "we synced" and "a server render reflects it" — a fast navigator
 *     cannot fire twice inside it.
 *
 * The sync is `mode: "additive"` and carries NO `count`/`range`: either of those
 * makes the backend treat the call as an explicit window request and disable
 * incremental sync (`_history_cursor_for`), which would restore the full rescan
 * this work exists to remove. The destructive purge/rebuild stays exclusive to
 * the user's own Re-sync button.
 *
 * What this does NOT do: it will not surface mail while the page sits open.
 * "New mail appears on my next visit (or within 30 minutes of navigating)" is
 * the property implemented here; push/polling was not in scope.
 */

type Phase = "idle" | "syncing" | "done" | "empty" | "error";

/**
 * `empty` — the connected-but-nothing-filed board, where this component is the
 * page's only explanation of what is happening. `quiet` — a populated board,
 * where it must be invisible unless it has something to report.
 */
type Variant = "empty" | "quiet";

/** Cooldown so the auto-sync runs at most once per window per tab session. */
const AUTOSYNC_KEY = "applied:dashboard:autosync:lastAt";
const AUTOSYNC_COOLDOWN_MS = 10 * 60 * 1000; // 10 minutes

function recentlyAutoSynced(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = window.sessionStorage.getItem(AUTOSYNC_KEY);
    return raw != null && Date.now() - Number(raw) < AUTOSYNC_COOLDOWN_MS;
  } catch {
    return false;
  }
}

function markAutoSynced(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(AUTOSYNC_KEY, String(Date.now()));
  } catch {
    // sessionStorage unavailable — degrade to the per-mount guard only.
  }
}

export function GmailSyncTrigger({
  lastSyncAt,
  hasCursor = false,
  variant = "empty",
}: {
  /** Backend `last_sync_at` — an instant with an explicit UTC offset, or null. */
  lastSyncAt: string | null;
  /** True when the last scan was cursored, i.e. the next one is incremental. */
  hasCursor?: boolean;
  variant?: Variant;
}) {
  const router = useRouter();
  const ran = useRef(false);
  const [phase, setPhase] = useState<Phase>(variant === "empty" ? "syncing" : "idle");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    // `router.refresh()` below re-renders this component with a FRESH
    // `lastSyncAt`, which re-runs this effect. The ref is what stops that from
    // being a loop — one attempt per mount, whatever the props do afterwards.
    if (ran.current) return;
    ran.current = true;

    let cancelled = false;
    (async () => {
      // Fresh enough, or already tried in this tab recently → say nothing new.
      if (!isStale(lastSyncAt, Date.now()) || recentlyAutoSynced()) {
        if (!cancelled) setPhase(variant === "empty" ? "empty" : "idle");
        return;
      }
      // Stamp before the request so a rapid re-navigation cannot double-fire
      // while the first one is still in flight.
      markAutoSynced();
      if (!cancelled) setPhase("syncing");
      try {
        const res = await fetch("/api/gmail/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // Additive (durable): a routine sync must never purge rows a bounded
          // scan missed. NO count/range — they disable the incremental path.
          body: JSON.stringify({ mode: "additive" }),
          cache: "no-store",
        });
        if (cancelled) return;
        if (!res.ok) {
          setPhase("error");
          return;
        }
        const data = (await res.json().catch(() => ({}))) as Partial<SyncCounts>;
        if (cancelled) return;
        setNote(filedSummary(data));
        setPhase((data.applications ?? 0) > 0 ? "done" : "empty");
        // Refresh even when nothing was filed: the server render is what carries
        // the new `last_sync_at` into the rail, and leaving it stale is exactly
        // the "did this ever run?" doubt that caused the manual re-syncs.
        router.refresh();
      } catch {
        if (!cancelled) setPhase("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, lastSyncAt, variant]);

  const line = "flex items-center gap-2 font-mono text-[11px] text-dim";

  if (variant === "quiet") {
    // A populated board says nothing unless there is something to say.
    if (phase === "idle" || phase === "empty") return null;
    return (
      <p className={line} role="status">
        {phase === "syncing" ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            checking Gmail for new mail…
          </>
        ) : phase === "error" ? (
          <>Couldn&apos;t reach Gmail just now — your board is unchanged.</>
        ) : (
          <>{note ?? "up to date"}</>
        )}
      </p>
    );
  }

  return (
    <p className={line} role="status">
      {phase === "syncing" ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          scanning your connected Gmail for applications…
        </>
      ) : phase === "error" ? (
        <>Couldn&apos;t reach Gmail to sync — file one by hand, or try again shortly.</>
      ) : phase === "done" ? (
        // Transient: the refresh this triggered re-renders the board as
        // populated and unmounts us. Until it lands, report the real outcome
        // rather than the "nothing found" copy below, which is now false.
        <>{note ?? "filed from Gmail"}</>
      ) : hasCursor ? (
        // A cursored scan only looked at what arrived since the last one, so
        // "nothing in the last 12 months" would be a claim it never checked.
        <>No new application emails since your last sync.</>
      ) : (
        // The uncursored server scan really is bounded to 12 months
        // (`_SYNC_DEFAULT_RANGE_MONTHS`).
        <>No application emails detected in the last 12 months yet.</>
      )}
    </p>
  );
}
