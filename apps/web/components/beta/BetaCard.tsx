import Link from "next/link";

import {
  BETA_CTA_LABEL,
  BETA_IMPORT_LABEL,
  BETA_MAILTO,
  BETA_SAMPLE_LABEL,
  BETA_SEATS,
  IMPORT_HREF,
  SAMPLE_INBOX_HREF,
} from "./constants";

/**
 * The rich beta-access notice. Lives where the decision actually happens:
 * the `/settings` Gmail-connect area and the not-connected `/inbox` state.
 * It carries the full, honest message — direct Gmail connection is invite-only
 * (Google's 100-test-user cap on the `gmail.readonly` restricted scope) — plus
 * the two real actions: email the admin for a seat, or try the zero-connection
 * sample inbox right now.
 *
 * A Server Component with no client island: all motion is CSS (the animated
 * beam border, glow, dot-ping and seat-panel sheen defined in globals.css) and
 * collapses to a static, fully legible state under `prefers-reduced-motion`.
 * The seat cap is rendered as a plain server-side number (not a count-up) so
 * the true "100" is always what shows — no hydration race can strand it at 0.
 */
export function BetaCard({ className = "" }: { className?: string }) {
  return (
    <aside
      data-beta="card"
      aria-labelledby="beta-card-title"
      className={`beta-card relative isolate overflow-hidden rounded-2xl border border-line-soft bg-surface p-5 sm:p-6 ${className}`.trim()}
    >
      <div className="relative z-[1] flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 sm:max-w-xl">
          <p className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-viz-rules">
            <span className="beta-dot" aria-hidden />
            Beta · under active development
          </p>

          <h2 id="beta-card-title" className="mt-3 text-lg font-medium text-strong">
            Connecting your own Gmail is invite-only right now.
          </h2>

          <p className="mt-2 text-sm leading-relaxed text-muted">
            JobTracker is in active development. Direct Gmail connection is limited to{" "}
            <span className="text-strong">100 beta testers</span>{" "}right now — that&apos;s the real
            Google OAuth test-user cap on the <code className="font-mono text-dim">gmail.readonly</code>{" "}
            scope — while we gather feedback. Want in? Email the admin to be added to the beta.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <a
              href={BETA_MAILTO}
              className="beta-cta inline-flex items-center gap-2 rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background outline-none transition-transform hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-viz-rules"
            >
              <span aria-hidden>✉</span>
              {BETA_CTA_LABEL}
            </a>
            <Link
              href={IMPORT_HREF}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-4 py-2 text-sm text-foreground outline-none transition-colors hover:border-line-strong hover:text-strong focus-visible:ring-2 focus-visible:ring-viz-rules"
            >
              {BETA_IMPORT_LABEL}
              <span aria-hidden>→</span>
            </Link>
            <Link
              href={SAMPLE_INBOX_HREF}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-4 py-2 text-sm text-foreground outline-none transition-colors hover:border-line-strong hover:text-strong focus-visible:ring-2 focus-visible:ring-viz-rules"
            >
              {BETA_SAMPLE_LABEL}
              <span aria-hidden>→</span>
            </Link>
          </div>

          <p className="mt-3 text-[12px] leading-relaxed text-dim">
            No seat, no wait — <span className="text-muted">import your own mail</span> and classify it
            on-device (nothing uploaded), or watch the classifier run on a synthetic sample inbox
            first.
          </p>
        </div>

        {/* Seat-cap motif — the honest "N / 100" is the *cap*, not occupancy. */}
        <div
          className="beta-seats shrink-0 self-stretch rounded-xl border border-line-soft bg-background/40 px-5 py-4 text-center sm:self-start"
          role="img"
          aria-label={`Beta access is capped at ${BETA_SEATS} testers — Google's OAuth test-user limit.`}
        >
          <p className="tabular font-mono text-4xl font-semibold leading-none text-strong" aria-hidden>
            {BETA_SEATS}
          </p>
          <p className="label-mono mt-2" aria-hidden>
            beta seats
          </p>
          <p className="mt-1 font-mono text-[10px] leading-tight text-dim" aria-hidden>
            Google OAuth
            <br />
            test-user cap
          </p>
        </div>
      </div>
    </aside>
  );
}
