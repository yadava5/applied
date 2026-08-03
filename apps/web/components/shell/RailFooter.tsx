"use client";

import { Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { RailGmailData } from "@/lib/shell/rail";

/**
 * The sidebar's anchored footer: the Gmail connection chip and, at the very
 * bottom, the user chip.
 *
 * Connection chip — three honest states:
 *   - connected     → live emerald dot (`.beta-dot` ping), the account email,
 *                     and a compact re-sync control.
 *   - not connected → a quiet chip that links to Settings, where connecting
 *                     actually lives.
 *   - unknown       → chip omitted entirely (a failed status probe is not a
 *                     disconnection; never show a guessed state).
 *
 * Re-sync here is the ADDITIVE path (`POST /api/gmail/sync` with `{}`) — new
 * mail folds in, existing rows are upserted, nothing is purged. The
 * destructive purge-and-rebuild stays exclusive to the dashboard's
 * `ReSyncButton`, which explains itself before running. On success we
 * `router.refresh()` so the server-rendered rail + board pick up the new rows.
 *
 * User chip — identity lives bottom-left (the Linear/Notion convention): a
 * monogram tile plus the truncated email, linking to Settings. Sign-out stays
 * in the top bar.
 */

type FooterProps = {
  gmail: RailGmailData | null;
  userEmail: string | null;
};

function GmailChip({ gmail }: { gmail: RailGmailData }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function resync() {
    setBusy(true);
    setNote(null);
    try {
      // Additive sync only — never the destructive rebuild (dashboard-only).
      const res = await fetch("/api/gmail/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        cache: "no-store",
      });
      if (!res.ok) {
        setNote(res.status === 409 ? "not connected" : "sync failed");
        setBusy(false);
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { created?: number };
      setNote(data.created && data.created > 0 ? `+${data.created} filed` : "up to date");
      router.refresh();
      setBusy(false);
    } catch {
      setNote("sync failed");
      setBusy(false);
    }
  }

  if (!gmail.connected) {
    return (
      <Link
        href="/settings"
        className="group flex items-center gap-2.5 rounded-lg border border-line-soft px-2.5 py-2 transition-colors hover:border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
      >
        <span aria-hidden="true" className="h-[0.45rem] w-[0.45rem] shrink-0 rounded-full bg-line-strong" />
        <span className="min-w-0">
          <span className="label-mono block">gmail · not connected</span>
          <span className="block truncate font-mono text-[11px] text-muted transition-colors group-hover:text-strong">
            connect in settings <span aria-hidden="true">→</span>
          </span>
        </span>
      </Link>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2.5 rounded-lg border border-line-soft px-2.5 py-2">
        <span className="beta-dot" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="label-mono">gmail · connected</p>
          {gmail.email ? (
            <p title={gmail.email} className="truncate font-mono text-[11px] text-muted">
              {gmail.email}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={resync}
          disabled={busy}
          aria-label="Re-sync Gmail"
          title="Scan new mail into the pipeline (additive — never removes rows)"
          className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </div>
      {note ? (
        <p role="status" className="mt-1 px-2.5 font-mono text-[10px] text-dim">
          {note}
        </p>
      ) : null}
    </div>
  );
}

export function RailFooter({ gmail, userEmail }: FooterProps) {
  const initial = userEmail?.charAt(0).toUpperCase() ?? "·";

  return (
    <div className="space-y-2">
      {gmail ? <GmailChip gmail={gmail} /> : null}
      <Link
        href="/settings"
        aria-label="Account — open settings"
        className="group flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
      >
        <span
          aria-hidden="true"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line bg-surface-2 font-mono text-sm text-strong"
        >
          {initial}
        </span>
        <span className="min-w-0">
          <span
            title={userEmail ?? undefined}
            className="block truncate font-mono text-[11px] text-muted transition-colors group-hover:text-strong"
          >
            {userEmail ?? "account"}
          </span>
          <span className="label-mono block">signed in</span>
        </span>
      </Link>
    </div>
  );
}
