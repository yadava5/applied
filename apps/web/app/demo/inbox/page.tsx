import Link from "next/link";
import type { Metadata } from "next";

import { SampleInbox } from "@/components/demo/SampleInbox";
import { Logo } from "@/components/brand/Logo";

export const metadata: Metadata = {
  title: "Sample inbox",
  description:
    "See the Applied classifier's real verdicts on a set of sample job-search emails — no Google connection, no inbox read.",
};

/**
 * Public, auth-free "sample inbox". A demo visitor sees classification
 * end-to-end — verdicts, the 0.85 confidence gate, and the three-layer
 * decision trace — on synthetic emails carrying the REAL model's output
 * (precomputed offline by the shipped int8-ONNX pipeline; layer 1 also runs
 * live in the browser). This is the zero-connection twin of the signed-in
 * `/inbox`, which classifies the visitor's actual Gmail once connected.
 *
 * Pinned dark with the rest of the demo family. <main> carries the ground and
 * an inner div carries the measure, not the other way round: `data-theme` on a
 * `max-w-3xl` element would paint a dark column between the visitor's own
 * light gutters at desktop.
 */
export default function DemoInboxPage() {
  return (
    <main data-theme="dark" className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-3xl px-6 pb-20">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              aria-label="Applied — home"
              className="brand-logo-link min-h-11 items-center text-strong"
            >
              <Logo className="h-6 w-auto" />
            </Link>
            <span className="whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
              sample inbox · real verdicts · no inbox read
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
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Sample inbox</h1>
          <p className="max-w-2xl text-muted">
            Eleven realistic job-search emails, each run through the actual Applied classifier. Click
            any message to trace its path through the three layers and see where it lands against the
            0.85 auto-file gate.
          </p>
          <div
            role="note"
            className="rounded-xl border border-line-soft bg-surface px-4 py-3 text-sm text-muted"
          >
            <span className="text-strong">How these verdicts are produced.</span> The emails are
            synthetic — invented companies, no real mail is read. The verdicts are not: each is the exact
            output of the shipped 3-layer classifier (the same quantized int8 ONNX pipeline running on
            the{" "}
            <a
              href="https://huggingface.co/spaces/yadava5/jobtracker-classifier"
              target="_blank"
              rel="noreferrer"
              className="text-strong underline-offset-4 hover:underline"
            >
              Hugging Face Space ↗
            </a>
            ). Layers 2–3 (the 23 MB model) are precomputed offline; layer 1 (regex rules) is recomputed
            live in your browser below each trace. Nothing here is hand-tuned.
          </div>
        </section>

        <div className="mt-8">
          <SampleInbox />
        </div>

        <p className="mt-10 text-center text-xs leading-relaxed text-dim">
          Want this on your own mail?{" "}
          <Link href="/login" className="text-muted underline-offset-4 hover:text-strong hover:underline">
            Sign in
          </Link>{" "}
          and connect Gmail read-only — the same classifier labels your real inbox.
        </p>
      </div>
    </main>
  );
}
