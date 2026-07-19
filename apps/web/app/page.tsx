import Link from "next/link";
import { DecisionTrace } from "@/components/viz/DecisionTrace";
import { Reveal } from "@/components/landing/Reveal";
import { RawInbox, ClassifiedInbox } from "@/components/landing/InboxScene";
import { Cascade } from "@/components/landing/Cascade";
import { ClassF1Bars } from "@/components/landing/ClassF1Bars";
import { AmbientField } from "@/components/landing/AmbientField";
import { CountUp } from "@/components/landing/CountUp";
import { ScrambleText } from "@/components/landing/ScrambleText";
import { MagneticLink } from "@/components/landing/MagneticLink";
import { SignatureEnding } from "@/components/landing/SignatureEnding";

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
    <main className="relative flex flex-col">
      {/* Motion is enhancement-only: with no JS, reveal everything up front. */}
      <noscript>
        <style>{`.reveal,.reveal-stagger>*,.bar-grow{opacity:1!important;transform:none!important}.bar-grow{width:var(--bar-w)!important}`}</style>
      </noscript>

      {/* App-native ambient field — fixed, low-alpha, behind the z-10 content. */}
      <AmbientField />

      <div className="relative z-10 flex flex-col">
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
          <MagneticLink
            href="/demo"
            className="rounded-lg bg-strong px-5 py-2.5 font-medium text-background shadow-[0_0_0_0_transparent] transition-shadow duration-300 hover:shadow-[0_10px_34px_-10px_rgba(255,255,255,0.3)]"
          >
            Enter the live demo <span aria-hidden>→</span>
          </MagneticLink>
          <a
            href={SYSTEM_CARD}
            className="spring-ease hover-lift rounded-lg border border-line px-5 py-2.5 text-foreground hover:border-line-strong hover:text-strong"
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
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
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
            <h2 className="text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              <ScrambleText text="Stop tracking. Start classifying." />
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
            <Link
              href="/demo/inbox"
              className="mt-5 inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-4 py-2.5 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
            >
              See it label a full sample inbox — real verdicts, no sign-in
              <span aria-hidden>→</span>
            </Link>
          </Reveal>
        </div>
      </section>

      {/* ---- 03 · HOW --------------------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>03 · how it works</Eyebrow>
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
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
                { k: "model", v: (<><CountUp end={22.8} decimals={1} /> MB int8 ONNX</>) },
                { k: "from", v: (<><CountUp end={90.4} decimals={1} /> MB float32 · ≈4×</>) },
                { k: "runtime", v: "Transformers.js · WASM" },
                { k: "privacy", v: "allowRemoteModels = false" },
              ].map(({ k, v }) => (
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
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
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
              <p className="tabular font-mono text-6xl font-semibold text-strong sm:text-7xl">
                <CountUp end={0.979} decimals={3} />
              </p>
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
              { id: "floor", v: <CountUp end={0.95} decimals={2} />, k: "macro-F1 CI floor — the merge fails below it" },
              { id: "tests", v: <CountUp end={182} />, k: "tests in the backend suite" },
              { id: "classes", v: <CountUp end={9} />, k: "email classes — 8 predicted + needs_review" },
              { id: "agree", v: (<><CountUp end={6} /> / 6</>), k: "output-agreement vs the Python pipeline" },
            ].map((s, i) => (
              <div
                key={s.id}
                className="rounded-xl border border-line-soft bg-surface p-4 transition-colors hover:border-line"
                style={{ ["--i" as string]: i }}
              >
                <p className="tabular font-mono text-2xl font-semibold text-strong">{s.v}</p>
                <p className="mt-1.5 text-[12px] leading-snug text-muted">{s.k}</p>
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

      {/* ---- 05 · PRIVACY ---------------------------------------------- */}
      {/* Every claim here is verified against the codebase:
       *   · no external LLM/model in the classify path — the only openai/anthropic
       *     strings in the repo are an employer domain→name lookup (tracking/extractor.py)
       *   · 3 layers — classifier/rules.py · classifier/embeddings.py (intfloat/e5-small-v2)
       *     · classifier/setfit_model.py (SetFitClassifier)
       *   · 22.8 MB int8 ONNX runs client-side — ml/browser/site/app.js sets
       *     env.allowRemoteModels = false; model_quantized.onnx = 22,843,695 B
       *   · gmail.readonly is the ONLY scope — email_clients/gmail.py SCOPES,
       *     config.py default. (Deliberately NOT claiming Fernet-at-rest or
       *     revoke-at-Google here — those paths aren't wired in the deployed cloud.) */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>05 · private by design</Eyebrow>
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              Your inbox stays yours.
            </h2>
            <p className="mt-5 text-muted">
              Most AI inbox tools work by sending your email to a large language model, where your
              private messages can become prompts, logs, or training data. JobTracker is built the
              other way around: the classifier is a small, purpose-built pipeline — not an LLM — and
              it can run entirely in your browser, so on that path your mail never leaves your
              machine.
            </p>
          </Reveal>

          <Reveal className="mt-10">
            <div className="privacy-card relative isolate overflow-hidden rounded-2xl border border-line-soft bg-surface p-5 sm:p-7">
              <div className="relative z-[1] grid gap-6 sm:grid-cols-3">
                {[
                  {
                    hue: "text-viz-rules",
                    k: "no large language model",
                    title: "No LLM reads your mail",
                    body: (
                      <>
                        Classification is three small layers — regex rules, a compact{" "}
                        <span className="text-strong">e5</span>{" "}embedding, and a fine-tuned{" "}
                        <span className="text-strong">SetFit</span>{" "}head. Nothing in that path calls
                        a third-party model or LLM API, so your email is never handed to one.
                      </>
                    ),
                  },
                  {
                    hue: "text-viz-embeddings",
                    k: "on your own cpu",
                    title: "It can run in your browser",
                    body: (
                      <>
                        The trained model compiles to a <span className="text-strong">22.8 MB</span>{" "}
                        int8-ONNX file that Transformers.js runs on your own CPU (
                        <span className="font-mono text-dim">allowRemoteModels = false</span>). Paste
                        text into the in-browser Space and it is classified on-device, never leaving
                        the tab.
                      </>
                    ),
                  },
                  {
                    hue: "text-viz-setfit",
                    k: "least privilege",
                    title: "Read-only, by construction",
                    body: (
                      <>
                        Connecting Gmail requests exactly one Google scope —{" "}
                        <span className="font-mono text-strong">gmail.readonly</span>. It can read
                        messages to classify them and <span className="text-strong">cannot</span>{" "}
                        send, delete, or modify anything; you authorize on Google&apos;s own consent
                        screen.
                      </>
                    ),
                  },
                ].map((p) => (
                  <div key={p.title} className="flex flex-col">
                    <p className={`label-mono inline-flex items-center gap-2 ${p.hue}`}>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden />
                      {p.k}
                    </p>
                    <h3 className="mt-3 text-base font-medium text-strong">{p.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted">{p.body}</p>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>

          <Reveal className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
            <Link
              href="/demo/inbox"
              className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-4 py-2.5 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
            >
              See it classify on-device <span aria-hidden>→</span>
            </Link>
            <span className="text-[12px] leading-relaxed text-dim">
              Connecting your own Gmail is invite-only while we&apos;re in beta.
            </span>
          </Reveal>
        </div>
      </section>

      {/* ---- 06 · TRY IT ------------------------------------------------ */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="max-w-2xl">
            <Eyebrow>06 · try it</Eyebrow>
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              Run a real email through all three layers.
            </h2>
          </Reveal>

          <Reveal stagger className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                href: "/demo",
                external: false,
                title: "Live demo",
                arrow: "→",
                body: "The pipeline board and decision trace, on fixture data. One click, no sign-in.",
              },
              {
                href: "/demo/inbox",
                external: false,
                title: "Sample inbox",
                arrow: "→",
                body: "Eleven job emails, the real classifier's verdicts, gate, and trace. No inbox read.",
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
                "group block rounded-xl border border-line bg-surface p-5 transition-colors duration-200 hover:border-line-strong hover:bg-surface-2";
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
          <p className="mx-auto mt-3 max-w-xl text-balance text-center text-[12px] leading-relaxed text-muted">
            Signed in, JobTracker connects your Gmail{" "}
            <span className="text-strong">read-only</span> to classify real mail — tokens encrypted,
            revocable anytime, nothing sent or deleted. Because{" "}
            <span className="font-mono text-dim">gmail.readonly</span> is a Google restricted scope,
            direct connection is limited to invited test users until verification; a{" "}
            <span className="text-strong">forwarding-address</span> option is the path to open,
            public scale.
          </p>
        </div>
      </section>

      {/* ---- 07 · SIGNATURE ENDING -------------------------------------- */}
      <section className="border-t border-line-soft">
        <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-28">
          <Reveal className="mx-auto max-w-2xl text-center">
            <Eyebrow>07 · one gesture</Eyebrow>
            <h2 className="title-focus text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
              One email. Three layers. One verdict.
            </h2>
            <p className="mt-5 text-muted">
              The whole system in a single gesture: an email falls through rules, e5, and SetFit,
              clears the 0.85 gate, and resolves into one filed outcome.
            </p>
          </Reveal>

          <Reveal className="mt-14">
            <SignatureEnding />
          </Reveal>
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
      </div>
    </main>
  );
}
