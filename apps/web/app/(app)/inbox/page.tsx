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
 * the client — the backend returns verdict metadata only.
 *
 * When Gmail isn't connected, the backend is unreachable, or the session was
 * rejected, the page says so PLAINLY and always offers a way forward — the
 * beta invite and the no-connection "Import your mail" fallback — rather than
 * a raw error, a stack, or a dead end.
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

function ImportFallback() {
  return (
    <div className="rounded-xl border border-line-soft bg-surface p-5">
      <h2 className="text-base font-medium text-strong">See it on your own mail — right now</h2>
      <p className="mt-1.5 text-sm text-muted">
        You don&apos;t have to wait for a beta seat. Export your mail from Google Takeout (or grab a
        single <span className="font-mono text-dim">.eml</span>) and classify it{" "}
        <span className="text-strong">entirely in your browser</span> — no upload, no OAuth.
      </p>
      <Link
        href="/import"
        className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
      >
        Import your mail <span aria-hidden>→</span>
      </Link>
    </div>
  );
}

function InboxShell({
  children,
  lede,
}: {
  children?: React.ReactNode;
  lede: React.ReactNode;
}) {
  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
        <p className="mt-1 text-sm text-muted">{lede}</p>
      </header>
      {children}
    </section>
  );
}

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

  // --- Signed out --------------------------------------------------------
  if (result.kind === "unauthenticated") {
    return (
      <InboxShell
        lede={
          <>
            Sign in to view your classified inbox — or{" "}
            <Link href="/import" className="text-strong underline-offset-4 hover:underline">
              import your mail
            </Link>{" "}
            with no sign-in.
          </>
        }
      >
        <ImportFallback />
      </InboxShell>
    );
  }

  // --- Connected, classified --------------------------------------------
  if (result.kind === "ok") {
    return (
      <section className="mx-auto max-w-3xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
            <p className="mt-1 font-mono text-xs text-dim">
              {result.scanned} recent message{result.scanned === 1 ? "" : "s"} · one verdict each
            </p>
          </div>
          <Link
            href="/import"
            className="font-mono text-[11px] text-dim underline-offset-4 hover:text-strong hover:underline"
          >
            import a file instead →
          </Link>
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

  // --- Not connected -----------------------------------------------------
  if (result.kind === "not_connected") {
    return (
      <InboxShell
        lede={
          <>
            Gmail isn&apos;t connected yet. Connect it in{" "}
            <Link href="/settings" className="text-strong underline-offset-4 hover:underline">
              Settings
            </Link>{" "}
            and this page fills with real, classified mail.
          </>
        }
      >
        <BetaCard />
        <ImportFallback />
      </InboxShell>
    );
  }

  // --- Honest failure states (never a raw error) -------------------------
  const lede =
    result.kind === "auth" ? (
      <>Your session couldn&apos;t be verified for the mail backend. Signing in again usually fixes it.</>
    ) : result.kind === "unavailable" ? (
      <>The Gmail connection isn&apos;t enabled on this deployment yet.</>
    ) : (
      <>The mail backend is temporarily unavailable — this page fills in the moment it answers.</>
    );

  return (
    <InboxShell lede={lede}>
      {result.kind === "auth" ? (
        <div className="rounded-xl border border-line-soft bg-surface p-5">
          <Link
            href="/login?redirect=/inbox"
            className="inline-flex items-center gap-2 rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background hover:opacity-90"
          >
            Sign in again <span aria-hidden>→</span>
          </Link>
          <p className="mt-3 font-mono text-[11px] text-dim">
            reference: backend responded {result.status}
          </p>
        </div>
      ) : null}
      <ImportFallback />
    </InboxShell>
  );
}
