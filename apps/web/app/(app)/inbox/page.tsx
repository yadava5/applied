import Link from "next/link";
import type { Metadata } from "next";

import { BetaCard } from "@/components/beta/BetaCard";
import { getGmailInbox, type InboxVerdict } from "@/lib/gmail/server";

export const metadata: Metadata = {
  title: "Classified inbox — JobTracker",
  description: "Recent Gmail messages, each with a classifier verdict.",
};

/**
 * The honest end of the pipeline: real recent messages from the connected
 * Gmail account, one classifier verdict each. Bodies are never fetched to
 * the client — the backend returns verdict metadata only. When Gmail isn't
 * connected (or the backend isn't reachable), the page says so and points
 * back to Settings rather than inventing rows.
 */

const CATEGORY_DOT: Record<string, string> = {
  offer: "bg-live",
  interview: "bg-live",
  assessment: "bg-live",
  applied: "bg-viz-embeddings",
  pending_application: "bg-viz-embeddings",
  follow_up: "bg-viz-rules",
  rejection: "bg-reject",
  needs_review: "bg-review",
  other: "bg-dim",
};

function VerdictRow({ v }: { v: InboxVerdict }) {
  const dot = CATEGORY_DOT[v.category] ?? "bg-dim";
  return (
    <li className="flex items-start justify-between gap-4 border-b border-line-soft px-1 py-3 last:border-b-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-strong">{v.subject}</p>
        <p className="truncate font-mono text-[11px] text-dim">
          {v.sender_name ? `${v.sender_name} · ` : ""}
          {v.sender_email}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3 text-right">
        <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
          {v.category}
        </span>
        <span className="tabular w-12 font-mono text-[11px] text-dim">
          {(v.confidence * 100).toFixed(0)}%
        </span>
        <span className="hidden w-16 font-mono text-[11px] text-dim sm:inline">{v.method}</span>
        {v.needs_review ? (
          <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-review">
            review
          </span>
        ) : (
          <span className="w-[52px]" aria-hidden />
        )}
      </div>
    </li>
  );
}

export default async function InboxPage() {
  const result = await getGmailInbox();

  if (result.kind === "not_connected") {
    return (
      <section className="mx-auto max-w-3xl space-y-6">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
          <p className="mt-1 text-sm text-muted">
            Gmail isn&apos;t connected yet. Connect it in{" "}
            <Link href="/settings" className="text-strong underline-offset-4 hover:underline">
              Settings
            </Link>{" "}
            and this page fills with real, classified mail.
          </p>
        </header>
        <BetaCard />
      </section>
    );
  }

  if (result.kind !== "ok") {
    return (
      <section className="mx-auto max-w-3xl space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
        <div
          role="status"
          className="rounded-xl border border-line-soft bg-surface p-4 font-mono text-sm text-muted"
        >
          {result.kind === "unauthenticated"
            ? "Sign in to view your classified inbox."
            : `The backend is unreachable — the inbox renders the moment it answers. (${result.message})`}
        </div>
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
          <p className="mt-1 font-mono text-xs text-dim">
            {result.scanned} recent message{result.scanned === 1 ? "" : "s"} · one verdict each
          </p>
        </div>
      </header>

      {result.verdicts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line-soft bg-surface p-8 text-center text-sm text-muted">
          No recent messages to classify.
        </div>
      ) : (
        <ul className="rounded-xl border border-line-soft bg-surface px-3">
          {result.verdicts.map((v) => (
            <VerdictRow key={v.message_id} v={v} />
          ))}
        </ul>
      )}

      <p className="font-mono text-[11px] leading-relaxed text-dim">{result.note}</p>
    </section>
  );
}
