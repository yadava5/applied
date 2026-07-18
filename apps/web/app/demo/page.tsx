import Link from "next/link";
import type { Metadata } from "next";
import { DEMO_APPLICATIONS, DEMO_STATS, type DemoStatus } from "@/lib/demo/demoData";
import { PipelineFunnel } from "@/components/viz/PipelineFunnel";
import { DecisionTrace } from "@/components/viz/DecisionTrace";

export const metadata: Metadata = {
  title: "Live demo — JobTracker",
  description:
    "The JobTracker pipeline board and classifier review queue, on fixture data. No inbox is read.",
};

const COLUMNS: { status: DemoStatus; label: string }[] = [
  { status: "applied", label: "applied" },
  { status: "interviewing", label: "interviewing" },
  { status: "offered", label: "offered" },
  { status: "rejected", label: "rejected" },
];

/**
 * The product, auth-free: the same board and review-queue UX the
 * signed-in app drives from the API, rendered from fixtures so a
 * visitor sees the pipeline in one click. Read-only by design.
 */
export default function DemoPage() {
  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-6 pb-16">
      <header className="flex h-14 items-center justify-between border-b border-line-soft">
        <div className="flex items-center gap-3">
          <Link href="/" className="font-mono text-sm font-semibold text-strong">
            job<span className="text-dim">_</span>tracker
          </Link>
          <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
            demo · fixture data · no inbox read
          </span>
        </div>
        <Link
          href="/"
          className="font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
        >
          ← landing
        </Link>
      </header>

      <dl className="mt-8 grid grid-cols-2 overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-4">
        {DEMO_STATS.map(([k, v]) => (
          <div
            key={k}
            className="border-b border-r border-line-soft p-4 last:border-r-0 sm:border-b-0"
          >
            <dt className="label-mono">{k}</dt>
            <dd className="tabular mt-1 font-mono text-lg font-semibold text-strong">{v}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="board-title" className="mt-10">
        <h2 id="board-title" className="label-mono mb-3">
          01 · pipeline
        </h2>
        <PipelineFunnel />
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {COLUMNS.map((col) => {
            const items = DEMO_APPLICATIONS.filter((a) => a.status === col.status);
            return (
              <div
                key={col.status}
                className="rounded-xl border border-line-soft bg-surface p-3"
              >
                <div className="mb-2 flex items-baseline justify-between px-1">
                  <span className="label-mono">{col.label}</span>
                  <span className="tabular font-mono text-xs text-muted">{items.length}</span>
                </div>
                <ul className="space-y-2">
                  {items.map((a) => (
                    <li
                      key={a.id}
                      className="rounded-lg border border-line-soft bg-surface-2 p-3 transition-colors hover:border-line-strong"
                    >
                      <p className="text-sm font-medium text-strong">{a.company}</p>
                      <p className="text-xs text-muted">{a.position}</p>
                      <p className="mt-2 truncate font-mono text-[11px] text-dim">
                        ✉ {a.lastSignal}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
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
      </section>
    </main>
  );
}
