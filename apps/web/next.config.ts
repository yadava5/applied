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
   * WHAT `dynamic: 30` TRADES. Rail navigation within a 30-second window
   * serves the payload the tab already has instead of asking the origin. In
   * exchange, data that changed on the server in those 30 seconds — changed by
   * something OTHER than this tab — is not seen until the window closes.
   * Nothing in this app changes server-side on its own: every mutation is a
   * user action in this tab, and `router.refresh()` bumps Next's global
   * segment-cache version (`invalidateSegmentCacheEntries`), so a refresh
   * invalidates EVERY route's entry, not just the one you are standing on.
   * That was checked call-by-call, not assumed — sync, rebuild, stage change,
   * file, reclassify, add, dismiss, restore, split and delete all refresh.
   *
   * The one place they do not is `components/settings/**`, which saves to
   * Supabase user metadata and never refreshes; `app/(app)/settings/page.tsx`
   * therefore opts itself out with `unstable_dynamicStaleTime = 0`. See the
   * note there.
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
    staleTimes: { dynamic: 30, static: 300 },
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
