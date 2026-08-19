/**
 * The app's Content-Security-Policy, built per request around a fresh nonce.
 *
 * WHY THIS MOVED OUT OF `next.config.ts`. The policy used to be a constant in
 * `securityHeaders` carrying `script-src 'self' 'unsafe-inline'` — which
 * permits inline `<script>` and inline event handlers, i.e. exactly the
 * injection class a CSP exists to stop. The CASA evidence pack names the CSP
 * as the compensating control for `httpOnly: false` session cookies
 * (`docs/casa/SESSION-COOKIES.md` §3.1); with `'unsafe-inline'` present that
 * argument did not hold. A nonce is the only mechanism that closes it here —
 * see WHY NOT HASHES below.
 *
 * HOW NEXT PICKS THE NONCE UP. `proxy.ts` sets this string on the REQUEST
 * headers. During app render Next reads `content-security-policy` off the
 * request and extracts the nonce itself — `app-render.js:209-210` calling
 * `getScriptNonceFromHeader`, whose regex is
 * `/^'nonce-([A-Za-z0-9+/_-]+={0,2})'$/` applied to a space-split token. It
 * then stamps the nonce onto the framework bootstrap, the chunk `<script src>`
 * tags and the streaming RSC payload scripts. It does NOT stamp a raw
 * `<script dangerouslySetInnerHTML>` authored in JSX; `app/layout.tsx` passes
 * `nonce` to its two pre-paint scripts by hand.
 *
 * WHY NOT HASHES, WHICH WOULD HAVE KEPT PAGES STATIC. The prerendered `/`
 * contains four inline scripts. Three are fixed strings and would hash fine.
 * The fourth is the React Flight payload — `self.__next_f.push([1, …])`, 61 KB
 * on the landing page alone — and its content is the rendered page. It changes
 * whenever any content changes, and on a streamed route it is emitted as many
 * chunks that differ per render. There is no stable hash set to pin, so a
 * hash-based `script-src` cannot work for the App Router. Measured on a real
 * production build, not assumed.
 *
 * WHAT IT COST. A nonce requires dynamic rendering: Next injects it at render
 * time from a per-request header, so a build-time prerender cannot carry one.
 * Six routes were `○ Static` before this and are `ƒ Dynamic` now — `/`,
 * `/login`, `/signup`, `/forgot-password`, `/demo/inbox` and `/_not-found` —
 * and `/` lost `Cache-Control: s-maxage=31536000`, so it is an origin render
 * rather than a CDN hit. Measured locally on `next build && next start`:
 * single request 4.1 ms → 8.3 ms; at concurrency 10, p50 12.4 ms → 59.4 ms and
 * p95 25.2 ms → 98.6 ms. Accepted against a ~100-user beta. If this app ever
 * takes real marketing traffic, re-measure before assuming it is still cheap.
 *
 * A HALF-MEASURE WAS CONSIDERED AND REJECTED: noncing only the signed-in
 * routes and leaving the marketing and auth pages static. The session cookie
 * is `Path=/` and readable from `document.cookie` on any same-origin path, so
 * script execution on the static landing page steals the session exactly as
 * well as on `/dashboard`. The weakest route sets the ceiling.
 */

/**
 * `style-src` keeps `'unsafe-inline'`, and that is a structural limit rather
 * than a deferral. The landing page ships 198 inline `style="--d:…ms"`
 * attributes (animation stagger delays) plus a `<style>` block from
 * `next/font`. CSP nonces apply to `<style>` ELEMENTS only — there is no
 * mechanism that lets a nonce cover a style ATTRIBUTE, and `'unsafe-hashes'`
 * would mean enumerating every one of those 198 values. Removing it means
 * refactoring the delays into classes, which is a real change to the design
 * system and out of scope here.
 *
 * The risk profile is also different: inline styles buy an attacker
 * defacement and, with a crafted selector, some limited data inference. They
 * do not buy script execution. `script-src` is where the account-compromise
 * path is, and that is the one now closed.
 *
 * The comment this replaces blamed `styled-jsx` for both relaxations. That was
 * wrong: `styled-jsx` is a transitive dependency of `next` and is never
 * imported in this tree (`grep -rn "styled-jsx\|<style jsx" app components lib`
 * returns nothing).
 */
const STYLE_SRC = "style-src 'self' 'unsafe-inline'";

/**
 * Supabase auth is the only remote origin the BROWSER reaches from here. The
 * backend is called server-side from the route handlers under `app/api/**`,
 * where CSP does not apply — see the long note that used to sit on this
 * directive in `next.config.ts` and now lives in git history for #234/#315.
 */
const CONNECT_SRC = "connect-src 'self' https://jbyvatoodyqqvkqbsrju.supabase.co";

/**
 * `next dev` needs `'unsafe-eval'`; production does not. React uses `eval` in
 * development to reconstruct server-side error stacks in the browser, and the
 * shipped Next guide (`node_modules/next/dist/docs/01-app/02-guides/
 * content-security-policy.md`) prescribes exactly this gate. It matters here
 * because `e2e-ci.yml` runs one job against `next dev` and another against
 * `next build && next start` — a policy that only works in production would
 * redden the first.
 *
 * The gate is on `NODE_ENV`, which Next sets to `"development"` only under
 * `next dev`; `next build`/`next start` and every deployed environment are
 * `"production"`, so this cannot leak into a deployment.
 */
const isDev = process.env.NODE_ENV === "development";

export function buildNonceCsp(nonce: string): string {
  return [
    "default-src 'self'",
    // 'strict-dynamic' makes the nonce the whole story: a browser that honours
    // it IGNORES the 'self' source, so every script must be nonced or loaded
    // by an already-trusted script. 'self' is retained only as the fallback
    // for browsers without 'strict-dynamic' support.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    STYLE_SRC,
    // `img-src` STAYS same-origin, and that survived the arrival of profile
    // photos rather than predating it. The two hosts a photo can come from —
    // Google's avatar CDN and this project's Supabase Storage bucket — are
    // named in `next.config.ts`'s `images.remotePatterns` instead, so
    // `next/image` fetches them server-side and the browser requests
    // `/_next/image?url=…` from this origin. `data:` covers the upload preview,
    // which is a canvas re-encode already sitting in the page; a `blob:` URL
    // would have widened this line for a thumbnail. If an image ever appears
    // blank, check that it is going through `components/ui/AvatarTile` before
    // reaching for this directive.
    "img-src 'self' data:",
    "font-src 'self'",
    CONNECT_SRC,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

/**
 * A fresh nonce per request. `randomUUID` is a CSPRNG; the dashes are stripped
 * so the value matches Next's extraction regex without base64 padding
 * ambiguity.
 */
export function createNonce(): string {
  return crypto.randomUUID().replace(/-/g, "");
}
