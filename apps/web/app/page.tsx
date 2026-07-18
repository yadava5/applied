import Link from "next/link";

/**
 * Landing — the front door. Monochrome, hairline-ruled, every number
 * verified against the repo (182 tests; CI gate at macro-F1 ≥ 0.95;
 * 0.9791 measured on the v3 eval set; 3 layers; 9 stages).
 */
export default function Landing() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6">
      <header className="flex h-14 items-center justify-between border-b border-line-soft">
        <span className="font-mono text-sm font-semibold text-strong">
          job<span className="text-dim">_</span>tracker
        </span>
        <nav className="flex items-center gap-3">
          <Link
            href="/demo"
            className="font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
          >
            live demo
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            Sign in
          </Link>
        </nav>
      </header>

      <section className="flex flex-1 flex-col items-center justify-center py-24 text-center">
        <p className="mb-8 inline-flex items-center gap-2 rounded-full border border-line px-4 py-1.5 font-mono text-xs text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          3-layer classifier — CI-gated at 0.95 macro-F1, 0.979 measured
        </p>
        <h1 className="max-w-3xl text-balance text-5xl font-medium tracking-tight text-strong sm:text-6xl">
          Your inbox already holds the verdict.
          <span className="block text-muted">JobTracker extracts it.</span>
        </h1>
        <p className="mt-6 max-w-xl text-balance text-muted">
          Every pipeline signal — applied, interview, assessment, offer, rejection — is
          adjudicated by a three-layer classifier: regex rules strike first, e5 embeddings
          arbitrate, SetFit renders the final call. Below 0.85 confidence, a human presides.
        </p>
        <div className="mt-9 flex gap-3">
          <Link
            href="/demo"
            className="rounded-lg bg-strong px-5 py-2.5 font-medium text-background transition-transform hover:-translate-y-px"
          >
            Enter the live demo ↓
          </Link>
          <a
            href="https://huggingface.co/spaces/yadava5/jobtracker-classifier"
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-line px-5 py-2.5 text-foreground transition-colors hover:border-line-strong"
          >
            Run the classifier in your browser ↗
          </a>
        </div>

        <dl className="mt-16 grid w-full max-w-3xl grid-cols-2 overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-4">
          {[
            ["macro-F1", "0.979 / gate 0.95"],
            ["layers", "rules → e5 → SetFit"],
            ["test suite", "182 passing"],
            ["email classes", "9 distinguished"],
          ].map(([k, v]) => (
            <div key={k} className="border-b border-r border-line-soft p-4 text-left last:border-r-0 sm:border-b-0">
              <dt className="label-mono">{k}</dt>
              <dd className="tabular mt-1 font-mono text-sm font-semibold text-strong">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <footer className="border-t border-line-soft py-6 text-center font-mono text-xs text-dim">
        demo runs on fixture data — no inbox is read · by Ayush Yadav
      </footer>
    </main>
  );
}
