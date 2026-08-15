import type { Metadata } from "next";
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
  title: { default: "Applied — your inbox, made legible", template: "%s · Applied" },
  description:
    "Email-powered job application tracking. A 3-layer classifier — rules, e5 embeddings, SetFit — reads your applications out of your inbox; the rules stage alone scores 0.9791 macro-F1, CI-gated at 0.95.",
  openGraph: {
    type: "website",
    url: "https://getapplied.vercel.app",
    title: "Applied",
    description:
      "A Next.js job-search tool: connect Gmail, fetch your inbox, and a classifier turns it into a live dashboard of your real applications.",
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
      "A Next.js job-search tool: connect Gmail, fetch your inbox, and a classifier turns it into a live dashboard of your real applications.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${atkinson.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* Apply the saved theme before paint — no flash, pages stay static. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        {/* Raise the post-auth boot cover before paint when a sign-in armed
            it (lib/boot/flag.ts) — same pattern, same reason: no flash. */}
        <script dangerouslySetInnerHTML={{ __html: BOOT_INIT_SCRIPT }} />
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
