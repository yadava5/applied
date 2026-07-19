import Link from "next/link";
import { DecisionTrace } from "@/components/viz/DecisionTrace";
import { Reveal } from "@/components/landing/Reveal";
import { RawInbox, ClassifiedInbox } from "@/components/landing/InboxScene";
import { Cascade } from "@/components/landing/Cascade";
import { ClassF1Bars } from "@/components/landing/ClassF1Bars";

/**
 * Landing — a narrative scroll: PROBLEM → SHIFT → HOW → PROOF → TRY IT.
 *
 * The story is JobTracker's own, told in its own dark-monochrome system with
 * the viz accents (cyan rules / violet e5 / green SetFit / amber gate). Every
 * number on this page is verified against the repo:
 *   · 201 regex rules      — classifier/rules.py (106 strong + 26 weak + 69 neg)
 *   · pretrained e5-small-v2 · fine-tuned SetFit (MiniLM-L6 body)
 *   · 0.85 confidence gate  — hybrid.py / DecisionTrace
 *   · 22.8 MB int8 ONNX     — model_quantized.onnx (22,843,695 B), from 90.4 MB
 *   · 0.9791 macro-F1       — baseline_hybrid_v3.json (acc 0.979, 2 misclassed)
 *   · CI floor 0.95         — backend-ci.yml (--min-macro-f1 0.95, ×2 gates)
 *   · 182 tests             — README.md · 9 classes (8 predicted + needs_review)
 *
 * Motion is progressive enhancement only (components/landing/Reveal.tsx + the
 * CSS in globals.css): it degrades to fully-visible under prefers-reduced-motion
 * and, via the <noscript> below, with JavaScript disabled.
 */

const SPACE_URL = "https://huggingface.co/spaces/yadava5/jobtracker-classifier";
const SYSTEM_CARD = "/system-card";

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="label-mono mb-4">{children}</p>;
}

