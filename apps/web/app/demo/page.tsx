import Link from "next/link";
import type { Metadata } from "next";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { Logo } from "@/components/brand/Logo";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { DecisionTrace } from "@/components/viz/DecisionTrace";
import { DEMO_APPLICATIONS_AS_API } from "@/lib/demo/asApplications";
import { summarize } from "@/lib/dashboard/summary";

export const metadata: Metadata = {
  title: "Live demo",
  description:
    "The Applied dashboard and classifier decision trace, on fixture data. No inbox is read.",
};

/**
 * The product, auth-free: the exact dashboard a signed-in user sees — the same
 * header hierarchy and the same `PipelineBoard` component (search, company
 * filter, column expanders all live) — rendered from fixtures so a visitor
 * sees it in one click. The file-application form runs in `demo` mode
 * (validated, never saved). Cards are read-only because their corrections
 * would 401 without a session; everything else is the real thing.
 *
 * What the signed-in dashboard dropped, this twin drops too: no stat tiles,
 * no classifier-context strip, no distribution bars, no recent-activity feed.
 * The decision trace stays as the demo's own second act — it is the showcase
 * the landing links to, not a dashboard component.
 */
export default function DemoPage() {
  const summary = summarize(DEMO_APPLICATIONS_AS_API);
  const subtitle = `${summary.total} filed · ${summary.inMotion} in motion · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;

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

        {/* --- 01 · the dashboard, verbatim ------------------------------- */}
        <section aria-labelledby="board-title" className="mt-8 space-y-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="board-title" className="text-2xl font-semibold tracking-tight text-strong">
                Pipeline
              </h2>
              <p className="mt-1 font-mono text-xs text-dim">{subtitle}</p>
            </div>
            <AddApplicationForm mode="demo" />
          </div>
          <PipelineBoard applications={DEMO_APPLICATIONS_AS_API} interactive={false} />
        </section>

        {/* --- the decision trace ----------------------------------------- */}
        {/* No 01/02 numbering: the page is a dashboard twin plus one showcase,
            not a sequence. */}
        <section aria-labelledby="queue-title" className="mt-12">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="queue-title" className="label-mono">
              decision trace — click an email to open its verdict
            </h2>
            <span className="font-mono text-[11px] text-dim">
              CI-gated at 0.95 macro-F1 · 0.979 measured
            </span>
          </div>
          <DecisionTrace />
          <p className="mt-3 font-mono text-[11px] leading-relaxed text-dim">
            Each verdict is traced through three layers — regex rules strike first, e5 embeddings
            arbitrate, a SetFit head renders the call. Below the 0.85 gate nothing is auto-filed;
            the email waits for a human and the correction becomes new training data. 0.979 macro-F1
            on the committed eval set, gated in CI at 0.95.
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
        <p className="mt-12 border-t border-line-soft pt-6 text-center font-mono text-[11px] text-dim">
          beta · direct Gmail connection is invite-only — the sample inbox needs no seat
        </p>
      </div>
    </main>
  );
}
