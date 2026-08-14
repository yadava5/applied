"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { SaveStatus, SettingsSection } from "./SettingsSection";
import { Toggle } from "./Toggle";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

export interface NotificationPrefs {
  weekly: boolean;
  reviewAlerts: boolean;
}

type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * Notification preferences. The choices persist to the Supabase user's metadata
 * immediately (so they survive reloads) AND drive real in-app behaviour on the
 * dashboard: `reviewAlerts` decides whether the Needs-review queue interrupts
 * the board (above it) or waits under it, and `weekly` folds the this-week
 * count into the header line (both wired in the dashboard page). Email delivery isn't
 * wired on this deployment yet — the caption says so plainly rather than
 * implying a toggle sends mail it can't.
 */
export function NotificationsSection({
  initial,
  mode = "live",
}: {
  initial: NotificationPrefs;
  mode?: SettingsMode;
}) {
  const [prefs, setPrefs] = useState<NotificationPrefs>(initial);
  const [state, setState] = useState<SaveState>("idle");
  const transport = settingsTransport(mode);
  const router = useRouter();

  async function persist(next: NotificationPrefs) {
    setPrefs(next);
    setState("saving");
    const { ok } = await transport.saveMetadata({ notifications: next });
    setState(ok ? "saved" : "error");
    /**
     * THE OTHER HALF OF #216, and the reason the toggle read as dead.
     *
     * `next.config.ts` caches every route's RSC payload in the client router
     * for 300 s (`experimental.staleTimes.dynamic`, #211 — a measured win
     * against 700–1150 ms of origin time per navigation, which is why the
     * answer here is to invalidate on the mutation rather than to opt
     * `/dashboard` out). The dashboard is almost always ALREADY in that cache
     * when a user comes here: the sidebar `Link` prefetches it. So the write
     * below landed in Supabase, the user clicked Dashboard, and the cached
     * payload rendered the OLD placement — self-correcting only once the
     * window closes, five minutes later since the window went to 300 s, which
     * is worse than a hard failure, because the control reads as broken
     * exactly while it is being tested and works once you have given up.
     *
     * `router.refresh()` bumps Next's GLOBAL segment-cache version, so this
     * discards every cached route entry, not just the dashboard's — the next
     * navigation to /inbox or /import re-pays its origin time too. That is
     * the right trade and it is deliberate: saves are rare and user-initiated,
     * navigations are constant, and a preference that does not appear where it
     * was promised is a correctness bug rather than a slow one.
     *
     * Only on `ok`: a failed save has nothing to publish, and refreshing would
     * re-render the surfaces against metadata that never changed.
     */
    if (ok) router.refresh();
  }

  return (
    <SettingsSection id="notifications" title="Notifications">
      <div className="divide-y divide-line-soft">
        <Toggle
          checked={prefs.weekly}
          onChange={(v) => persist({ ...prefs, weekly: v })}
          label="Weekly summary"
          description="Adds this week's filings to your dashboard's header line."
        />
        <Toggle
          checked={prefs.reviewAlerts}
          onChange={(v) => persist({ ...prefs, reviewAlerts: v })}
          label="Needs-review alerts"
          description="On, held mail interrupts the board above your rows. Off, it waits below them."
        />
      </div>
      {/* The toggles' own lines say exactly what each does; the only feedback
          left to carry is the save state (#200 cut the footer caption).
          `min-h-4` reserves the status line's height so "Saved" arriving —
          and clearing itself (#213) — never re-flows the card. */}
      <div className="mt-2 flex min-h-4 justify-end">
        <SaveStatus state={state} />
      </div>
    </SettingsSection>
  );
}
