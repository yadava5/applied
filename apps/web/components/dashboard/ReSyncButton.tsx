"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Manual "Re-sync from Gmail" control for the POPULATED dashboard.
 *
 * The empty-state auto-runs one sync (GmailSyncTrigger), but a user who already
 * has rows — including the owner's stale garbage rows — had NO way to trigger
 * the purge/rebuild. This button POSTs the same `/api/gmail/sync` (which REPLACES
 * the Gmail-derived pipeline: stale auto rows out, real rows + review queue
 * rebuilt, manual/user-set rows preserved) and `router.refresh()`es the server
 * board on success. Idempotent, so pressing it twice is harmless.
 */
export function ReSyncButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function resync() {
    setBusy(true);
    setNote(null);
    try {
      const res = await fetch("/api/gmail/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        cache: "no-store",
      });
      if (!res.ok) {
        setNote(res.status === 409 ? "Gmail not connected" : "Re-sync failed — try again shortly");
        setBusy(false);
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { purged?: number };
      setNote(data.purged && data.purged > 0 ? `cleared ${data.purged} stale` : "up to date");
      router.refresh();
      setBusy(false);
    } catch {
      setNote("Re-sync failed — try again shortly");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={resync}
        disabled={busy}
        title="Re-scan Gmail and rebuild the pipeline (removes stale rows, keeps your edits)"
        className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="h-4 w-4" aria-hidden />
        )}
        {busy ? "Re-syncing…" : "Re-sync"}
      </button>
      {note ? (
        <span role="status" className="font-mono text-[10px] text-dim">
          {note}
        </span>
      ) : null}
    </div>
  );
}
