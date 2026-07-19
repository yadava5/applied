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
      // Supabase auth + the FastAPI backend are the only remote calls.
      "connect-src 'self' https://jbyvatoodyqqvkqbsrju.supabase.co https://jobtracker-api-seven.vercel.app",
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
  async rewrites() {
    return [{ source: "/system-card", destination: "/system-card/index.html" }];
  },
};

export default nextConfig;
