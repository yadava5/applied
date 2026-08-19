import { Reveal } from "@/components/landing/Reveal";
import { BenchmarkFigure } from "./BenchmarkFigure";
import { NEW_TAB } from "./chrome";
import { ACCESS, DECISION, PRIVACY } from "./copy";

/**
 * The three shared content sections. Variants A and B compose them as a
 * quiet run below their board; variant C restages the same copy inside its
 * descent (`ClaimsDescent`) and then closes with the same `AccessSection`.
 * The copy itself lives in `copy.ts` — nothing here writes a claim.
 */

function SectionShell({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    // `scroll-mt` clears the sticky nav (h-14) plus a breath, so an anchored
    // arrival lands on the eyebrow rather than under the header.
    <section id={id} className="scroll-mt-20 border-t border-line-soft">
      <div className="mx-auto w-full max-w-5xl px-6 py-20 sm:py-24">{children}</div>
    </section>
  );
}

export function DecisionSection() {
  return (
    <SectionShell>
      <Reveal className="max-w-2xl">
        <p className="label-caps mb-4">{DECISION.eyebrow}</p>
        <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          {DECISION.headline}
        </h2>
        <p className="mt-5 text-muted">{DECISION.body}</p>
      </Reveal>
      <Reveal className="mt-10 grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr] lg:items-center">
        <BenchmarkFigure />
        <p className="max-w-md text-sm text-dim">{DECISION.gate}</p>
      </Reveal>
    </SectionShell>
  );
}

export function PrivacySection() {
  return (
    <SectionShell>
      <Reveal className="max-w-2xl">
        <p className="label-caps mb-4">{PRIVACY.eyebrow}</p>
        <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          {PRIVACY.headline}
        </h2>
        <p className="mt-5 text-muted">{PRIVACY.scope}</p>
        <p className="mt-4 text-muted">{PRIVACY.retention}</p>
        <p className="mt-4 text-muted">
          {PRIVACY.mechanism}{" "}
          <span className="break-all font-mono text-[0.8125rem] text-strong">{PRIVACY.testPath}</span>
        </p>
        <p className="mt-6 text-sm text-dim">
          {PRIVACY.systemCardLead}{" "}
          <a
            href="/system-card"
            {...NEW_TAB}
            className="text-muted underline underline-offset-4 transition-colors hover:text-strong"
          >
            {PRIVACY.systemCardLink}
          </a>{" "}
          — {PRIVACY.policyLead}{" "}
          <a
            href="/privacy"
            {...NEW_TAB}
            className="text-muted underline underline-offset-4 transition-colors hover:text-strong"
          >
            {PRIVACY.policyLink}
          </a>
          .
        </p>
      </Reveal>
    </SectionShell>
  );
}

/**
 * The seat cap, stated plainly — and then an action, because a cap alone is
 * a dead end. /import is public, uncapped, and the full rules pass on the
 * visitor's own exported mail: the cap becomes a privacy flex.
 *
 * This is the page's ONE conversion surface, which is why it carries the id
 * the nav's "Get access" anchors to (`ACCESS_ANCHOR`). Every variant renders
 * it exactly once, so the anchor cannot become ambiguous.
 *
 * `exhibit` is optional and OPT-IN, so this stays one section shared by three
 * variants rather than becoming three. Landing B passes a recording of the
 * import page doing what the CTA promises — the button's own evidence, beside
 * the button — because the fallback path was the one claim on the page with
 * nothing behind it. A and C pass nothing and are unchanged.
 */
export function AccessSection({ exhibit }: { exhibit?: React.ReactNode }) {
  return (
    <SectionShell id="access">
      <Reveal className="max-w-2xl">
        <p className="label-caps mb-4">{ACCESS.eyebrow}</p>
        <h2 className="text-balance text-3xl font-medium tracking-tight text-strong sm:text-4xl">
          {ACCESS.headline}
        </h2>
        <p className="mt-5 text-muted">{ACCESS.cap}</p>
        <p className="mt-4 text-muted">{ACCESS.noSeat}</p>
        <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
          <a
            href="/import"
            {...NEW_TAB}
            className="inline-flex min-h-11 items-center rounded-lg bg-strong px-5 py-2.5 font-medium text-background transition-opacity hover:opacity-90"
          >
            {ACCESS.cta} <span aria-hidden className="ml-2">→</span>
          </a>
          <span className="text-sm text-dim">
            {ACCESS.aside}{" "}
            <a
              href={`mailto:${ACCESS.contact}`}
              className="text-muted underline-offset-4 hover:text-strong hover:underline"
            >
              {ACCESS.contact}
            </a>
          </span>
        </div>
      </Reveal>
      {exhibit && <div className="mt-12">{exhibit}</div>}
    </SectionShell>
  );
}
