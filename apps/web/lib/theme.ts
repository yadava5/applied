/**
 * Appearance theme. The app is monochrome dark by default; a user can opt into
 * a light palette in Settings. The choice lives in `localStorage` (a device
 * preference, like the beta-banner dismissal) and is applied to
 * `document.documentElement.dataset.theme` by a tiny blocking script injected
 * in the root layout BEFORE first paint, so there is no flash of the wrong
 * theme. `localStorage` rather than a cookie keeps the choice off the request,
 * so the theme costs no per-request read. NOTE: that used to also mean "pages
 * stay statically renderable"; it no longer does. Every route is dynamic now
 * because the nonce-based CSP requires it (`lib/security/csp.ts`) — the theme
 * is not what forces it, and reverting the theme to a cookie would not buy
 * static rendering back.
 */
export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "jt-theme";

/** Runs in <head> before paint. Kept tiny and dependency-free. Defaults to
 * dark (the brand default) for any unset/invalid/blocked-storage case. */
export const THEME_INIT_SCRIPT = `try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');document.documentElement.dataset.theme=(t==='light')?'light':'dark';}catch(e){document.documentElement.dataset.theme='dark';}`;

/** Same-tab notification channel for theme changes (the browser `storage`
 * event only fires in OTHER tabs). */
export const THEME_CHANGE_EVENT = "jt-theme-change";

/** Read the theme currently applied to <html> (set by the pre-paint script).
 * Safe to call during render; returns the dark default on the server. */
export function readAppliedTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

/**
 * Apply and persist a theme choice: flip `data-theme` on <html>, save it, and
 * notify same-tab subscribers. Lives here (not in a component body) so the DOM
 * write is a plain module side effect, invoked only from event handlers.
 */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage blocked — the in-session switch still applied above. */
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}
