import Link from "next/link";
import type { Metadata } from "next";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { InboxWorkbench } from "@/components/gmail/InboxWorkbench";
import { getGmailStatus } from "@/lib/gmail/server";

export const metadata: Metadata = {
  title: "Classified inbox",
  description: "Mine your Gmail for your real job-search pipeline, one classifier verdict per message.",
};

/**
 * The honest end of the pipeline: real mail from the connected Gmail account,
 * one classifier verdict each. The server render only resolves the *connection*
 * state (cheap `/auth/gmail/status`); the actual high-volume, filterable mine
 * runs in the client {@link InboxWorkbench}, which pages the backend and shows
 * the pipeline (category summary + follow-up flags). Bodies are never fetched.
 *
 * Every non-connected path says so plainly and offers a way forward — connect,
 * the beta invite, or the no-OAuth import fallback — never a raw error.
 */

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
  // Measure capped for readability, but aligned to the shell's shared left
  // edge (no `mx-auto`): every authed page starts at the same x.
  return (
    <section className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
        <p className="mt-1 text-sm text-muted">{lede}</p>
      </header>
      {children}
    </section>
  );
}

export default async function InboxPage() {
  const result = await getGmailStatus();

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

  // --- Backend answered: branch on configured / connected ----------------
  if (result.kind === "ok") {
    const { configured, connected, email } = result.status;

    if (configured && connected) {
      // The connected inbox is a data surface: it spans the shell's full
      // column like the dashboard board does (the capped reading measure is
      // for the prose/CTA states below). Header voice matches every tab —
      // h1 + one mono line of state.
      return (
        <section className="space-y-6">
          <header>
            <h1 className="text-2xl font-semibold tracking-tight text-strong">Classified inbox</h1>
            <p className="mt-1 font-mono text-xs text-dim">
              read-only mine · one verdict per message · unanswered applications get flagged
            </p>
          </header>
          <InboxWorkbench email={email} />
        </section>
      );
    }

    if (configured && !connected) {
      return (
        <InboxShell
          lede={
            <>
              This is where your real, classified mail lands. Connect Gmail read-only and it fills with
              live verdicts — or preview the classifier first, no connection needed.
            </>
          }
        >
          <div className="rounded-xl border border-line-soft bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-base font-medium text-strong">Connect Gmail to fill this inbox</h2>
                <p className="mt-1.5 text-sm text-muted">
                  Read-only, on Google&apos;s own consent screen. The classifier reads your job-search
                  mail to label it — it <span className="text-strong">cannot</span> send, delete, or
                  modify anything.
                </p>
              </div>
              <ConnectGmailButton className="shrink-0" />
            </div>
            <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
              Want the full breakdown of scopes and safeguards first? See{" "}
              <Link href="/settings" className="text-strong underline-offset-4 hover:underline">
                Settings
              </Link>
              .
            </p>
          </div>
          <BetaCard />
          <ImportFallback />
        </InboxShell>
      );
    }

    // Backend reachable but Gmail not configured on this deploy.
    return (
      <InboxShell lede={<>The Gmail connection isn&apos;t enabled on this deployment yet.</>}>
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
