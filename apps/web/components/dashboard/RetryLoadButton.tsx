"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

/**
 * "Try again" for the dashboard's failed-load state.
 *
 * The load failed on the SERVER (the backend rejected the session or never
 * answered), so the only honest retry is to re-run the server render:
 * `router.refresh()` re-requests the route and re-renders its Server
 * Components. Wrapped in a transition so the button can report that the retry
 * is in flight instead of looking inert; if the backend is still down the page
 * simply re-renders this same state, which is the truthful outcome.
 */
export function RetryLoadButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [tried, setTried] = useState(false);

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        disabled={pending}
        onClick={() => {
          setTried(true);
          startTransition(() => {
            router.refresh();
          });
        }}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong disabled:cursor-not-allowed disabled:opacity-50"
      >
        {pending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="h-4 w-4" aria-hidden />
        )}
        {pending ? "Retrying…" : "Try again"}
      </button>
      {tried && !pending ? (
        <span role="status" className="font-mono text-[10px] text-dim">
          still failing — the backend hasn&apos;t recovered yet
        </span>
      ) : null}
    </div>
  );
}
