/**
 * Warm the ORIGIN — not the client — for the tabs the user is about to click.
 *
 * What this is, stated precisely, because the distinction has been proven the
 * hard way (see the staleTimes note in next.config.ts): Next 16.3 issues no
 * prefetch for `ƒ Dynamic` routes, and even an explicit `router.prefetch()`
 * payload is not reused by the navigation that follows. Nothing here claims
 * otherwise. These are plain same-origin fetches whose responses are thrown
 * away; their only value is server-side — the serving instance requires each
 * route's module graph before the user's first click pays for it, and the
 * FastAPI backend answers one request per surface while the boot animation
 * still has the screen. The user's later navigation still renders on the
 * origin and still hits the network.
 *
 * Fired once, at boot RESOLVE rather than boot start, deliberately: the
 * dashboard's own render is in flight during the loop, and racing it with
 * three more origin renders invites Fluid's concurrency-based scale-out —
 * spawning the cold instances this is meant to avoid. By resolve time the
 * app is interactive and the requests trail behind the user, staggered.
 */

import { isBootPath } from "@/lib/boot/flag";

const WARM_ROUTES = ["/dashboard", "/inbox", "/settings", "/import"];
const WARM_STAGGER_MS = 300;

let warmed = false;

export function warmSiblingRoutes(currentPath: string): void {
  if (warmed) return;
  warmed = true;
  if (!isBootPath(currentPath)) return;
  const rest = WARM_ROUTES.filter((r) => !currentPath.startsWith(r));
  rest.forEach((route, i) => {
    window.setTimeout(() => {
      // Same-origin GET with the session cookies, so the render is the real
      // one (auth + backend reads), not a redirect-to-login stub. The
      // response body is never read.
      fetch(route, { credentials: "same-origin", cache: "no-store" }).catch(() => {
        /* a failed warm costs nothing — the click just pays the cold price */
      });
    }, WARM_STAGGER_MS * (i + 1));
  });
}
