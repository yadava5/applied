import { LayoutDashboard, Inbox, Upload, Settings, type LucideIcon } from "lucide-react";

/**
 * Single source of truth for the authed app's primary navigation. Shared by
 * the desktop `Sidebar` and the mobile menu in `TopBar` so their targets,
 * labels, order, and active-state logic can never drift apart.
 */
export type NavItem = { href: string; label: string; icon: LucideIcon };

export const navItems: NavItem[] = [
  // "Applications", because that is what the rows are and what a person says
  // — "Dashboard" named the furniture, and "Pipeline" was a sales-CRM borrow.
  // The ROUTE stays /dashboard: renames stop at presentation labels.
  { href: "/dashboard", label: "Applications", icon: LayoutDashboard },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/import", label: "Import mail", icon: Upload },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Where each destination lives when the shell is mounted over fixtures
 * (`AppShellFrame`'s `demo` — /demo and /demo/shell). Every signed-in target
 * sits behind the auth proxy, so for the anonymous visitor the demo serves,
 * all four would resolve to a bounce to /login — a rail whose most prominent
 * controls all dead-end is exactly the hostility the demo pill exists to
 * prevent at the session edge. Each mapping is a REAL public surface, never a
 * copy: the board twin, the sample inbox (its own header names it the
 * zero-connection twin of /inbox), the in-browser .mbox import (public by
 * design — "no upload, no sign-in"), and the settings twin. `NavLink` applies
 * the map at the one shared anchor; the items' labels, icons, order and
 * active logic stay this file's to own, so the demo rail can never disagree
 * with the signed-in rail about what the four destinations ARE.
 */
export const demoNavHrefs: Record<string, string> = {
  "/dashboard": "/demo",
  "/inbox": "/demo/inbox",
  "/import": "/import",
  "/settings": "/demo/settings",
};

/** The fixture-mode destination for a nav href; the href itself when the
 *  surface has no public twin to offer. */
export function demoHrefFor(href: string): string {
  return demoNavHrefs[href] ?? href;
}

/**
 * A nav item is active on its own path or any nested child route. `/import`
 * is included here even though it lives outside the `(app)` route group: when
 * a signed-in user opens it, the page renders inside the app shell, so the
 * sidebar must still light "Import mail".
 *
 * The board twins count as /dashboard: /demo and /demo/shell mount the shell
 * around the dashboard twin, and a rail that lights nothing there would drift
 * from the surface the twin stands in for — on the signed-in board,
 * "Applications" is lit. Exact paths rather than a /demo prefix, because the
 * other demo surfaces are different destinations' twins (/demo/inbox is
 * Inbox's) and render no shell today; give them their own clause if they ever
 * do.
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  if (pathname === href || pathname.startsWith(`${href}/`)) return true;
  return href === "/dashboard" && (pathname === "/demo" || pathname === "/demo/shell");
}
