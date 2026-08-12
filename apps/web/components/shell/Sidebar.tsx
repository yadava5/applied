"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import type { RailData } from "@/lib/shell/rail";
import { isNavItemActive, navItems } from "./nav";
import { RailFooter } from "./RailFooter";

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
 * This rail carries NO pipeline numbers, by measurement rather than taste.
 * PR #122 stacked an instrument column here (snapshot + the pulse's four
 * derived signals) and the result was 744px of column in a middle pane that
 * gets 537–717px at 1280×720…1440×900 — the app's own chrome scrolled
 * internally on every common laptop (202px over at the owner's real
 * 1309×693, with the Dashboard nav item pushed out of view), which read as
 * "the dashboard still scrolls". And even the slim snapshot that survived a
 * first fix stated a total the same screen already stated twice (the page
 * subtitle, the spine's "all" row — the task #59 restatement family). The
 * pulse is dashboard content, so it lives with the board — its full-width
 * band above the spine + worklist row (`PipelineBoard`'s `pulse` prop) — and
 * the chrome stays constant on every tab and can never scroll again: four
 * nav items cannot outgrow any viewport this app supports.
 *
 * The item matching the current route keeps its clear active treatment — a
 * cyan accent bar, a lit icon, a raised surface, and `aria-current="page"`.
 * Micro-interactions: icons nudge right on hover (motion-safe only) and every
 * interactive element carries a visible cyan focus ring for keyboard users.
 *
 * `rail` is assembled server-side by `lib/shell/rail` (type-only import here,
 * erased at compile time) — this component just renders what it is handed.
 */

type SidebarProps = {
  rail: RailData;
  userEmail: string | null;
};

export function Sidebar({ rail, userEmail }: SidebarProps) {
  const pathname = usePathname();

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
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
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
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>

      <div className="shrink-0 border-t border-line-soft px-3 py-3">
        <RailFooter gmail={rail.gmail} userEmail={userEmail} />
      </div>
    </aside>
  );
}
