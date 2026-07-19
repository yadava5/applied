import Link from "next/link";
import { LayoutDashboard, Inbox, Settings } from "lucide-react";

import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-line-soft bg-surface md:block">
      <div className="px-4 py-4">
        <Link
          href="/dashboard"
          className="block font-mono text-sm font-semibold tracking-tight text-strong"
        >
          job<span className="text-dim">_</span>tracker
        </Link>
      </div>
      <nav className="px-2" aria-label="Primary">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                    "text-muted hover:bg-surface-2 hover:text-strong",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
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
