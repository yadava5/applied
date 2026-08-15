import type { NextConfig } from "next";

/**
 * Security headers applied to every route. The app is same-origin-only
 * (no embedding, no third-party scripts), so the policy is strict: no
 * framing, no MIME sniffing, minimal referrer leakage, and no powerful
 * browser APIs granted.
 */
const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next.js inline runtime + styled-jsx need these two relaxations.
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      // Supabase auth is the only remote origin the BROWSER reaches from here.
      //
      // https://jobtracker-api-seven.vercel.app was listed too, and removing it
      // changed nothing a visitor can do — because connect-src only ever
      // constrained fetches the browser makes, and the browser never makes that
      // one. The backend is reached exclusively from the Next route handlers
      // under app/api/**, server-side, where the caller's Supabase JWT is
      // attached (lib/api/server.ts, lib/applications/server.ts,
      // lib/gmail/server.ts). CSP does not apply to a fetch that originates in
      // the Node runtime, so the grant was doing no work.
      //
      // It is NOT dead infrastructure, and an earlier version of this comment
      // said it was. That claim came from grepping apps/web for the literal
      // host, which returns this line and nothing else — the host reaches the
      // code through BACKEND_API_URL, an env var, so a literal grep can never
      // see it. Proved live instead: GET https://getapplied.vercel.app/api/
      // applications answers 401 with {"detail":{"detail":"Missing
      // Authorization header"}}, and that inner body is the FastAPI backend's,
      // verbatim — the string exists only in backend/jobtracker/auth/
      // supabase_jwt.py and nowhere in this tree. Deleting that project takes
      // down the export, the pipeline board writes, Gmail connect/inbox and
      // account deletion.
      "connect-src 'self' https://jbyvatoodyqqvkqbsrju.supabase.co",
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
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
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
