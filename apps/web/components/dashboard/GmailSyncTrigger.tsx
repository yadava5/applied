"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * Auto-populates the dashboard from connected Gmail.
 *
 * Rendered only in the "connected but no applications yet" state. It fires one
 * bounded server-side sync (`POST /api/gmail/sync`, a full purge/rebuild) — but
 * at most ONCE per cooldown window per tab session, not on every dashboard
 * navigation. Each visit remounts this component, so a per-mount `useRef` guard
 * alone still re-scanned Gmail on every Inbox → Dashboard hop; the cooldown
 * stamp in `sessionStorage` is what makes repeat visits cheap. If a sync
 * persists applications it calls `router.refresh()` so the server dashboard
 * re-renders with the real board; if it finds no job mail it leaves the honest
 * empty state in place. The backend upsert is idempotent, so this never
 * duplicates rows.
 */

type State = "syncing" | "empty" | "error";

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

export function GmailSyncTrigger() {
  const router = useRouter();
  const ran = useRef(false);
  const [state, setState] = useState<State>("syncing");

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    let cancelled = false;
    (async () => {
      // Already auto-synced recently in this session → show the honest empty
      // state instead of re-scanning Gmail on this navigation.
      if (recentlyAutoSynced()) {
        if (!cancelled) setState("empty");
        return;
      }
      // Stamp before the request so a rapid re-navigation can't double-fire the
      // purge/rebuild while the first one is still in flight.
      markAutoSynced();
      try {
        const res = await fetch("/api/gmail/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
          cache: "no-store",
        });
        if (cancelled) return;
        if (!res.ok) {
          setState("error");
          return;
        }
        const data = (await res.json()) as { applications?: number };
        if (cancelled) return;
        if ((data.applications ?? 0) > 0) {
          router.refresh();
        } else {
          setState("empty");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <p className="flex items-center gap-2 font-mono text-[11px] text-dim" role="status">
      {state === "syncing" ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          scanning your connected Gmail for applications…
        </>
      ) : state === "empty" ? (
        <>No application emails detected in the last 12 months yet.</>
      ) : (
        <>Couldn&apos;t reach Gmail to sync — file one by hand, or try again shortly.</>
      )}
    </p>
  );
}
