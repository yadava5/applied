/**
 * The twin's stand-in for the Supabase user metadata that holds a real
 * account's notification preferences.
 *
 * WHY A COOKIE, and not `localStorage` like the theme. The property that
 * matters is the READ path, not the write: on the live product the SERVER
 * reads the prefs and renders both surfaces from them —
 * `app/(app)/(protected)/settings/page.tsx` seeds the toggles, `app/(app)/(protected)/dashboard/page.tsx`
 * places the queue and builds the subtitle. A cookie reproduces exactly that
 * topology for the public twin (written by the browser, read by the server on
 * the next request), so `/demo` and `/demo/settings` cannot disagree about
 * what is switched on. `localStorage` would force a post-mount client read
 * that the real dashboard never performs — a twin diverging from the surface
 * it stands in for, which is the failure this whole family of demo routes
 * exists to prevent.
 *
 * It is a SESSION cookie (no max-age), scoped to `path=/demo`: it never
 * travels to the signed-in app, carries no identity, holds two booleans the
 * visitor set themselves, and is gone when the browser closes. The privacy
 * page says so (§6) — the demo is the one place in this app that sets a
 * cookie of its own.
 */
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";
// Relative and extensioned, not `@/lib/settings/notifications`, for the reason
// `lib/dashboard/summary.ts` spells out: `node --test` strips types but cannot
// resolve the `@/` alias, so one VALUE import through it would make this
// module — and the parse the twin depends on — untestable. The type-only
// import above is erased before Node sees it, so it may keep the alias.
import { readNotificationPrefs } from "../settings/notifications.ts";

export const DEMO_NOTIFICATIONS_COOKIE = "applied-demo-notifications";

/** Everything under `/demo` — `/demo`, `/demo/settings`, `/demo/shell` — and
 *  nothing above it. Path matching is prefix-plus-`/`, so `/demonstration`
 *  would not match even if such a route existed. */
const COOKIE_PATH = "/demo";

function safeDecode(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    // A malformed escape is a malformed pref: fall through to the parse
    // below, which answers "both off" for anything it cannot read.
    return raw;
  }
}

/**
 * Parse the cookie into the SAME shape, through the SAME defensive reader,
 * that the signed-in page uses on real metadata — so the twin's parse is the
 * product's parse and an absent or garbage cookie yields both flags false,
 * which is also the live default for a never-set preference.
 *
 * Takes the raw value rather than reading `cookies()` itself: the callers are
 * three Server Components that already await their own request context, and
 * keeping this pure is what lets `tests/unit/notification-prefs.test.mjs`
 * drive it.
 */
export function parseDemoNotificationPrefs(raw: string | undefined): NotificationPrefs {
  if (!raw) return readNotificationPrefs({});
  try {
    return readNotificationPrefs({ notifications: JSON.parse(safeDecode(raw)) });
  } catch {
    return readNotificationPrefs({});
  }
}

/** Persist the twin's prefs from the browser. No-op off the client. */
export function writeDemoNotificationPrefs(prefs: NotificationPrefs): void {
  if (typeof document === "undefined") return;
  const value = encodeURIComponent(JSON.stringify(prefs));
  document.cookie = `${DEMO_NOTIFICATIONS_COOKIE}=${value}; path=${COOKIE_PATH}; SameSite=Lax`;
}
