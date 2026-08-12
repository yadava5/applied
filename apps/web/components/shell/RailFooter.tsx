import Link from "next/link";

import { LastSynced } from "@/components/gmail/LastSynced";
import type { RailGmailData } from "@/lib/shell/rail";

/**
 * The sidebar's anchored footer: the Gmail connection chip and, at the very
 * bottom, the user chip.
 *
 * Connection chip — three honest states:
 *   - connected     → live emerald dot (`.beta-dot` ping), the account email,
 *                     when the board was last built. Links to the dashboard,
 *                     where sync now lives.
 *   - not connected → a quiet chip that links to Settings, where connecting
 *                     actually lives.
 *   - unknown       → chip omitted entirely (a failed status probe is not a
 *                     disconnection; never show a guessed state).
 *
 * The re-sync icon button is GONE — it was the fourth sync trigger, an
 * unlabelled icon that did something different from the identically-iconed
 * header button. The rail keeps what a rail is for: glanceable truth. Sync is
 * one click away (chip → dashboard → `Sync`), and this component is now a
 * server component — no fetch, no state, just what it was handed.
 *
 * "Last synced" lives here because the connection state already does, and it
 * is the answer to the question that drove the repeated manual re-syncs:
 * *did this thing ever run?* Whether the last sync SUCCEEDED and when are two
 * different facts: the backend leaves `last_sync_at` at the last good run when
 * one fails, so both render rather than one overwriting the other.
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
  if (!gmail.connected) {
    return (
      <Link
        href="/settings"
        className="group flex items-center gap-2.5 rounded-lg border border-line-soft px-2.5 py-2 transition-colors hover:border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
      >
        <span aria-hidden="true" className="h-[0.45rem] w-[0.45rem] shrink-0 rounded-full bg-line-strong" />
        <span className="min-w-0">
          <span className="label-caps block">gmail · not connected</span>
          <span className="block truncate text-xs text-muted transition-colors group-hover:text-strong">
            connect in settings <span aria-hidden="true">→</span>
          </span>
        </span>
      </Link>
    );
  }

  return (
    <Link
      href="/dashboard"
      aria-label="Gmail connected — open dashboard"
      className="group flex items-center gap-2.5 rounded-lg border border-line-soft px-2.5 py-2 transition-colors hover:border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
    >
      <span className="beta-dot" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="label-caps block">gmail · connected</span>
        {gmail.email ? (
          <span title={gmail.email} className="block truncate text-xs text-muted">
            {gmail.email}
          </span>
        ) : null}
        <LastSynced at={gmail.lastSyncAt} className="block truncate font-mono text-[10px] text-dim" />
        {gmail.syncStatus === "error" ? (
          <span className="block truncate text-[11px] text-reject-ink">
            last sync failed{gmail.syncError ? ` · ${gmail.syncError}` : ""}
          </span>
        ) : null}
      </span>
    </Link>
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
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line bg-surface-2 text-sm font-semibold text-strong"
        >
          {initial}
        </span>
        <span className="min-w-0">
          <span
            title={userEmail ?? undefined}
            className="block truncate text-xs text-muted transition-colors group-hover:text-strong"
          >
            {userEmail ?? "account"}
          </span>
          <span className="label-caps block">signed in</span>
        </span>
      </Link>
    </div>
  );
}
