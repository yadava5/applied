"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";
import { isNavItemActive, navItems } from "./nav";

type TopBarProps = {
  userEmail: string | null;
};

export function TopBar({ userEmail }: TopBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  // The desktop sidebar is hidden below `md`, so this menu is the only way to
  // move between sections on a phone — never leave the user stranded. It closes
  // on Escape, on the backdrop, and whenever a destination link is tapped (each
  // link's onClick), so no route-change effect is needed.
  useEffect(() => {
    if (!menuOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  async function handleSignOut() {
    setIsSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    // Refresh so the proxy re-evaluates and redirects us to /login.
    router.refresh();
    router.replace("/login");
  }

  return (
    <header className="relative flex h-14 items-center justify-between border-b border-line-soft bg-surface px-4">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-strong md:hidden"
        >
          {menuOpen ? (
            <X className="h-5 w-5" aria-hidden="true" />
          ) : (
            <Menu className="h-5 w-5" aria-hidden="true" />
          )}
        </button>
        <div className="truncate font-mono text-sm text-muted">{userEmail ?? ""}</div>
      </div>

      <Button
        type="button"
        variant="ghost"
        onClick={handleSignOut}
        disabled={isSigningOut}
      >
        {isSigningOut ? "Signing out…" : "Sign out"}
      </Button>

      {/* Mobile navigation — mirrors the desktop sidebar (same items + active
          state) and is the only in-app nav below `md`. */}
      {menuOpen ? (
        <>
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setMenuOpen(false)}
            className="fixed bottom-0 left-0 right-0 top-14 z-40 bg-background/70 md:hidden"
          />
          <nav
            id="mobile-nav"
            aria-label="Primary"
            className="absolute inset-x-0 top-14 z-50 border-b border-line-soft bg-surface px-2 py-2 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.8)] md:hidden"
          >
            <ul className="space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = isNavItemActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setMenuOpen(false)}
                      className={cn(
                        "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                        active
                          ? "bg-surface-2 text-strong"
                          : "text-muted hover:bg-surface-2 hover:text-strong",
                      )}
                    >
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
        </>
      ) : null}
    </header>
  );
}