export default function Landing() {
  return (
    <main className="flex flex-col">
      {/* Motion is enhancement-only: with no JS, reveal everything up front. */}
      <noscript>
        <style>{`.reveal,.reveal-stagger>*,.bar-grow{opacity:1!important;transform:none!important}.bar-grow{width:var(--bar-w)!important}`}</style>
      </noscript>

      {/* ---- nav -------------------------------------------------------- */}
      <header className="sticky top-0 z-50 border-b border-line-soft bg-background">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-6">
          <Link href="/" className="font-mono text-sm font-semibold text-strong">
            job<span className="text-dim">_</span>tracker
          </Link>
          <nav className="flex items-center gap-4">
            <a
              href={SYSTEM_CARD}
              className="hidden font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong sm:inline"
            >
              system card
            </a>
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
        </div>
      </header>

      {/* ---- hero ------------------------------------------------------- */}
      <section className="mx-auto flex w-full max-w-5xl flex-col items-center px-6 pt-20 pb-16 text-center sm:pt-28">
        <p className="mb-8 inline-flex items-center gap-2 rounded-full border border-line px-4 py-1.5 font-mono text-xs text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-live" aria-hidden />
          three layers · gated at 0.95 macro-F1 · 0.979 measured
        </p>
        <h1 className="max-w-3xl text-balance text-5xl font-medium tracking-tight text-strong sm:text-6xl">
          Your inbox already holds the verdict.
          <span className="block text-muted">JobTracker extracts it.</span>
        </h1>
        <p className="mt-6 max-w-xl text-balance text-muted">
          Every application ends as an email — applied, interview, assessment, offer, rejection. The
          outcome is already written down. A three-layer classifier reads it at the source, so the
          tracker fills itself.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Link
            href="/demo"
            className="rounded-lg bg-strong px-5 py-2.5 font-medium text-background transition-transform hover:-translate-y-px"
          >
            Enter the live demo →
          </Link>
          <a
            href={SYSTEM_CARD}
            className="rounded-lg border border-line px-5 py-2.5 text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            Read the System Card →
          </a>
        </div>
        <p className="mt-6 font-mono text-[11px] text-dim">
          runs in your browser · 22.8 MB · zero servers ·{" "}
          <a href={SPACE_URL} target="_blank" rel="noreferrer" className="text-muted underline-offset-4 hover:text-strong hover:underline">
            run the classifier ↗
          </a>
        </p>
        <div className="scroll-cue mt-16 font-mono text-[11px] text-dim" aria-hidden>
          ↓ scroll · the whole story
        </div>
      </section>

      {/* ---- 01 · PROBLEM ---------------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>01 · the problem</Eyebrow>
            <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              A job search lives in your inbox.
            </h2>
            <p className="mt-5 text-muted">
              Dozens of applications. Replies, rejections, assessments, an offer if you are lucky —
              all arriving unlabeled, interleaved with newsletters and receipts, across two accounts,
              faster than anyone keeps up with by hand.
            </p>
          </Reveal>

          <Reveal className="mt-10">
            <RawInbox />
          </Reveal>

          <Reveal className="mt-10 max-w-2xl">
            <p className="label-mono mb-4">manual tracking is lossy</p>
            <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
              {[
                "The assessment scrolls past — its 48-hour deadline passes unseen.",
                "“Did I hear back from them?” has no answer but a scroll.",
                "The row still says applied three weeks after they said no.",
                "Two accounts, one search — half the thread lives where you aren’t looking.",
              ].map((item) => (
                <li key={item} className="flex gap-2 text-sm text-muted">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-reject" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-6 text-sm text-dim">
              A manual tracker is only ever as fresh as your discipline. Classification never gets
              tired.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- 02 · SHIFT ------------------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>02 · the shift</Eyebrow>
            <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              Stop tracking. Start classifying.
            </h2>
            <p className="mt-5 text-muted">
              Tracking is bookkeeping — a symptom. The real task is classification: given an email,
              which job-search outcome is this, and how sure are we? Solve that at the source and the
              tracker maintains itself — applications link, statuses advance, and the pipeline is just
              a projection over labeled mail.
            </p>
          </Reveal>

          <Reveal className="mt-10 max-w-2xl border-l-2 border-line-strong pl-5">
            <p className="text-balance text-xl font-medium text-strong sm:text-2xl">
              “If you can label the email, you never have to track the application.”
            </p>
          </Reveal>

          <Reveal className="mt-10">
            <ClassifiedInbox />
            <p className="mt-3 font-mono text-[11px] leading-relaxed text-dim">
              The same seven emails — nothing added, the signal just made legible. The one it is not
              sure about, it refuses to guess on.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- 03 · HOW --------------------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>03 · how it works</Eyebrow>
            <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              Three layers in series, cheapest first.
            </h2>
            <p className="mt-5 text-muted">
              One email enters the top. Each layer tries to decide; clear its threshold and the
              cascade files and stops. Fall short and it drops to a smarter, costlier layer — and
              finally to a gate that would rather ask a human than guess.
            </p>
          </Reveal>

          <Reveal className="mt-10">
            <Cascade />
          </Reveal>

          {/* runs in your browser */}
          <Reveal className="mt-12 rounded-xl border border-line-soft bg-surface p-5 sm:p-7">
            <h3 className="text-xl font-medium tracking-tight text-strong sm:text-2xl">
              And the learned model runs in your browser.
            </h3>
            <p className="mt-4 max-w-2xl text-muted">
              The one trained model — the SetFit head — exports to int8 ONNX. 90.4 MB of float32
              weights quantize to <span className="text-strong">22.8 MB</span>; Transformers.js
              executes them in WebAssembly, on your own CPU. No inference server. No per-request cost.
              No data leaves the tab.
            </p>
            <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line-soft bg-line-soft sm:grid-cols-4">
              {[
                ["model", "22.8 MB int8 ONNX"],
                ["from", "90.4 MB float32 · ≈4×"],
                ["runtime", "Transformers.js · WASM"],
                ["privacy", "allowRemoteModels = false"],
              ].map(([k, v]) => (
                <div key={k} className="bg-surface p-3">
                  <dt className="label-mono">{k}</dt>
                  <dd className="tabular mt-1 font-mono text-[12px] font-semibold text-strong">{v}</dd>
                </div>
              ))}
            </dl>
          </Reveal>

          {/* the signature decision trace */}
          <Reveal className="mt-12">
            <h3 className="text-xl font-medium tracking-tight text-strong sm:text-2xl">
              Every verdict, traced.
            </h3>
            <p className="mt-4 mb-5 max-w-2xl text-muted">
              The signature view: each email’s path through the three layers and the gate. The layer
              that fired lights in its own hue; earlier layers passed it on, later ones were never
              needed. Click any row to open its adjudication.
            </p>
            <DecisionTrace />
            <p className="mt-3 font-mono text-[11px] text-dim">
              live logic · fixture data — no inbox is read.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- 04 · PROOF ------------------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>04 · the receipts</Eyebrow>
            <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              0.979 macro-F1 — and a gate that blocks merges.
            </h2>
            <p className="mt-5 text-muted">
              Macro-F1 averages the per-class F1 so no category hides behind the frequent ones. It is
              not a one-time screenshot: two GitHub Actions gates re-run the evaluation on every
              backend change and fail the build below 0.95. The number is load-bearing.
            </p>
          </Reveal>

          <div className="mt-10 grid gap-6 lg:grid-cols-[auto_1fr] lg:items-center">
            <Reveal className="rounded-xl border border-line-soft bg-surface px-8 py-7 text-center lg:text-left">
              <p className="tabular font-mono text-6xl font-semibold text-strong sm:text-7xl">0.979</p>
              <p className="mt-2 font-mono text-[11px] leading-relaxed text-dim">
                macro-F1 · hybrid classifier v3
                <br />
                accuracy 0.979 · two of the held-out emails misclassified
              </p>
            </Reveal>
            <ClassF1Bars />
          </div>

          <Reveal stagger className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["0.95", "macro-F1 CI floor — the merge fails below it"],
              ["182", "tests in the backend suite"],
              ["9", "email classes — 8 predicted + needs_review"],
              ["6 / 6", "output-agreement vs the Python pipeline"],
            ].map(([v, k], i) => (
              <div
                key={v}
                className="rounded-xl border border-line-soft bg-surface p-4"
                style={{ ["--i" as string]: i }}
              >
                <p className="tabular font-mono text-2xl font-semibold text-strong">{v}</p>
                <p className="mt-1.5 text-[12px] leading-snug text-muted">{k}</p>
              </div>
            ))}
          </Reveal>

          <Reveal className="mt-10 max-w-2xl border-l-2 border-line-strong pl-5">
            <p className="text-balance text-lg font-medium text-strong sm:text-xl">
              “A classifier that knows when to stop is worth more than one that is always sure.”
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- 05 · TRY IT ------------------------------------------------ */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>05 · try it</Eyebrow>
            <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              Run a real email through all three layers.
            </h2>
          </Reveal>

          <Reveal stagger className="mt-10 grid gap-3 sm:grid-cols-3">
            {[
              {
                href: "/demo",
                external: false,
                title: "Live demo",
                arrow: "→",
                body: "The pipeline board and decision trace, on fixture data. One click, no sign-in.",
              },
              {
                href: SPACE_URL,
                external: true,
                title: "In-browser classifier",
                arrow: "↗",
                body: "Paste your own text; it is classified client-side, on your CPU — nothing uploaded.",
              },
              {
                href: SYSTEM_CARD,
                external: false,
                title: "System Card",
                arrow: "→",
                body: "The full printed walkthrough: the why, the cascade, and the receipts.",
              },
            ].map((door, i) => {
              const inner = (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-base font-medium text-strong">{door.title}</span>
                    <span className="font-mono text-muted transition-transform group-hover:translate-x-0.5">
                      {door.arrow}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-muted">{door.body}</p>
                </>
              );
              const cls =
                "group block rounded-xl border border-line bg-surface p-5 transition-colors hover:border-line-strong";
              return door.external ? (
                <a
                  key={door.title}
                  href={door.href}
                  target="_blank"
                  rel="noreferrer"
                  className={cls}
                  style={{ ["--i" as string]: i }}
                >
                  {inner}
                </a>
              ) : (
                <Link key={door.title} href={door.href} className={cls} style={{ ["--i" as string]: i }}>
                  {inner}
                </Link>
              );
            })}
          </Reveal>

          <p className="mt-8 text-center font-mono text-[11px] text-dim">
            three layers · one gate · zero servers
          </p>
        </div>
      </section>

      {/* ---- footer ----------------------------------------------------- */}
      <footer className="border-t border-line-soft">
        <div className="mx-auto flex w-full max-w-5xl flex-col items-center justify-between gap-3 px-6 py-8 sm:flex-row">
          <span className="font-mono text-xs text-dim">
            demo runs on fixture data — no inbox is read · by Ayush Yadav
          </span>
          <nav className="flex items-center gap-4 font-mono text-[11px] text-dim">
            <a href={SYSTEM_CARD} className="transition-colors hover:text-strong">
              System Card
            </a>
            <Link href="/demo" className="transition-colors hover:text-strong">
              Live demo
            </Link>
            <a href={SPACE_URL} target="_blank" rel="noreferrer" className="transition-colors hover:text-strong">
              Classifier ↗
            </a>
          </nav>
        </div>
      </footer>
    </main>
  );
}
