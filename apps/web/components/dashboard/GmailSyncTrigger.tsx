"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * Auto-populates the dashboard from connected Gmail.
 *
 * Rendered only in the "connected but no applications yet" state, it fires one
 * bounded server-side sync (`POST /api/gmail/sync`) on mount. If it persists
 * any applications it calls `router.refresh()` so the server dashboard
 * re-renders with the real board; if it finds no job mail it leaves the honest
 * empty state in place. Runs once per mount (guarded), and the backend upsert
 * is idempotent, so this can never loop or duplicate rows.
 */

type State = "syncing" | "empty" | "error";

export function GmailSyncTrigger() {
  const router = useRouter();
  const ran = useRef(false);
  const [state, setState] = useState<State>("syncing");

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    let cancelled = false;
    (async () => {
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
