import type { NextConfig } from "next";

/**
 * Security headers applied to every route. The app is same-origin-only
 * (no embedding, no third-party scripts), so the policy is strict: no
 * framing, no MIME sniffing, minimal referrer leakage, and no powerful
 * browser APIs granted.
 *
 * `Content-Security-Policy` is deliberately NOT in this list any more. It is
 * built per request in `lib/security/csp.ts` and set by `proxy.ts`, because it
 * now carries a per-request nonce and a constant cannot. Do not add one back
 * here: on a production build an entry in this array OVERRIDES a header set
 * elsewhere for the same key — measured, and documented on `noStoreHeaders`
 * below for `Cache-Control`. A CSP re-added here would win over the nonced one
 * and the app would serve nonced HTML behind a policy that never mentions the
 * nonce, which fails closed (every script blocked) or, if someone "fixed" it
 * by restoring `'unsafe-inline'`, fails open and silently. `scripts/csp-gate.mjs`
 * catches both by comparing the served header against the served body.
 */
const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

/**
 * No-store directives for every route handler under `/api` (#315).
 *
 * These three are not a house style — they are exactly what `@supabase/ssr`
 * hands to `setAll` as its second argument (`applyServerStorage` in
 * `@supabase/ssr/dist/main/cookies.js`), the headers the library wants on any
 * response that carries the cookies it wrote. `lib/supabase/middleware.ts`
 * already applies them to the proxy's response. `tests/unit/api-no-store-
 * headers.test.mjs` asks the INSTALLED library for them at runtime and fails if
 * these values ever stop matching, so a version bump is compared rather than
 * silently diverged from. Do not hand-edit them to something that looks
 * equivalent.
 *
 * WHY THE WHOLE `/api` SURFACE AND NOT ONE HANDLER. #315 was filed against
 * `app/api/account/delete/route.ts`, which returns JSON while `getUser()` may
 * have rotated the session, and which declared no `Cache-Control` — so Vercel's
 * edge supplied one, and it says `public`:
 *
 *     $ curl -D - "https://getapplied.vercel.app/login"
 *     cache-control: public, max-age=0, must-revalidate
 *
 * `public` is an explicit shared-cache storage licence. It is the platform's
 * default rather than anyone's decision, which is the kind that changes under
 * you, and #234 measured a real `s-maxage=31536000` out of this same
 * deployment.
 *
 * It is not one handler, and the reason was measured rather than assumed. Only
 * three route handlers import `lib/supabase/server` directly, but every handler
 * under `app/api/` reaches `createClient()` transitively through
 * `lib/api/server.ts` -> `getAccessToken()` -> `getCurrentSession()` ->
 * `auth.getSession()`. Driving the INSTALLED `@supabase/ssr` 0.12.4 with a
 * cookie jar holding a session past its expiry, `getSession()` refreshed and
 * called `setAll` once, with all three of these headers and a rewritten
 * `sb-<ref>-auth-token`. The control — the same probe with a session an hour
 * from expiry — fired `setAll` zero times and made no network call. So
 * "getSession only reads the cookie" is false, and the set of handlers whose
 * response can carry a library-written cookie is every one of them.
 *
 * WHY IT IS SAFE TO DECLARE THIS BLANKET. All seventeen handlers under
 * `app/api/` are user-scoped proxies to the FastAPI backend or auth-adjacent
 * actions. Not one of them wants to be cached, by a shared cache or a private
 * one.
 *
 * A CONSTRAINT FOR WHOEVER ADDS A CACHING ROUTE LATER: on a production build
 * this entry OVERRIDES a `Cache-Control` the handler sets itself — measured,
 * with the handler returning one value and this config another; the config's
 * won. A route under `/api` that genuinely wants caching has to change this
 * source pattern, not set its own header and hope.
 *
 * The two PKCE callbacks (`/callback`, `/reset-password/callback`) also carry
 * session cookies and are NOT under `/api`. They sit beside page routes, so
 * covering them here would mean widening this pattern onto paths that serve
 * HTML — and `/login` legitimately carries `s-maxage=31536000` as a prerender.
 * They are PR #312's subject, which is open and unmerged as this lands. The
 * enumeration in the test named above knows about both, says so, and fails if
 * a route handler appears that is neither covered here nor one of them.
 */
const noStoreHeaders = [
  { key: "Cache-Control", value: "private, no-cache, no-store, must-revalidate, max-age=0" },
  { key: "Expires", value: "0" },
  { key: "Pragma", value: "no-cache" },
];

/**
 * The path pattern above. Named so the test can assert against the same string
 * this config ships, rather than restating it and pinning nothing.
 */
export const API_NO_STORE_SOURCE = "/api/:path*";

