import Link from "next/link";
import type { Metadata } from "next";

import { Logo } from "@/components/brand/Logo";
import { InboxWorkbench } from "@/components/gmail/InboxWorkbench";

export const metadata: Metadata = {
  title: "Live scan demo",
  description:
    "The Applied live-scan view on fixture mail — including correcting a verdict the classifier got wrong. No Google connection, no inbox read.",
};

/**
 * The live-scan twin — the REAL `InboxWorkbench` over the simulated scan
 * transport (`lib/gmail/transport.ts`), the same contract `/demo/settings`
 * holds for the settings sections and `/demo` for the board: only the
 * transport is simulated, every control runs its genuine state machine.
 *
 * It exists because `/inbox?view=scan` needs BOTH a Supabase session and a
 * linked Gmail account, which neither CI nor a local checkout has — so the
 * whole scan surface, including the correction control this page was built
 * for, had no executing coverage and nothing reviewable. The alternative was a
 * 22nd session-guarded e2e that skips in CI, which is not coverage.
 *
 * What it faithfully stands in for: the component, its chips, the correction
 * round trip, and the `needs_employer` response — a 2xx that files nothing.
 * What it cannot stand in for: the backend actually storing a scanned message.
 * That is `backend/tests/test_scan_classify.py`, which drives the real
 * endpoint against a real database.
 *
 * Theme-forced dark, per-request rendering: the same rules as the rest of the
 * `/demo` family (`app/demo/settings/page.tsx` documents both).
 */
export const dynamic = "force-dynamic";

export default function DemoScanPage() {
  return (
    <main data-theme="dark" className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-4xl px-6 pb-20">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              aria-label="Applied — home"
              className="brand-logo-link inline-flex min-h-11 items-center text-strong"
            >
              <Logo className="h-6 w-auto" />
            </Link>
            <span className="whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
              demo · fixture mail · nothing is read or saved
            </span>
          </div>
          <Link
            href="/demo"
            className="inline-flex min-h-11 items-center font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
          >
            ← demo
          </Link>
        </header>

        <section className="mt-8 space-y-3">
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Live scan</h1>
          <p className="max-w-2xl text-muted">
            This is the view that reads your mailbox and shows one verdict per message. Here it runs
            on six fixture emails instead — including one the classifier gets wrong.
          </p>
          <div
            role="note"
            className="rounded-xl border border-line-soft bg-surface px-4 py-3 text-sm text-muted"
          >
            <span className="text-strong">The first message is the point.</span> It is plainly an
            assessment; the classifier filed it under <span className="text-strong">other</span>, and
            was not confident even about that. Press{" "}
            <span className="text-strong">reclassify</span> on it, choose{" "}
            <span className="text-strong">assessment</span>, and the row, the filter chips and this
            session&apos;s cached scan all move with your decision. On a real mailbox that
            correction also stores the message — a scan reads Gmail and keeps nothing, so there was
            previously nothing to correct.
          </div>
        </section>

        <div className="mt-8">
          <InboxWorkbench mode="demo" email="demo@applied.example" />
        </div>
      </div>
    </main>
  );
}
