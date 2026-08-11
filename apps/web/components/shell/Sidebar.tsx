"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import type { RailData } from "@/lib/shell/rail";
import { isNavItemActive, navItems } from "./nav";
import { RailFooter } from "./RailFooter";
import { RailPipeline } from "./RailPipeline";

/**
 * Desktop primary navigation, redesigned as a full-height data rail (hidden
 * below `md`; the mobile menu in `TopBar` takes over there).
 *
 * Top to bottom: the Applied lockup, the four nav items, a live pipeline
 * snapshot (`RailPipeline` — total, stage distribution, needs-review nudge),
 * then — anchored to the viewport bottom via the sticky full-height column —
 * the Gmail connection chip and the user chip (`RailFooter`). The rail is
 * `sticky top-0 h-dvh`, so it stays in view while long pages scroll and the
 * footer genuinely anchors; the middle section scrolls internally on short
 * viewports so the footer is never pushed out of reach.
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
          aria-label="Applied — go to dashboard"
          className="brand-logo-link rounded-md text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules"
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
                      "group relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules",
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

        {/* The pipeline snapshot is for the pages that DON'T show the
            pipeline (inbox, settings, import) — glanceable truth plus the
            needs-review deep link. On /dashboard the real board is on screen,
            and a miniature of it beside itself is the count-duplication this
            redesign removed from the page; so here, it yields. */}
        {isNavItemActive(pathname, "/dashboard") ? null : (
          <div className="mt-5 px-3">
            <RailPipeline pipeline={rail.pipeline} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line-soft px-3 py-3">
        <RailFooter gmail={rail.gmail} userEmail={userEmail} />
      </div>
    </aside>
  );
}
