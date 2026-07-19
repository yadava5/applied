import { LayoutDashboard, Inbox, Upload, Settings, type LucideIcon } from "lucide-react";

/**
 * Single source of truth for the authed app's primary navigation. Shared by
 * the desktop `Sidebar` and the mobile menu in `TopBar` so their targets,
 * labels, order, and active-state logic can never drift apart.
 */
export type NavItem = { href: string; label: string; icon: LucideIcon };

export const navItems: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/import", label: "Import mail", icon: Upload },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * A nav item is active on its own path or any nested child route. `/import`
 * is included here even though it lives outside the `(app)` route group: when
 * a signed-in user opens it, the page renders inside the app shell, so the
 * sidebar must still light "Import mail".
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
