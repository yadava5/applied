"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  BETA_CTA_LABEL,
  BETA_MAILTO,
  BETA_SAMPLE_LABEL,
  BETA_SEATS,
  SAMPLE_INBOX_HREF,
} from "./constants";

/**
 * The slim, site-wide beta pill. Deliberately subtle: it surfaces
 * "Beta · limited access" without redesigning or dominating the landing or
 * demo, and expands into a compact details popover carrying the same two
 * actions as the rich <BetaCard> (email the admin, try the sample inbox).
 *
 * - Dismissible, and the dismissal persists in localStorage.
 * - Hidden on the surfaces that already show the full card (/settings,
 *   /inbox) and on the deep interactive sample inbox (/demo/inbox).
 * - Fixed-position, so it never shifts page layout; renders nothing until
 *   mounted so there is no hydration flash and no server/client mismatch.
 * - Popover closes on Escape / outside click; the toggle exposes
 *   aria-expanded/aria-controls and the panel is a labelled region.
 *
 * All motion (the pulsing dot, the drifting accent border, the popover
 * entrance) is CSS and collapses to static under prefers-reduced-motion.
 */

const DISMISS_KEY = "jobtracker:beta-banner-dismissed:v1";

/** Surfaces that already carry the full beta card, or are too interaction-dense for a pill. */
const HIDE_ON = ["/settings", "/inbox", "/demo/inbox"];

export function BetaBanner() {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Defer off the effect body (never a synchronous setState there) so the
    // null → pill swap happens after hydration — no server/client mismatch,
    // and, since the banner is fixed-position, no layout shift. A macrotask
    // (not rAF) so it still fires when the tab is loaded in the background.
    const id = window.setTimeout(() => {
      let alreadyDismissed = false;
      try {
        alreadyDismissed = window.localStorage.getItem(DISMISS_KEY) === "1";
      } catch {
        /* storage blocked (private mode) — just show the pill */
      }
      setDismissed(alreadyDismissed);
      setMounted(true);
    }, 0);
    return () => window.clearTimeout(id);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  function dismiss() {
    setOpen(false);
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* non-fatal — the banner is hidden for this session regardless */
    }
  }

  if (!mounted || dismissed) return null;
  if (HIDE_ON.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return null;

  return (
    <div
      ref={rootRef}
      className="pointer-events-none fixed inset-x-0 bottom-3 z-40 flex justify-center px-3 sm:bottom-4"
    >
      <div className="pointer-events-auto relative">
        {open ? (
          <div
            id="beta-banner-panel"
            role="region"
            aria-label="JobTracker beta access"
            data-beta="banner-panel"
            className="beta-panel absolute bottom-full left-1/2 mb-2 w-[min(20rem,calc(100vw-1.5rem))] -translate-x-1/2 rounded-xl border border-line-soft bg-surface p-4 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.8)]"
          >
            <p className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-viz-rules">
              <span className="beta-dot" aria-hidden />
              Beta · limited access
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              JobTracker is under active development. Direct Gmail connection is limited to{" "}
              <span className="text-strong">{BETA_SEATS} beta testers</span>{" "}— Google&apos;s OAuth
              test-user cap — while we gather feedback.
            </p>
            <div className="mt-3 flex flex-col gap-2">
              <a
                href={BETA_MAILTO}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-strong px-3 py-2 text-sm font-medium text-background outline-none transition-transform hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-viz-rules"
              >
                <span aria-hidden>✉</span>
                {BETA_CTA_LABEL}
              </a>
              <Link
                href={SAMPLE_INBOX_HREF}
                onClick={() => setOpen(false)}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground outline-none transition-colors hover:border-line-strong hover:text-strong focus-visible:ring-2 focus-visible:ring-viz-rules"
              >
                {BETA_SAMPLE_LABEL}
                <span aria-hidden>→</span>
              </Link>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-dim">
              No connection needed for the sample inbox — real classifier, synthetic mail.
            </p>
          </div>
        ) : null}

        <div className="beta-pill flex items-center gap-1 rounded-full border border-line-soft bg-surface/90 py-1 pl-3 pr-1 backdrop-blur">
          <button
            type="button"
            aria-label="Beta — limited access"
            aria-expanded={open}
            aria-controls="beta-banner-panel"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 rounded-full py-0.5 pr-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
          >
            <span className="beta-dot" aria-hidden />
            <span className="font-mono font-semibold uppercase tracking-widest text-strong">Beta</span>
            <span className="hidden text-muted sm:inline">· limited access</span>
            <span className="font-mono text-dim" aria-hidden>
              {open ? "▾" : "▸"}
            </span>
          </button>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss beta notice"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-dim outline-none transition-colors hover:bg-surface-2 hover:text-strong focus-visible:ring-2 focus-visible:ring-viz-rules"
          >
            <span aria-hidden className="text-sm leading-none">
              ×
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
