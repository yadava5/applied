import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { BetaBanner } from "@/components/beta/BetaBanner";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
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
    "Email-powered job application tracking. A 3-layer classifier — rules, e5 embeddings, SetFit — reads the pipeline out of your inbox; the rules stage alone scores 0.9791 macro-F1, CI-gated at 0.95.",
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* Apply the saved theme before paint — no flash, pages stay static. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        {children}
        <BetaBanner />
      </body>
    </html>
  );
}
