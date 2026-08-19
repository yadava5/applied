import { type NextRequest } from "next/server";

import { buildNonceCsp, createNonce } from "@/lib/security/csp";
import { updateSession } from "@/lib/supabase/middleware";

/**
 * Next.js 16 renamed the `middleware.ts` convention to `proxy.ts`
 * (see https://nextjs.org/docs/app/api-reference/file-conventions/proxy).
 * The function body still fulfils the same role: refresh the Supabase
 * session on every eligible request and gate protected routes behind auth.
 *
 * All auth logic lives in `lib/supabase/middleware.ts#updateSession` so it
 * can be unit-tested without a NextRequest mock. This file additionally mints
 * the per-request CSP nonce — see `lib/security/csp.ts` for why the policy is
 * built here rather than declared as a constant in `next.config.ts`.
 */
export async function proxy(request: NextRequest) {
  const nonce = createNonce();
  const csp = buildNonceCsp(nonce);

  /**
   * ORDER IS LOAD-BEARING. Both mutations must happen BEFORE `updateSession`
   * runs. Next reads the nonce off the REQUEST headers during app render
   * (`app-render.js:209-210`), and the request headers reach the render only
   * through the `NextResponse.next({ request })` that `updateSession`
   * constructs — including the one it rebuilds inside `setAll` when Supabase
   * rotates cookies. Set these after the call and the response header still
   * advertises a nonce while nothing in the document carries it, which under
   * `'strict-dynamic'` blocks every script on the page. `csp-gate.mjs`
   * compares the header nonce against the body nonce precisely to catch that.
   */
  request.headers.set("x-nonce", nonce);
  request.headers.set("content-security-policy", csp);

  const response = await updateSession(request);

  /**
   * Set on the response too, because the browser enforces the response header,
   * not the request one. `set` (not `append`) so a route can never end up with
   * two policies, which the browser would intersect.
   *
   * Safe on the redirect exits: `redirectPreservingSession` copies the cookie
   * JAR onto a fresh `NextResponse.redirect`, and setting one header here does
   * not disturb it. Verified on the wire — `/dashboard` signed-out, `/callback`
   * and `/reset-password/callback` all still answer 307 with their `location`
   * intact.
   */
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    /*
     * Run on every path except:
     * - `_next/static`     (static asset bundles)
     * - `_next/image`      (image optimiser)
     * - favicon + metadata files
     * - `system-card`      (see below)
     * - any file with an extension (png/jpg/svg/...)
     *
     * This is the Supabase SSR template's negative matcher plus `system-card`.
     * That path is a self-contained Vite bundle under `public/system-card/`,
     * not an app route, so nothing can inject a nonce into its HTML — and
     * under `'strict-dynamic'` the `'self'` source is ignored, so its one
     * external module script would be blocked outright. It is excluded here
     * and given its own classic `'self'` policy in `next.config.ts`.
     */
    "/((?!_next/static|_next/image|favicon.ico|system-card|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
