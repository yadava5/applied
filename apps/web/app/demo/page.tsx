import Link from "next/link";
import type { Metadata } from "next";

import { Logo } from "@/components/brand/Logo";
import { DemoDashboard } from "@/components/demo/DemoDashboard";
import { DecisionTrace } from "@/components/viz/DecisionTrace";

export const metadata: Metadata = {
  title: "Live demo",
  description:
    "The Applied dashboard and classifier decision trace, on fixture data. No inbox is read.",
};

/**
 * Rendered per request, because the fixtures are dated RELATIVE to today.
 *
 * As a static route this page is prerendered once and the build day's dates are
 * baked into the HTML on disk, while the client resolves "today" at view time —
 * so the filed stamps disagree and React throws a hydration error (#418) on
 * every day after the build. Measured: clean at +0d, mismatching at +3d, +30d
 * and +180d, and clean again at +365d, where the stamp string happens to
 * repeat. That last one is the proof it is the date and nothing else.
 *
 * Resolving the date on the server and passing it down does NOT fix this on a
 * static route — there, "server render time" IS build time, so the demo would
 * simply resume ageing, which is the defect the relative dates removed. Only
 * per-request rendering collapses the window to the UTC-midnight boundary that
 * `lib/dashboard/age.ts` already documents as accepted.
 */
export const dynamic = "force-dynamic";

/**
 * The product, auth-free: the exact dashboard a signed-in user sees, running
 * its real components — SyncBar, the board, drag, the detail sheet — over an
 * in-memory fixture store (`DemoDashboard`). Only the transport is simulated;
 * every interaction is the genuine state machine, which is both the "demo is
 * the real thing" contract and what gives the session-gated surfaces their
 * executing e2e coverage.
 *
 * What the signed-in dashboard dropped, this twin drops too: no stat tiles,
 * no classifier-context strip, no distribution bars, no recent-activity feed.
 * The decision trace stays as the demo's own second act — it is the showcase
 * the landing links to, not a dashboard component.
 */
export default function DemoPage() {
  return (
    <main data-theme="dark" className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-6xl px-6 pb-16">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="brand-logo-link inline-flex min-h-11 items-center text-strong"
              aria-label="Applied — go to landing"
            >
              <Logo className="h-6 w-auto" />
            </Link>
            <span className="whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
              demo · fixture data · no inbox read
            </span>
          </div>
          <Link
            href="/"
            className="inline-flex min-h-11 items-center font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
          >
            ← landing
          </Link>
        </header>

        {/* --- the dashboard, verbatim ------------------------------------ */}
        <div className="mt-8">
          <DemoDashboard />
        </div>

        {/* --- the decision trace ----------------------------------------- */}
        {/* No 01/02 numbering: the page is a dashboard twin plus one showcase,
            not a sequence. */}
        <section aria-labelledby="queue-title" className="mt-12">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="queue-title" className="label-caps">
              decision trace — click an email to open its verdict
            </h2>
            {/* The qualifier is load-bearing and matches the landing's pill:
                0.979 is the RULES stage, and this line sits directly above a
                trace of the three-layer cascade, where an unqualified number
                reads as the cascade's. It is not — the full cascade scores
                0.958 on the same 96-email set (README, "Classifier
                evaluation"). This figure has drifted before. */}
            <span className="font-mono text-[11px] text-dim">
              CI-gated at 0.95 macro-F1 · rules stage 0.979
            </span>
          </div>
          <DecisionTrace />
          <p className="mt-3 text-xs leading-relaxed text-dim">
            Each verdict is traced through three layers — regex rules strike first, e5 embeddings
            arbitrate, a SetFit head renders the call. Below the 0.85 gate nothing is auto-filed;
            the email waits for a human and the correction becomes new training data. To be precise
            about what the score measures: 0.979 macro-F1 is the <strong>rules stage</strong> on the
            committed 96-email benchmark, gated in CI at 0.95. The full cascade scores 0.958 on that
            same set.
          </p>
          <Link
            href="/demo/inbox"
            className="mt-6 inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-4 py-2.5 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            Run a full sample inbox through the real classifier
            <span aria-hidden>→</span>
          </Link>
        </section>

        {/* In flow, not floating: the fixed beta pill used to sit on top of
            board content here, so the demo carries its beta note statically. */}
        <p className="mt-12 border-t border-line-soft pt-6 text-center text-xs text-dim">
          beta · direct Gmail connection is invite-only — the sample inbox needs no seat
        </p>
      </div>
    </main>
  );
}