/**
 * The System Card is a self-contained Vite bundle under `public/system-card/`,
 * not an app route. It is excluded from the proxy matcher, so it never gets a
 * nonce — and under the app's `'strict-dynamic'` policy `'self'` is IGNORED,
 * which would block its one external module script outright. Measured, not
 * assumed: the CSP gate reported `un-nonced=1` on `/system-card` against
 * `<script type="module" crossorigin src="/system-card/assets/index-*.js">`.
 * It therefore carries its own classic `'self'` policy. No inline script
 * exists in that bundle (verified: zero `<script>…</script>` bodies in
 * `public/system-card/index.html`), so it needs no inline grant.
 */
export const SYSTEM_CARD_SOURCE = "/system-card/:path*";

const systemCardHeaders = [
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  /**
   * The router cache. This is the fix for the reported symptom in issue #203:
   * 12 of 12 in-app navigations issued a fresh `_rsc` request, so returning to
   * a tab you were on ten seconds ago re-paid the whole 700–1150 ms of server
   * time (dashboard→inbox measured 1090 / 989 / 1019 ms on visits 1, 2, 3 —
   * visit 3 costs exactly what visit 1 did). Every one of these routes is
   * `ƒ Dynamic`, and Next's default `staleTimes.dynamic` is 0, which means no
   * client cache at all, by construction.
   *
   * WHAT A STALE WINDOW TRADES. Rail navigation within the window serves the
   * payload the tab already has instead of asking the origin. In exchange,
   * data that changed on the server inside that window — changed by something
   * OTHER than this tab — is not seen until it closes. Every in-tab mutation
   * heals itself: `router.refresh()` bumps Next's global segment-cache version
   * (`invalidateSegmentCacheEntries`), so a refresh invalidates EVERY route's
   * entry, not just the one you are standing on. That was checked
   * call-by-call, not assumed — sync, rebuild, stage change, file, reclassify,
   * add, dismiss, restore, split and delete all refresh.
   *
   * WHY IT IS 300 AND NOT 30. Thirty seconds was too short to be the thing it
   * was for. Measured on production at `dynamic: 30`: /inbox on a first visit
   * settled in 1124 ms and issued one `_rsc` request; back to /dashboard
   * inside the window, 78 ms and zero requests; /inbox again inside the
   * window, 33 ms and zero. The cache was never broken — it was 15–30× and
   * then it expired. Visit a tab, work for a minute, come back, and the whole
   * 1124 ms is re-paid, which is experienced as the app being randomly slow.
   * Nothing pre-warms it away, either: `<Link prefetch={true}>` issues NOTHING
   * for these `ƒ Dynamic` routes, and an explicit `router.prefetch()` on a cold
   * route does fire requests but the navigation that follows still cost 460 ms
   * and still hit the network — the prefetched payload was not reused. The
   * window is the only knob that works, so it is set to the length of a
   * working session rather than the length of a pause.
   *
   * WHAT MAKES 300 SAFE — AND THE SENTENCE THIS REPLACES. An earlier version of
   * this note said "nothing in this app changes server-side on its own: every
   * mutation is a user action in this tab". THAT IS NO LONGER TRUE. #284 added
   * a scheduled sync — the `crons` entry in the repo-root `vercel.json`, on a
   * fifteen-minute schedule, hitting `/cron/sync` on the backend project (the
   * cron expression is not quoted here: its slash-star would close this block
   * comment, which is exactly how the first draft of this note failed `tsc`).
   * So mail is filed and the board moves every 15 minutes with no tab open and
   * nobody watching. A five-minute cache on top of that, alone, would be a
   * stale-data bug. It does not ship alone: `components/shell/ReturnRefresh`
   * mounts one listener in the signed-in shell and calls `router.refresh()`
   * when the reader comes back after being away longer than
   * `AWAY_REFRESH_THRESHOLD_MS` (60 s — `lib/shell/awayRefresh.ts`). Away
   * beyond a glance, and the cache is dropped wholesale on return; a glance,
   * and nothing is spent. The threshold is deliberately BELOW this window and
   * must stay there: past 300 s the next navigation refetches anyway, so the
   * two numbers being different is what gives the rule anything to do. The
   * residual exposure, stated plainly rather than left to be discovered: a
   * reader who never leaves the tab at all can be up to 300 s behind a
   * cron-written change, against a cron that runs every 900 s.
   *
   * `components/settings/**` saves to Supabase user metadata, and its writers
   * refresh too (#216/#231) — `/settings` used to pin itself out with
   * `unstable_dynamicStaleTime = 0` when they did not. The pin is gone
   * (perf/nav-latency): every route participates now, and the writer contract
   * is held by `tests/unit/settings-publish-contract.test.mjs` instead of a
   * per-navigation origin tax. See the note in `app/(app)/(protected)/settings/page.tsx`.
   *
   * WHY `static` IS PINNED AT ITS DEFAULT. 300 is already Next 16's default
   * (`config-shared.js`), so this line changes nothing — it is here because
   * supplying a `staleTimes` object replaces the default object wholesale, and
   * `createSelectStaleTime` gates the server-side static override on
   * `typeof staleTimes.static === 'number'`. Omitting the key would quietly
   * drop that path. Lowering it to 180, as first proposed, would have been a
   * REGRESSION dressed as a tuning knob.
   */
  experimental: {
    staleTimes: { dynamic: 300, static: 300 },
  },
  /**
   * The image optimizer, and the two hosts profile photos may come from.
   *
   * THIS BLOCK IS THE PRIVACY MECHANISM, not a performance tweak. Applied
   * renders one remote image — the account's profile photo — and it has two
   * possible origins: Google's avatar CDN for a Google sign-in, and this
   * project's Supabase Storage bucket for an uploaded one. Naming them here is
   * what lets `next/image` fetch them SERVER-SIDE, so the browser only ever
   * requests `/_next/image?url=…` from Applied's own origin. Take this out and
   * "fix" the tile with a plain `<img>` and every signed-in page load becomes a
   * request to Google carrying the reader's IP and the timing of their job
   * search — on a product whose pitch is that nothing reads your mail. The long
   * version is in `lib/profile/avatar.ts`.
   *
   * IT IS ALSO WHY THE CSP DID NOT MOVE. `img-src 'self' data:` in
   * `lib/security/csp.ts` is unchanged by this feature, because there is no
   * cross-origin image load left to permit. If a future change points an
   * `<img>` straight at either host, the image will be BLOCKED and it will look
   * like a bug in the tile rather than a policy decision — that is the trap,
   * and it is deliberate.
   *
   * THE SUPABASE HOST IS SPELLED OUT rather than derived from
   * `NEXT_PUBLIC_SUPABASE_URL`, matching the identical literal in the CSP's
   * `connect-src`: the config is also loaded standalone (transpiled, imported
   * from a data: URL) by `tests/unit/api-no-store-headers.test.mjs`, where a
   * missing env var would fail the gate rather than the app. Its pathname is
   * pinned to the avatars bucket's public prefix so the optimizer cannot be
   * driven at anything else in the project.
   *
   * `*.googleusercontent.com` covers the `lh3`…`lh6` shards Google has served
   * avatars from; `lib/profile/avatar.ts` validates the same family before a
   * URL ever reaches this component, and `tests/unit/profile-avatar.test.mjs`
   * asserts the two agree — a URL this config refuses would otherwise fall back
   * to the monogram silently.
   *
   * `minimumCacheTTL` IS LONG ON PURPOSE, and it is safe because of a decision
   * made elsewhere: an uploaded photo's object path carries a UUID
   * (`newAvatarPath`), so replacing one produces a new URL rather than needing
   * a cached one invalidated. Thirty days means Google is asked for a given
   * avatar roughly once a month instead of once a page — the point of the whole
   * arrangement — and it caps what Vercel's Image Optimization is billed for.
   * The trade, stated plainly: a user who changes their photo AT GOOGLE and
   * keeps the same URL can see the old one here for up to thirty days, and
   * uploading their own is the immediate way out.
   *
   * `dangerouslyAllowSVG` is left at its `false` default and must stay there:
   * an SVG is a script vector, and the one thing this optimizer fetches is a
   * file chosen by a third party.
   */
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.googleusercontent.com", search: "" },
      {
        protocol: "https",
        hostname: "jbyvatoodyqqvkqbsrju.supabase.co",
        pathname: "/storage/v1/object/public/avatars/**",
        search: "",
      },
    ],
    minimumCacheTTL: 60 * 60 * 24 * 30,
  },
  async headers() {
    return [
      { source: "/(.*)", headers: securityHeaders },
      { source: SYSTEM_CARD_SOURCE, headers: systemCardHeaders },
      { source: API_NO_STORE_SOURCE, headers: noStoreHeaders },
    ];
  },
  // The System Card is a self-contained Vite build committed under
  // public/system-card/ (see booklet/ · `npm run build:system-card`). Serve its
  // entry at the clean /system-card path; the hashed assets under
  // /system-card/assets/* resolve as static files directly.
  //
  // `beforeFiles` (not the default afterFiles): /system-card is NOT an app route,
  // so an RSC data request for it (`?_rsc=…` + `RSC: 1`, emitted if anything ever
  // <Link>-prefetches it) resolves to a 404 *before* an afterFiles rewrite runs —
  // the console error the audit flagged (JT-1). Rewriting in beforeFiles maps the
  // request to the static index.html ahead of route/RSC resolution, so it returns
  // the page (200) instead. The landing already links it with a plain <a> (no
  // prefetch); this is the belt-and-suspenders root fix for the endpoint itself.
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/system-card", destination: "/system-card/index.html" },
      ],
    };
  },
};

export default nextConfig;
