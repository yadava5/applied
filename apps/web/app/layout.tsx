import type { Metadata } from "next";
import { headers } from "next/headers";
import { Geist_Mono } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import { BetaBanner } from "@/components/beta/BetaBanner";
import { BootOverlay } from "@/components/boot/BootOverlay";
import { BOOT_INIT_SCRIPT } from "@/lib/boot/flag";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

/**
 * The product's two voices (see the type-system note in globals.css):
 *
 *  - Atkinson Hyperlegible Next — everything read as language. The Braille
 *    Institute's face, designed so no two letterforms can be confused — the
 *    tagline ("your inbox, made legible") applied to the UI itself, and the
 *    case that matters here: four near-identical role strings on one board.
 *    One variable file (wght 200–800), latin subset, upright only: 34 KB.
 *    Vendored (app/fonts/) rather than pulled through next/font/google
 *    because Next has no fallback-metrics entry for this family — the local
 *    route reads metrics from the file itself and emits a size-adjusted
 *    Arial fallback, so a slow first load cannot shift layout. It also
 *    removes the build-time fetch to Google.
 *  - Geist Mono — kept, but demoted from default voice to data notation:
 *    timestamps, counts, confidence figures, ids, code literals.
 *
 * `next/font` self-hosts both: files are served from this origin as
 * immutable static assets — no runtime request to any font CDN, which the
 * CSP forbids and the privacy posture depends on.
 */
const atkinson = localFont({
  src: "./fonts/atkinson-hyperlegible-next-latin-wght.woff2",
  weight: "200 800",
  style: "normal",
  variable: "--font-atkinson",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  // Absolute base so the relative og:image below resolves to a full https
  // URL for crawlers (LinkedIn/Slack/iMessage/Discord) — the correct
  // App Router idiom, and what makes "/og.png" become an absolute tag.
  metadataBase: new URL("https://getapplied.vercel.app"),
  /**
   * THE MOST PUBLIC SENTENCES APPLIED HAS, and until 2026-08-21 they were the
   * worst. This block renders into every search result, every link preview
   * and the head of every page including the landing, and it read:
   *
   *   "Email-powered job application tracking. A 3-layer classifier — rules,
   *    e5 embeddings, SetFit — reads your applications out of your inbox; the
   *    rules stage alone scores 0.9791 macro-F1, CI-gated at 0.95."
   *
   * That is the architecture, two model names, a self-graded score, the CI
   * threshold and two em dashes, in the one sentence Google prints. The whole
   * landing was swept clean of exactly those things in #394 and this survived
   * it, because a scan of the landing's import graph does not reach
   * `app/layout.tsx` — the same shape as the internals that were surviving
   * inside a video. `tests/unit/landing-voice.test.mjs` scans this file now.
   *
   * IT IS ALSO WHERE THE CATEGORY BELONGS. The landing deliberately refuses
   * to open on "job tracker" (copy.ts says why: the category is a commodity
   * with a graveyard behind it, and leading with it files Applied under every
   * tool the reader already abandoned). But declining to LEAD with the
   * category is not the same as never saying it, and here the reader meets it
   * BEFORE the click, where it is orientation rather than positioning. So the
   * description names the job search plainly and the page still opens on the
   * loss.
   *
   * LENGTH IS A CONSTRAINT: Google truncates around 155 characters and the
   * description is 143. The OpenGraph and Twitter cards get more room, so
   * they carry the two auditable privacy claims as well.
   *
   * THE OG AND TWITTER DESCRIPTIONS USED TO OPEN "A Next.js job-search
   * tool", which named the framework in the first three words of every link
   * anyone shared. That is the loudest "somebody's side project" signal a
   * preview can carry, and it is the same call that took the maker's byline
   * out of the footer on 2026-08-19.
   */
  title: { default: "Applied · your inbox, made legible", template: "%s · Applied" },
  description:
    "Applied reads your job-search mail and moves each application forward for you, so an interview invite never sits unread under sixty other things.",
  openGraph: {
    type: "website",
    url: "https://getapplied.vercel.app",
    title: "Applied",
    description:
      "Applied reads your job-search mail and moves each application forward for you. No AI reads your mail, and the message body is never stored.",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "Applied system-card cover: the Applied wordmark over a dark field of envelope icons on a confidence line, tagline 'The inbox already holds the verdict. Classify it at the source.'",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Applied",
    description:
      "Applied reads your job-search mail and moves each application forward for you. No AI reads your mail, and the message body is never stored.",
    images: ["/og.png"],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  /**
   * The per-request CSP nonce, minted in `proxy.ts`. Next stamps its own
   * framework and RSC-payload scripts automatically, but not the two raw
   * `<script dangerouslySetInnerHTML>` tags below, so they are nonced here.
   *
   * THIS `headers()` READ IS WHAT MAKES EVERY ROUTE DYNAMIC. That is inherent
   * to nonces rather than a cost of this line — Next cannot inject a nonce
   * into a build-time prerender either way — but it is the mechanical reason
   * `/`, `/login`, `/signup`, `/forgot-password` and `/demo/inbox` moved from
   * `○ Static` to `ƒ Dynamic`. See `lib/security/csp.ts` for the measurements
   * that made that trade acceptable.
   */
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${atkinson.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* Apply the saved theme before paint — no flash. Nonced by hand:
            Next stamps its OWN inline scripts but not a raw
            dangerouslySetInnerHTML one (lib/security/csp.ts). */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        {/* Raise the post-auth boot cover before paint when a sign-in armed
            it (lib/boot/flag.ts) — same pattern, same reason: no flash. */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: BOOT_INIT_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        {children}
        {/* Root-mounted so it survives the login → dashboard navigation. */}
        <BootOverlay />
        <BetaBanner />
      </body>
    </html>
  );
}
