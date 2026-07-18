import Link from "next/link";

/**
 * Landing — the front door. Monochrome, hairline-ruled, every number
 * verified against the repo (182 tests; CI gate at macro-F1 ≥ 0.95;
 * 0.9791 measured on the v3 eval set; 3 layers; 9 stages).
 *
 * The hero doesn't describe the classifier — it runs one email through it, so
 * the first thing a visitor sees is the actual three-layer adjudication.
 */

type Layer = "rules" | "embeddings" | "setfit";

const LAYER_COLOR: Record<Layer, string> = {
  rules: "var(--viz-rules)",
  embeddings: "var(--viz-embeddings)",
  setfit: "var(--viz-setfit)",
};

function LayerDot({ layer, n }: { layer: Layer; n: number }) {
  return (
    <span
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] font-semibold"
      style={{ color: LAYER_COLOR[layer], border: `1px solid ${LAYER_COLOR[layer]}` }}
      aria-hidden
    >
      {n}
    </span>
  );
}

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
          three layers · gated at 0.95 macro-F1 · 0.979 measured
        </p>
        <h1 className="max-w-3xl text-balance text-5xl font-medium tracking-tight text-strong sm:text-6xl">
          Your inbox already holds the verdict.
          <span className="block text-muted">JobTracker extracts it.</span>
        </h1>
        <p className="mt-6 max-w-xl text-balance text-muted">
          Every pipeline signal — applied, interview, assessment, offer, rejection —
          is adjudicated by three models in series: regex rules strike first, e5
          embeddings arbitrate, SetFit renders the call. Below 0.85 confidence, it
          declines to guess and hands you the decision.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Link
            href="/demo"
            className="rounded-lg bg-strong px-5 py-2.5 font-medium text-background transition-transform hover:-translate-y-px"
          >
            Enter the live demo →
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

        {/* Signature: one real email, three layers. The product, not a pitch. */}
        <figure className="mt-16 w-full max-w-2xl overflow-hidden rounded-xl border border-line-soft bg-surface text-left">
          <figcaption className="flex items-center justify-between border-b border-line-soft px-5 py-3">
            <span className="label-mono">one email · three layers</span>
            <span className="font-mono text-[11px] text-dim">live logic · fixture data</span>
          </figcaption>

          <div className="px-5 py-5">
            <p className="rounded-lg border border-line-soft bg-background px-4 py-3 text-sm text-foreground">
              <span className="mr-2 font-mono text-[11px] uppercase tracking-widest text-dim">
                subject
              </span>
              “Unfortunately, we won’t be moving forward with your application.”
            </p>

            <ol className="mt-5 space-y-3">
              <li className="flex items-center gap-3">
                <LayerDot layer="rules" n={1} />
                <span className="w-28 shrink-0 font-mono text-xs text-muted">regex rules</span>
                <span className="text-sm text-dim">no high-precision rule — abstains ↓</span>
              </li>
              <li className="flex items-center gap-3">
                <LayerDot layer="embeddings" n={2} />
                <span className="w-28 shrink-0 font-mono text-xs text-muted">e5 embeddings</span>
                <span className="text-sm text-dim">
                  nearest class <span className="text-foreground">rejection</span> · sim{" "}
                  <span className="tabular font-mono">0.71</span> — narrows ↓
                </span>
              </li>
              <li className="flex items-center gap-3">
                <LayerDot layer="setfit" n={3} />
                <span className="w-28 shrink-0 font-mono text-xs text-muted">SetFit head</span>
                <span className="text-sm text-strong">
                  rejection · <span className="tabular font-mono">0.94</span> — decides ✓
                </span>
              </li>
            </ol>

            {/* Confidence against the 0.85 gate — the gate is not decoration. */}
            <div className="mt-6">
              <div className="relative h-1.5 w-full rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full"
                  style={{ width: "94%", background: "var(--viz-setfit)" }}
                />
                <div
                  className="absolute top-1/2 h-3.5 w-px -translate-y-1/2 bg-line-strong"
                  style={{ left: "85%" }}
                  aria-hidden
                />
              </div>
              <div className="mt-2 flex items-center justify-between font-mono text-[11px] text-dim">
                <span className="tabular text-muted">0.94 confidence</span>
                <span>gate 0.85 — below it, a human decides</span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-line-soft px-5 py-3">
            <span className="label-mono">verdict</span>
            <span
              className="font-mono text-sm font-semibold"
              style={{ color: "var(--viz-setfit)" }}
            >
              REJECTION → logged to pipeline
            </span>
          </div>
        </figure>

        <dl className="mt-10 grid w-full max-w-2xl grid-cols-2 overflow-hidden rounded-xl border border-line-soft bg-surface sm:grid-cols-4">
          {[
            ["macro-F1", "0.979 / gate 0.95"],
            ["layers", "rules → e5 → SetFit"],
            ["test suite", "182 passing"],
            ["email classes", "9 distinguished"],
          ].map(([k, v]) => (
            <div
              key={k}
              className="border-b border-r border-line-soft p-4 text-left last:border-r-0 sm:border-b-0"
            >
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
