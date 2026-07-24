"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import { isNavItemActive, navItems } from "./nav";

/**
 * Desktop primary navigation (hidden below `md`; the mobile menu in `TopBar`
 * takes over there). The item matching the current route gets a clear active
 * treatment — a cyan accent bar, a lit icon, a raised surface, and
 * `aria-current="page"` — so it is always obvious which section you are in.
 */
export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-line-soft bg-surface md:block">
      <div className="px-4 py-4">
        <Link
          href="/dashboard"
          aria-label="Applied — go to dashboard"
          className="brand-logo-link text-strong"
        >
          <Logo className="h-7 w-auto" />
        </Link>
      </div>
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
                    "relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
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
                    className={cn("h-4 w-4", active && "text-viz-rules")}
                    aria-hidden="true"
                  />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
