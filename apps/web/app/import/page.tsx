import Link from "next/link";
import type { Metadata } from "next";

import { ImportMail } from "@/components/import/ImportMail";

export const metadata: Metadata = {
  title: "Import your mail — JobTracker",
  description:
    "Classify your own job-search mail with no Google connection and no sign-in. Your file is parsed and classified entirely in your browser — nothing is uploaded.",
};

/**
 * Public, auth-free, connection-free mail import. A visitor drops a Google
 * Takeout .mbox (or an .eml / JSON export) and sees it classified on-device
 * by the same layer-1 rules engine the sample inbox runs live. No OAuth, no
 * server, no upload — the privacy-preserving way to try the classifier on
 * your OWN mail.
 */
export default function ImportPage() {
  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-6 pb-20">
      <header className="flex h-14 items-center justify-between border-b border-line-soft">
        <div className="flex items-center gap-3">
          <Link href="/" className="font-mono text-sm font-semibold text-strong">
            job<span className="text-dim">_</span>tracker
          </Link>
          <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
            import · on-device · no upload
          </span>
        </div>
        <Link
          href="/demo/inbox"
          className="font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
        >
          sample inbox →
        </Link>
      </header>

      <section className="mt-8 space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Import your mail</h1>
        <p className="max-w-2xl text-muted">
          Classify your own job-search mail without connecting Gmail and without signing in. Export
          your mail from{" "}
          <span className="text-strong">Google Takeout</span> (or drop a single{" "}
          <span className="font-mono text-dim">.eml</span>), and JobTracker runs the classifier on it
          right here in your browser. Nothing is uploaded — this is the same privacy guarantee as the
          rest of the app, made literal.
        </p>
      </section>

      <div className="mt-8">
        <ImportMail />
      </div>

      <p className="mt-10 text-center font-mono text-[11px] leading-relaxed text-dim">
        Prefer to connect the source directly?{" "}
        <Link href="/settings" className="text-muted underline-offset-4 hover:text-strong hover:underline">
          Sign in and connect Gmail read-only
        </Link>{" "}
        — invite-only while we&apos;re in beta.
      </p>
    </main>
  );
}
