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
 *
 * THE ORIGIN IS A PARAMETER, NOT A LITERAL (#740). It used to be one project
 * ref written into the policy. A deployment pointed at any other Supabase
 * project then BUILT GREEN and shipped a policy that blocks its own auth
 * traffic — nothing type-checks a hostname, and the server side is unaffected.
 *
 * What that costs is worse than a degraded refresh: sign-in itself never
 * leaves the page. `signInWithPassword` (`app/(auth)/login/page.tsx`),
 * `signOut` (`components/shell/SessionControls.tsx`), signup,
 * forgot-password, `SetNewPasswordForm`, the Google button and every call in
 * `lib/settings/transport.ts` are browser fetches to THIS origin, and each is
 * blocked at the first attempt. Meanwhile `app/api/**` keeps answering under
 * `'self'`, so every server-side probe reads healthy while nobody can log in.
 *
 * Not hypothetical — the repo already recorded the symptom. The docblock in
 * `tests/e2e/auth.spec.ts` describes CI and local dev running against the
 * placeholder `https://example.supabase.co` and the fetch failing in the page
 * with no request ever routed. That is this defect, observed, and it is why
 * that file needed a second instrument.
 *
 * WHY A PARAMETER RATHER THAN READING `publicEnv` HERE. The read costs nothing
 * in `proxy.ts` either way — it already imports `updateSession`, which imports
 * `publicEnv` — so the reason is testability, and it is not a stylistic one. A
 * value this module reads for itself cannot be VARIED, and a test that set
 * `process.env` would exercise a runtime read production does not have:
 * `NEXT_PUBLIC_*` is inlined as literal text at build time (see `lib/env.ts`
 * for why those reads are spelled out in full rather than indexed). The
 * parameter is in the signature precisely so a unit test can hand this
 * function two different origins and watch both reach the policy — an
 * expectation naming the CURRENT project would have passed against the
 * hardcoded literal too, and proved nothing.
 *
 * NO VALIDATION HERE, deliberately. `lib/env.ts#requireUrl` already fails the
 * build on an absent or malformed `NEXT_PUBLIC_SUPABASE_URL`; a second layer
 * would only be a second thing to keep in step.
 */
const connectSrc = (supabaseOrigin: string) => `connect-src 'self' ${supabaseOrigin}`;

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

/**
 * @param nonce          The per-request nonce, from `createNonce()`.
 * @param supabaseOrigin The deployment's Supabase ORIGIN — scheme, host and
 *   port only. Pass `new URL(publicEnv.NEXT_PUBLIC_SUPABASE_URL).origin`, not
 *   the raw variable: a trailing slash or any path would be read by the
 *   browser as a path restriction on the source, which is a different (and
 *   narrower) policy than the one intended.
 */
export function buildNonceCsp(nonce: string, supabaseOrigin: string): string {
  return [
    "default-src 'self'",
    // 'strict-dynamic' makes the nonce the whole story: a browser that honours
    // it IGNORES the 'self' source, so every script must be nonced or loaded
    // by an already-trusted script. 'self' is retained only as the fallback
    // for browsers without 'strict-dynamic' support.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    STYLE_SRC,
    "img-src 'self' data:",
    "font-src 'self'",
    connectSrc(supabaseOrigin),
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
