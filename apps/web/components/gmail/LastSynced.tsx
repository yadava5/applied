"use client";

import { useEffect, useState } from "react";

import {
  NOT_SYNCED_YET,
  absoluteInstant,
  absoluteSyncLabel,
  relativeSyncLabel,
} from "@/lib/gmail/sync-state";

/**
 * "last synced 3 minutes ago" — the one place the sync instant is rendered.
 *
 * Hydration-safe by construction. Relative time is a function of `now`, and the
 * server's `now` is minutes stale by the time the browser hydrates, so
 * computing it during SSR (or in a `useState` initializer, which runs during
 * hydration) mismatches the server HTML — the class of mistake that produced
 * React #418 in production here.
 *
 * So the first render — server AND client — is the ABSOLUTE instant, which is a
 * pure function of the ISO string's characters and therefore identical in both.
 * Only after `useEffect` (which never runs on the server, and runs after
 * hydration has already committed) does the label become relative. The absolute
 * form stays reachable on hover via `title`, and the machine-readable instant
 * stays in `dateTime`.
 *
 * The minute ticker matters more than it looks: this chip lives in the app
 * shell, and a long-open tab that still reads "just now" an hour later is the
 * same lie the product told before it had any sync memory at all.
 */
export function LastSynced({ at, className }: { at: string | null; className?: string }) {
  const [label, setLabel] = useState(() => absoluteSyncLabel(at));

  useEffect(() => {
    const tick = () => setLabel(relativeSyncLabel(at, Date.now()));
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [at]);

  if (!at) {
    return <span className={className}>{NOT_SYNCED_YET}</span>;
  }

  return (
    <time dateTime={at} title={absoluteInstant(at) ?? undefined} className={className}>
      {label}
    </time>
  );
}
