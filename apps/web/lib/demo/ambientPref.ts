/**
 * The twin's stand-in for the metadata key that holds a real account's
 * ambient-mail preference — the same topology, and the same reasoning, as
 * `notificationPrefs.ts` beside it: the SERVER reads the pref and renders the
 * shell from it (`/demo/shell` mounts or omits the rail's field exactly as
 * the `(app)` layout does), so a cookie written by the demo Settings toggle
 * and read on the next request is the honest reproduction, where a
 * `localStorage` read would be a divergence. Same cookie discipline too:
 * session-lived, scoped to `/demo`, one boolean the visitor set themselves —
 * and named on the privacy page (§6) beside its sibling.
 */
// Relative and extensioned for the reason notificationPrefs.ts spells out:
// `node --test` strips types but cannot resolve the `@/` alias.
import { readAmbientPref } from "../settings/ambient.ts";

export const DEMO_AMBIENT_COOKIE = "applied-demo-ambient";

const COOKIE_PATH = "/demo";

/**
 * Parse the cookie through the SAME defensive reader the signed-in layout
 * uses on real metadata: absent or garbage yields ON, the live default for a
 * never-set preference.
 */
export function parseDemoAmbientPref(raw: string | undefined): boolean {
  if (!raw) return readAmbientPref({});
  try {
    return readAmbientPref({ ambient: JSON.parse(decodeURIComponent(raw)) });
  } catch {
    return readAmbientPref({});
  }
}

/** Persist the twin's pref from the browser. No-op off the client. */
export function writeDemoAmbientPref(on: boolean): void {
  if (typeof document === "undefined") return;
  document.cookie = `${DEMO_AMBIENT_COOKIE}=${JSON.stringify(on)}; path=${COOKIE_PATH}; SameSite=Lax`;
}
