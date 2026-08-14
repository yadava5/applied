"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import { isNavItemActive, navItems } from "./nav";
import { NavLink } from "./NavLink";
import { RailFooter } from "./RailFooter";
import { useShellSlots } from "./shell-slots";

/**
 * Desktop primary navigation (hidden below `md`; the mobile menu in `TopBar`
 * takes over there).
 *
 * Top to bottom: the Applied lockup, the four nav items, then — anchored to
 * the viewport bottom via the sticky full-height column — one identity block:
 * who is signed in, with the Gmail connection state as a subordinate line
 * beneath it (`RailFooter`, which explains why those two chips became one).
 * The rail is `sticky top-0 h-dvh`, so it stays in view while long pages
 * scroll and the footer genuinely anchors; the middle section keeps
 * `overflow-y-auto` purely as a safety valve for pathologically short
 * windows.
 *
 * This rail carries NO pipeline data of its own, by measurement rather than
 * taste. PR #122 stacked an instrument column here (snapshot + the pulse's
 * four derived signals) and the result was 744px of column in a middle pane
 * that gets 537–717px at 1280×720…1440×900 — the app's own chrome scrolled
 * internally on every common laptop (202px over at the owner's real
 * 1309×693, with the Dashboard nav item pushed out of view), which read as
 * "the dashboard still scrolls". And even the slim snapshot that survived a
 * first fix stated a total the same screen already stated twice (the page
 * subtitle, the spine's "all" row — the task #59 restatement family). The
 * pulse is dashboard content, so it lives with the board — its full-width
 * band above the worklist (`PipelineBoard`'s `pulse` prop).
 *
 * What the middle run DOES hold on the board route is the board's own stage
 * lens + search, portaled in by `PipelineBoard` (see the slot below): those
 * are FILTERS — navigation within the route, which is what a nav rail is for
 * — their counts are the lens's own badges, and the whole block measures
 * ~300px against the ≥537px the middle run always has, so the #122 overflow
 * cannot recur. Derived data (bars, ages, deadlines) stays banned here.
 *
 * The item matching the current route keeps its clear active treatment — a
 * cyan accent bar, a lit icon, a raised surface, and `aria-current="page"`.
 * Micro-interactions: icons nudge right on hover (motion-safe only) and every
 * interactive element carries a visible cyan focus ring for keyboard users.
 *
 * The footer's connection line arrives already rendered (`connection`), not as
 * data: it is the one thing here that needs a backend answer, so it streams in
 * behind its own Suspense boundary — which has to live on the SERVER side of
 * this client component. This component just renders what it is handed.
 */

type SidebarProps = {
  /**
   * The footer's Gmail connection line, already rendered. A SLOT, not data:
   * this is a Client Component, and the line's Suspense boundary lives on the
   * server side of that line so the probe can stream in without the page's own
   * render waiting for it (see `AppShell`). A resolved element passes through
   * here untouched.
   */
  connection: ReactNode;
  userEmail: string | null;
  /** Display name for the identity block; `null` falls back to the email. */
  userName?: string | null;
};

export function Sidebar({ connection, userEmail, userName = null }: SidebarProps) {
  const pathname = usePathname();
  const { setRail } = useShellSlots();

  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line-soft bg-surface md:flex">
      <div className="px-4 py-4">
        <Link
          href="/dashboard"
          aria-label="Applied — go to your applications"
          className="brand-logo-link rounded-md text-strong focus-accent"
        >
          <Logo className="h-7 w-auto" />
        </Link>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pb-4">
        <nav className="px-2" aria-label="Primary">
          <ul className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = isNavItemActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <NavLink
                    href={item.href}
                    active={active}
                    className={cn(
                      "group relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-accent",
                      active
                        ? "bg-surface-2 text-strong"
                        : "text-muted hover:bg-surface-2 hover:text-strong",
                    )}
                  >
                    {active ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-viz-rules"
                      />
                    ) : null}
                    <Icon
                      className={cn(
                        "h-4 w-4 transition-transform motion-safe:group-hover:translate-x-0.5",
                        active && "text-viz-rules",
                      )}
                      aria-hidden="true"
                    />
                    {item.label}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* The rail's middle run — the void PR #122 once overfilled with data.
            It is a SLOT now: the board portals its stage lens + search here
            (`PipelineBoard`, via shell-slots), so what fills it is the
            board's own filter state with one owner, and the rail itself still
            carries no pipeline numbers of its own. Empty on every route that
            mounts nothing into it. */}
        <div ref={setRail} className="mt-5 border-t border-line-soft px-2 pt-4 empty:hidden" />
      </div>

      <div className="shrink-0 border-t border-line-soft px-3 py-3">
        <RailFooter connection={connection} userName={userName} userEmail={userEmail} />
      </div>
    </aside>
  );
}
