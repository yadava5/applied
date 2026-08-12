"use client";

import { useEffect, useState } from "react";

import {
  NOT_SYNCED_YET,
  absoluteInstant,
  compactSyncLabel,
  relativeSyncLabel,
} from "@/lib/gmail/sync-state";

/**
 * "last synced 3 minutes ago" — the one place the sync instant is rendered.
 *
 * ONE format, everywhere: relative. This component used to server-render the
 * absolute UTC form and swap to relative after mount (hydration-safe, but the
 * live header was observed holding "last synced 2026-08-11 06:42 UTC" beside
 * a rail reading "34 minutes ago" — same fact, two formats, one screen). Now
 * nothing visible is rendered until the browser knows `now`: the server (and
 * the client's hydration pass) emit the bare <time> shell, and the first
 * effect fills in the relative label. That is hydration-safe by construction
 * — both sides render identical empty content — and makes a stuck absolute
 * form impossible, because the absolute string only ever appears in `title`
 * (hover) and `dateTime` (machines).
 *
 * The minute ticker matters more than it looks: this renders in the app
 * shell, and a long-open tab that still reads "just now" an hour later is the
 * same lie the product told before it had any sync memory at all.
 */
export function LastSynced({
  at,
  className,
  compact = false,
}: {
  at: string | null;
  className?: string;
  /** "synced 3 minutes ago" instead of the full sentence — for rows where a
   *  Sync control sits beside it and already names the operation. */
  compact?: boolean;
}) {
  /** `null` until mounted — the server has no honest `now` to compute from. */
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    const tick = () => setLabel((compact ? compactSyncLabel : relativeSyncLabel)(at, Date.now()));
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [at, compact]);

  if (!at) {
    return <span className={className}>{NOT_SYNCED_YET}</span>;
  }

  return (
    <time dateTime={at} title={absoluteInstant(at) ?? undefined} className={className}>
      {label}
    </time>
  );
}
