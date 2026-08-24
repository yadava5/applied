"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  BETA_CTA_LABEL,
  BETA_IMPORT_LABEL,
  BETA_MAILTO,
  BETA_SEATS,
  IMPORT_HREF,
} from "./constants";

/**
 * The slim, site-wide beta pill. Deliberately subtle: it surfaces
 * "Beta · limited access" without redesigning or dominating the landing or
 * demo, and expands into a compact details popover carrying the beta ask
 * (email the admin) plus the no-connection import path.
 *
 * The sample-inbox action is the ONE thing this popover carries that the rich
 * <BetaCard> deliberately does not (#495) — see the note in `constants.ts`.
 * It is allowed here precisely because `HIDE_ON` below keeps this pill off
 * every signed-in route, so the only visitors who see it are signed out. If a
 * signed-in route is ever removed from that list, this link leaves with it.
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

/**
 * Surfaces that already carry the full beta card, say "beta" in their own
 * copy, or are work surfaces a fixed pill would sit on top of. The pill is
 * `position: fixed`, so on a dense page it overlaps real content (it used to
 * cover board rows on /dashboard) — it now shows only on the narrative
 * surfaces (landing, /demo) that were designed around it.
 */
const HIDE_ON = [
  "/settings",
  "/inbox",
  "/demo",
  "/dashboard",
  "/import",
  // The landing candidates: a fixed app toast floating over a sales page's
  // hero board is app chrome leaking into marketing — access is the page's
  // own Access section there, not a pill's.
  //
  // `/` IS THAT LANDING NOW. Candidate B was promoted out of `/landing-b`
  // into `app/page.tsx`, and this list did not follow it, so the rule above
  // has been true of three routes nobody visits and false of the only one a
  // stranger loads. At 390px the cost is not theoretical: the pill is
  // `position: fixed inset-x-0 bottom-3`, so it spans the viewport and lands
  // on whatever is at the foot of the screen — hit-testing its centre on the
  // landing returned the board's own "Software Engineer, Simulation" row.
  //
  // Exact-match only, and the matcher below already guarantees that: `"/"`
  // hits the `pathname === p` arm, and its `startsWith("//")` arm cannot
  // match a real path. Add nothing shorter — a bare prefix here would hide
  // the pill everywhere.
  "/",
  "/landing-a",
  "/landing-b",
  "/landing-c",
];

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
  if (HIDE_ON.some((p) => pathname === p || pathname.startsWith(`${p}/`)))
    return null;

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
            aria-label="Applied beta access"
            data-beta="banner-panel"
            className="beta-panel absolute bottom-full left-1/2 mb-2 w-[min(20rem,calc(100vw-1.5rem))] -translate-x-1/2 rounded-xl border border-line-soft bg-surface p-4 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.8)]"
          >
            <p className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-viz-rules">
              <span className="beta-dot" aria-hidden />
              Beta · limited access
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              Applied is under active development. Direct Gmail connection is
              limited to{" "}
              <span className="text-strong">{BETA_SEATS} beta testers</span> —
              Google&apos;s OAuth test-user cap — while we gather feedback.
            </p>
            <div className="mt-3 flex flex-col gap-2">
              <a
                href={BETA_MAILTO}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-strong px-3 py-2 text-sm font-medium text-background outline-none transition-transform hover:-translate-y-px focus-accent"
              >
                <span aria-hidden>✉</span>
                {BETA_CTA_LABEL}
              </a>
              {/* THE SECOND ACTION IS /import, NOT THE SAMPLE INBOX, and the
                  swap is the point rather than a copy tweak. This pill is
                  `position: fixed` ROOT-layout chrome: it renders on every
                  route its `HIDE_ON` list does not name, and that list names
                  routes, not sessions. It does not cover `/privacy` — which a
                  signed-in user reaches from a standing link on the protected
                  Inbox page and from the Gmail card in Settings, and which
                  wears the full app shell when they do — and it cannot cover
                  `not-found`, where any mistyped URL lands. So the argument
                  that once justified keeping a `/demo/inbox` link here ("the
                  only people who see this pill are strangers") was false on
                  two surfaces, and `constants.ts` said in as many words that
                  the link had to leave the moment that stopped holding.

                  `/import` is the honest replacement rather than nothing: it
                  is the same offer minus the fiction — the real classifier
                  over the reader's OWN mail, in their browser, with no
                  connection and no account — and it is what `BetaCard`, this
                  pill's in-app sibling, has always linked to. The two
                  surfaces now carry the same two actions, so there is no
                  divergence left to justify or to re-litigate. The demo still
                  exists and is still linked, from the landing page and the
                  `/demo` routes, where a stranger meets it and a user does
                  not. */}
              <Link
                href={IMPORT_HREF}
                onClick={() => setOpen(false)}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-foreground outline-none transition-colors hover:border-line-strong hover:text-strong focus-accent"
              >
                {BETA_IMPORT_LABEL}
                <span aria-hidden>→</span>
              </Link>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-dim">
              No connection and no account for the import path — your mail is
              read in this browser and never uploaded.
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
            className="flex items-center gap-2 rounded-full py-0.5 pr-1 text-xs focus-accent"
          >
            <span className="beta-dot" aria-hidden />
            <span className="font-mono font-semibold uppercase tracking-widest text-strong">
              Beta
            </span>
            <span className="hidden text-muted sm:inline">
              · limited access
            </span>
            <span className="font-mono text-dim" aria-hidden>
              {open ? "▾" : "▸"}
            </span>
          </button>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss beta notice"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-dim outline-none transition-colors hover:bg-surface-2 hover:text-strong focus-accent"
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
