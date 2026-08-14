"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";

import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import { isNavItemActive, navItems } from "./nav";
import { NavLink } from "./NavLink";
import { DemoFixturePill, DemoSignupCta, SignOutButton } from "./SessionControls";

type TopBarProps = {
  userEmail: string | null;
  /** Display name for the identity line; `null` falls back to the email. */
  userName?: string | null;
  /**
   * Fixture mode (/demo/shell): there is no session to sign out of, so the
   * sign-out button becomes the demo provenance pill — same slot, same bar
   * height, and an anonymous visitor is never handed a control that can only
   * bounce them to /login.
   */
  demo?: boolean;
};

export function TopBar({ userEmail, userName = null, demo = false }: TopBarProps) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // The route's own name, from the nav vocabulary — never hardcoded, because
  // this one bar serves every authed route and the board twins (/demo,
  // /demo/shell, which `isNavItemActive` counts as /dashboard). The demo
  // fallback survives as a guard for any future fixture route the matcher
  // does not know. The board route gets an <h1>: its page surrendered the
  // in-page header row to the worklist, so the page heading lives here now.
  // Every other route keeps its own <h1> below and this reads as the location
  // label beside it.
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

  return (
    // On the BOARD route this bar yields at `lg`+: the board's own header row
    // (SyncBar — title folded in, sign-out in its ⋯ menu) takes the top line,
    // so the screen never spends 48px on a strip whose middle is empty. Every
    // other route — and every width below `lg`, where the mobile menu and the
    // stacked board header need it — keeps this bar exactly as it is.
    <header
      className={cn(
        "relative flex h-12 items-center justify-between border-b border-line-soft bg-surface px-4",
        isBoardTitle && "lg:hidden",
      )}
    >
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
          {/* In fixture mode "your applications" is the board twin — the real
              /dashboard is an auth bounce for the anonymous visitor. */}
          <Link
            href={demo ? "/demo" : "/dashboard"}
            aria-label="Applied — go to your applications"
            className="brand-logo-link text-strong"
          >
            <Logo variant="mark" className="h-7 w-7" />
          </Link>
        </span>
        {/* The route title. NOT on the board route: its title is the page's
            one <h1>, rendered by the board's own header row at every width
            (SyncBar's `title`) — a second copy here, even CSS-hidden at lg,
            was a duplicate h1 in the document outline and exactly the
            two-nodes-one-hidden shape that keeps producing strict-mode
            locator bugs. The node is simply absent, not hidden. Identity
            lives in the rail footer (desktop) and the mobile menu (below
            `md`). */}
        {current && !isBoardTitle ? (
          <span className="truncate text-sm font-medium text-muted">{current.label}</span>
        ) : null}
      </div>

      {demo ? <DemoFixturePill /> : <SignOutButton />}

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
                title now goes. Same email→name substitution as the rail: the
                name when one is set, the email otherwise, and the email kept
                in `title` so the mailbox is still discoverable. */}
            {userName || userEmail ? (
              <p
                title={userEmail ?? undefined}
                className="mb-2 truncate border-b border-line-soft px-3 pb-2 text-xs text-dim"
              >
                {userName ?? userEmail}
              </p>
            ) : null}
            <ul className="space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = isNavItemActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <NavLink
                      href={item.href}
                      active={active}
                      onClick={() => setMenuOpen(false)}
                      /* `relative` so the pending accent has a containing block
                         — the desktop item already carried it for the active
                         bar, this one did not. An `absolute` child with no
                         positioned ancestor escapes to the nearest one it can
                         find, which is how a stray `sr-only` once made the whole
                         document scroll (#149). */
                      className={cn(
                        "relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
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
                    </NavLink>
                  </li>
                );
              })}
            </ul>
            {/* Fixture mode: the menu is identity + destinations, and for an
                anonymous visitor the honest identity story ends in an
                invitation. Same block the rail footer mounts on desktop —
                DemoSignupCta is the single copy — closing the menu on
                navigation like every destination link above. */}
            {demo ? (
              <div className="mt-2 border-t border-line-soft px-3 pb-1 pt-2.5">
                <DemoSignupCta onNavigate={() => setMenuOpen(false)} />
              </div>
            ) : null}
          </nav>
        </>
      ) : null}
    </header>
  );
}
