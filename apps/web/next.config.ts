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
