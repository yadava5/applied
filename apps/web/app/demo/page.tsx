import Link from "next/link";
import type { Metadata } from "next";

import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { ClassifierContext, StatTiles } from "@/components/dashboard/StatTiles";
import { DecisionTrace } from "@/components/viz/DecisionTrace";
import { StageFunnel } from "@/components/viz/StageFunnel";
import { DEMO_APPLICATIONS_AS_API } from "@/lib/demo/asApplications";
import { summarize } from "@/lib/dashboard/summary";

export const metadata: Metadata = {
  title: "Live demo — Applied",
  description:
    "The Applied dashboard and classifier decision trace, on fixture data. No inbox is read.",
};

/**
 * The product, auth-free: the exact dashboard a signed-in user sees — the same
 * StatTiles, pipeline funnel, board, and recent-activity components — rendered
 * from fixtures so a visitor sees it in one click. The file-application form is
 * live too, in `demo` mode (validated, never saved), so the full UX is
 * exercisable without an account. Read-only by design.
 */
export default function DemoPage() {
  const summary = summarize(DEMO_APPLICATIONS_AS_API);
  const funnelStages = summary.stages.map(({ stage, count }) => ({
    label: stage.label,
    count,
    color: stage.color,
  }));

  return (
    <main data-theme="dark" className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-6xl px-6 pb-16">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="inline-flex min-h-11 items-center font-mono text-sm font-semibold text-strong"
            >
              job<span className="text-dim">_</span>tracker
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

        <div className="mt-8 space-y-4">
          <StatTiles summary={summary} />
          <ClassifierContext />
        </div>

        <section aria-labelledby="board-title" className="mt-10">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 id="board-title" className="label-mono">
              01 · pipeline
            </h2>
            <AddApplicationForm mode="demo" />
          </div>
          <StageFunnel
            stages={funnelStages}
            total={summary.total}
            caption={`pipeline distribution · ${summary.total} applications`}
            highlight={`${summary.advancedPct}% advanced past applied`}
          />
          <div className="mt-4">
            <PipelineBoard applications={DEMO_APPLICATIONS_AS_API} interactive={false} />
          </div>
          <div className="mt-4">
            <RecentActivity applications={DEMO_APPLICATIONS_AS_API} limit={5} />
          </div>
        </section>

        <section aria-labelledby="queue-title" className="mt-12">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="queue-title" className="label-mono">
              02 · decision trace — click an email to open its verdict
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
      </div>
    </main>
  );
}
