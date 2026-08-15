/**
 * The post-auth boot flag. Sign-in surfaces arm it just before handing the
 * browser to the protected area; the `BootOverlay` in the root layout consumes
 * it exactly once and plays the Triage boot over the app's first render.
 *
 * Two arrival shapes, two channels:
 *
 *  - Email sign-in is a client-side `router.replace` — the root layout (and
 *    the overlay in it) survives the transition, so `armBoot` also dispatches
 *    a same-tab event and the overlay is covering the screen before the
 *    navigation even starts.
 *  - Google OAuth is a full document round-trip (login → Google → /callback →
 *    302 /dashboard). Only the sessionStorage flag survives that, and the
 *    overlay's canvas cannot exist until hydration — so `BOOT_INIT_SCRIPT`
 *    runs in <head> before paint (the same pattern as `THEME_INIT_SCRIPT`)
 *    and raises `data-boot` on <html>, which CSS turns into an opaque cover.
 *    No flash of half-loaded shell, no hydration mismatch (`<html>` already
 *    carries `suppressHydrationWarning` for the theme).
 *
 * The flag carries a timestamp and expires after ten minutes so an abandoned
 * OAuth attempt cannot replay the boot on some unrelated later visit, and it
 * only ever activates on the four signed-in routes — never on `/demo`, which
 * has no auth transition to dramatise.
 */

export const BOOT_FLAG_KEY = "jt-boot";
export const BOOT_BEGIN_EVENT = "jt-boot-begin";

/** An armed flag older than this is stale, not a sign-in in flight. */
export const BOOT_FLAG_MAX_AGE_MS = 10 * 60 * 1000;

/** The only surfaces the boot may cover. Mirrored in BOOT_INIT_SCRIPT. */
const BOOT_PATH_RE = /^\/(dashboard|inbox|settings|import)($|[/?#])/;

export function isBootPath(path: string): boolean {
  return BOOT_PATH_RE.test(path);
}

/** Runs in <head> before paint. Kept tiny and dependency-free; clears a
 * stale/foreign flag instead of activating on it. */
export const BOOT_INIT_SCRIPT = `try{var v=sessionStorage.getItem('${BOOT_FLAG_KEY}');if(v){var i=v.lastIndexOf('|');var fresh=Date.now()-(+v.slice(i+1))<${BOOT_FLAG_MAX_AGE_MS};if(fresh&&/^\\/(dashboard|inbox|settings|import)($|[/?#])/.test(location.pathname)){document.documentElement.dataset.boot='1';}else if(!fresh){sessionStorage.removeItem('${BOOT_FLAG_KEY}');}}}catch(e){}`;

/**
 * Arm the boot for `target` (a same-origin path). `notify` dispatches the
 * same-tab event for client-side navigations; the OAuth path leaves it false
 * because the document is about to be replaced anyway and an overlay flash on
 * /login would only race the redirect.
 */
export function armBoot(target: string, { notify = true } = {}): void {
  try {
    sessionStorage.setItem(BOOT_FLAG_KEY, `${target}|${Date.now()}`);
  } catch {
    /* storage blocked — the event path below still works for client navs. */
  }
  if (notify) {
    window.dispatchEvent(new CustomEvent(BOOT_BEGIN_EVENT, { detail: target }));
  }
}

/** Read a live flag's target, or null if absent, stale, or not a boot path. */
export function readBootFlag(): string | null {
  try {
    const v = sessionStorage.getItem(BOOT_FLAG_KEY);
    if (!v) return null;
    const i = v.lastIndexOf("|");
    if (i < 0) return null;
    const ts = Number(v.slice(i + 1));
    if (!Number.isFinite(ts) || Date.now() - ts > BOOT_FLAG_MAX_AGE_MS) return null;
    const target = v.slice(0, i);
    return isBootPath(target) ? target : null;
  } catch {
    return null;
  }
}

export function clearBootFlag(): void {
  try {
    sessionStorage.removeItem(BOOT_FLAG_KEY);
  } catch {
    /* nothing to clear if storage is blocked. */
  }
}
