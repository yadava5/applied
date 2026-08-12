"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";
import { isNavItemActive, navItems } from "./nav";

type TopBarProps = {
  userEmail: string | null;
  /**
   * Fixture mode (/demo/shell): there is no session to sign out of, so the
   * sign-out button becomes the demo provenance pill — same slot, same bar
   * height, and an anonymous visitor is never handed a control that can only
   * bounce them to /login.
   */
  demo?: boolean;
};

export function TopBar({ userEmail, demo = false }: TopBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  // The route's own name, from the nav vocabulary — never hardcoded, because
  // this one bar serves every authed route (and /demo/shell, whose path
  // matches no nav item but which IS the board twin). The board route gets an
  // <h1>: its page surrendered the in-page header row to the worklist, so the
  // page heading lives here now. Every other route keeps its own <h1> below
  // and this reads as the location label beside it.
  const current =
    navItems.find((item) => isNavItemActive(pathname, item.href)) ?? (demo ? navItems[0] : null);
  const isBoardTitle = current?.href === "/dashboard";

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
    <header className="relative flex h-12 items-center justify-between border-b border-line-soft bg-surface px-4">
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
        {/* Compact mark — the desktop sidebar wordmark is hidden below `md`, so
            this keeps the app branded (and gives a home link) on phones. The
            `md:hidden` lives on a wrapper because `.brand-logo-link` sets
            `display` in unlayered CSS (globals), which outranks the layered
            utility on the same element — hiding the parent sidesteps that. */}
        <span className="shrink-0 md:hidden">
          <Link
            href="/dashboard"
            aria-label="Applied — go to your applications"
            className="brand-logo-link text-strong"
          >
            <Logo variant="mark" className="h-7 w-7" />
          </Link>
        </span>
        {/* The route title — this bar's one piece of content besides sign-out,
            in a bar that measured 92% empty. Identity lives in the rail
            footer (desktop) and the mobile menu (below `md`). */}
        {current ? (
          isBoardTitle ? (
            <h1 className="truncate text-sm font-semibold tracking-tight text-strong">
              {current.label}
            </h1>
          ) : (
            <span className="truncate text-sm font-medium text-muted">{current.label}</span>
          )
        ) : null}
      </div>

      {demo ? (
        <Link
          href="/demo"
          aria-label="Demo shell on fixture data — back to the demo overview"
          className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted transition-colors hover:text-strong focus-accent"
        >
          demo · fixture data
        </Link>
      ) : (
        <Button type="button" variant="ghost" onClick={handleSignOut} disabled={isSigningOut}>
          {isSigningOut ? "Signing out…" : "Sign out"}
        </Button>
      )}

      {/* Mobile navigation — mirrors the desktop sidebar (same items + active
          state) and is the only in-app nav below `md`. */}
      {menuOpen ? (
        <>
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setMenuOpen(false)}
            className="fixed bottom-0 left-0 right-0 top-12 z-40 bg-background/70 md:hidden"
          />
          <nav
            id="mobile-nav"
            aria-label="Primary"
            className="absolute inset-x-0 top-12 z-50 border-b border-line-soft bg-surface px-2 py-2 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.8)] md:hidden"
          >
            {/* Identity lives here below `md` (the rail footer's job on
                desktop) — it used to sit in the bar itself, where the route
                title now goes. */}
            {userEmail ? (
              <p className="mb-2 truncate border-b border-line-soft px-3 pb-2 text-xs text-dim">
                {userEmail}
              </p>
            ) : null}
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
