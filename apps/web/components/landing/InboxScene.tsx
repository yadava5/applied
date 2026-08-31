import type { CSSProperties } from "react";
import { Reveal } from "./Reveal";

/**
 * The Problem→Solution beat, told with one dataset shown twice.
 *
 * `RawInbox` is the inbox as it actually arrives: job verdicts interleaved with
 * a newsletter, every row unlabeled — you cannot tell status at a glance.
 * `ClassifiedInbox` is the exact same feed after the cascade reads it: each row
 * resolved to its category, the low-confidence one held back for a human. The
 * repeated rows are the argument — nothing was added, the signal was just made
 * legible. Categories are illustrative (they mirror the app's demo fixture),
 * not a benchmark.
 *
 * NAMING RULE FOR THESE ROWS (#638). Naming the CHANNEL is accurate and is the
 * point of the scene: `greenhouse.io` really is the relay this mail arrives
 * through, so it stays. Naming the EMPLOYER is fabrication — a row that puts a
 * real company's name on an invented subject line with an invented confidence
 * asserts, on a public page, that a specific company sent a specific verdict.
 * Every employer here is invented and shared with the app's own fixtures
 * (`lib/demo/demoData.ts`). Two rows used to name real companies and were
 * swapped in #638; `tests/unit/no-real-employer-in-shipped-fixtures.test.mjs`
 * is what stops the next one.
 */

type Row = {
  from: string;
  subject: string;
  cat: keyof typeof CAT;
  conf: number;
};

const CAT = {
  applied: { label: "applied", color: "var(--text-muted)" },
  interview: { label: "interview", color: "var(--viz-rules)" },
  assessment: { label: "assessment", color: "var(--viz-embeddings)" },
  offer: { label: "offer", color: "var(--green)" },
  rejection: { label: "rejection", color: "var(--red)" },
  other: { label: "other · filtered", color: "var(--text-dim)" },
  needs_review: { label: "human review", color: "var(--amber)" },
} as const;

const ROWS: Row[] = [
  { from: "no-reply@greenhouse.io", subject: "Update on your application to Northstar", cat: "rejection", conf: 0.94 },
  { from: "jobs@junipercloud.io", subject: "We received your application", cat: "applied", conf: 0.95 },
  { from: "talent@harbor.io", subject: "Take-home exercise — due in 48 hours", cat: "assessment", conf: 0.97 },
  { from: "digest@jobboard.com", subject: "12 new roles match your search", cat: "other", conf: 0.98 },
  { from: "recruiting@kestreldynamics.com", subject: "Next steps for your candidacy", cat: "interview", conf: 0.96 },
  { from: "maya@earlystage.xyz", subject: "Quick question about your background", cat: "needs_review", conf: 0.61 },
  { from: "people@beacon.io", subject: "We’d like to make you an offer", cat: "offer", conf: 0.99 },
];

function Sender({ from }: { from: string }) {
  return <span className="shrink-0 font-mono text-[11px] text-dim">{from}</span>;
}

/** The inbox as it lands: unlabeled, interleaved, indistinguishable. */
export function RawInbox() {
  return (
    <figure className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      <figcaption className="flex items-center justify-between border-b border-line-soft px-4 py-3">
        <span className="label-mono">inbox · unread</span>
        <span className="font-mono text-[11px] text-dim">every row hides a verdict</span>
      </figcaption>
      <ul className="divide-y divide-line-soft">
        {ROWS.map((row) => {
          // Easter egg: one row quietly resolves to its verdict on hover / focus
          // — the page's thesis ("your inbox already holds the verdict") made
          // literal on a single line. CSS-only, so RawInbox stays server-rendered.
          const isEgg = row.cat === "offer";
          if (isEgg) {
            return (
              <li
                key={row.subject}
                tabIndex={0}
                aria-label={`${row.subject} — hover to classify`}
                className="focus-inset group relative flex cursor-default items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2 focus-visible:bg-surface-2"
              >
                <span className="relative h-3 w-3 shrink-0" aria-hidden>
                  <span className="absolute inset-0 rounded-[3px] border border-line-strong transition-opacity duration-300 group-hover:opacity-0 group-focus-visible:opacity-0" />
                  <span
                    className="absolute inset-0 rounded-full opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus-visible:opacity-100"
                    style={{ background: "var(--green)", boxShadow: "0 0 10px -1px var(--green)" }}
                  />
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-muted transition-colors duration-300 group-hover:text-strong group-focus-visible:text-strong">
                  {row.subject}
                </span>
                <span className="hidden sm:block">
                  <Sender from={row.from} />
                </span>
                <span className="relative shrink-0">
                  <span className="block rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-dim transition-opacity duration-300 group-hover:opacity-0 group-focus-visible:opacity-0">
                    unclassified
                  </span>
                  <span
                    className="absolute inset-0 grid place-items-center rounded-full border font-mono text-[10px] uppercase tracking-wide opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus-visible:opacity-100"
                    style={{ color: "var(--green)", borderColor: "color-mix(in oklab, var(--green) 45%, transparent)" }}
                  >
                    offer
                  </span>
                </span>
              </li>
            );
          }
          return (
            <li key={row.subject} className="flex items-center gap-3 px-4 py-3">
              <span className="h-3 w-3 shrink-0 rounded-[3px] border border-line-strong" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm text-muted">{row.subject}</span>
              <span className="hidden sm:block">
                <Sender from={row.from} />
              </span>
              <span className="shrink-0 rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-dim">
                unclassified
              </span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

/** The same feed, read at the source: every row resolved to its category. */
export function ClassifiedInbox() {
  return (
    <figure className="overflow-hidden rounded-xl border border-line-soft bg-surface">
      <figcaption className="flex items-center justify-between border-b border-line-soft px-4 py-3">
        <span className="label-mono">inbox · classified</span>
        <span className="font-mono text-[11px] text-dim">same inbox · read at the source</span>
      </figcaption>
      <Reveal stagger>
        {ROWS.map((row, i) => {
          const meta = CAT[row.cat];
          const review = row.cat === "needs_review";
          return (
            <div
              key={row.subject}
              className="flex items-center gap-3 border-b border-line-soft px-4 py-3 last:border-b-0"
              style={{ "--i": i } as CSSProperties}
            >
              <span
                className="h-3 w-3 shrink-0 rounded-full"
                style={{ background: meta.color, boxShadow: `0 0 10px -2px ${meta.color}` }}
                aria-hidden
              />
              <span className="min-w-0 flex-1 truncate text-sm text-strong">{row.subject}</span>
              <span className="hidden sm:block">
                <Sender from={row.from} />
              </span>
              <span
                className="shrink-0 rounded-full border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide"
                style={{ color: meta.color, borderColor: `color-mix(in oklab, ${meta.color} 45%, transparent)` }}
              >
                {meta.label}
              </span>
              <span
                className="tabular w-10 shrink-0 text-right font-mono text-[11px]"
                style={{ color: review ? "var(--amber)" : "var(--green)" }}
              >
                {Math.round(row.conf * 100)}%
              </span>
            </div>
          );
        })}
      </Reveal>
    </figure>
  );
}
