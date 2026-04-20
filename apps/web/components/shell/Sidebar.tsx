import Link from "next/link";
import { LayoutDashboard } from "lucide-react";

import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
] as const;

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-neutral-200 bg-neutral-50/40 md:block dark:border-neutral-800 dark:bg-neutral-950/40">
      <div className="px-4 py-4">
        <Link
          href="/dashboard"
          className="block text-base font-semibold tracking-tight"
        >
          JobTracker
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
                    "text-neutral-700 hover:bg-neutral-200/60",
                    "dark:text-neutral-200 dark:hover:bg-neutral-800/60",
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
