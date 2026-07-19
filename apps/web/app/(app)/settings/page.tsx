import Link from "next/link";
import type { Metadata } from "next";

import { getGmailStatus } from "@/lib/gmail/server";

export const metadata: Metadata = {
  title: "Settings — JobTracker",
  description: "Connect Gmail so JobTracker can read and classify your job-search mail.",
};

/**
 * The real "Connect Gmail" surface. Everything here is server-rendered:
 * the status is read from the backend with the user's JWT, "Connect" is a
 * link to the server-side authorize route, and "Disconnect" is a native
 * form POST. No token ever reaches the browser.
 *
 * When the backend has not yet been given its Google OAuth credentials (or
 * is unreachable), the page says so plainly instead of pretending to be
 * connected.
 */

const FLAG_BANNERS: Record<string, { tone: "ok" | "warn" | "error"; text: string }> = {
  connected: { tone: "ok", text: "Gmail connected. JobTracker can now read and classify your job-search mail." },
  disconnected: { tone: "ok", text: "Gmail disconnected and access revoked at Google." },
  error: { tone: "error", text: "Something went wrong with the Gmail connection. Please try again." },
  unavailable: {
    tone: "warn",
    text: "Gmail connection isn't enabled on this deployment yet — see the note below.",
  },
};

const TONE_CLASS: Record<"ok" | "warn" | "error", string> = {
  ok: "border-live/40 text-strong",
  warn: "border-line-strong text-muted",
  error: "border-reject/50 text-strong",
};

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ gmail?: string }>;
}) {
  const { gmail: flag } = await searchParams;
  const banner = flag ? FLAG_BANNERS[flag] : undefined;
  const result = await getGmailStatus();

  const connected = result.kind === "ok" && result.status.connected;
  const configured = result.kind === "ok" && result.status.configured;
  const email = result.kind === "ok" ? result.status.email : null;

  return (
    <section className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Settings</h1>
        <p className="mt-1 font-mono text-xs text-dim">Connect the inbox that feeds the tracker.</p>
      </header>

      {banner ? (
        <div
          role="status"
          className={`rounded-xl border bg-surface px-4 py-3 text-sm ${TONE_CLASS[banner.tone]}`}
        >
          {banner.text}
        </div>
      ) : null}

      {/* ---- Gmail connection card ------------------------------------- */}
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-medium text-strong">Gmail</h2>
            <p className="mt-1 text-sm text-muted">
              Read-only access so the classifier can read your job-search mail at the source.
            </p>

            <div className="mt-3 flex items-center gap-2 font-mono text-xs">
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-live" : "bg-dim"}`}
                aria-hidden
              />
              {result.kind === "unauthenticated" ? (
                <span className="text-dim">Sign in to manage Gmail.</span>
              ) : result.kind === "unavailable" ? (
                <span className="text-dim">
                  Backend unreachable — connection status unavailable ({result.message}).
                </span>
              ) : connected ? (
                <span className="text-strong">Connected{email ? ` · ${email}` : ""}</span>
              ) : configured ? (
                <span className="text-muted">Not connected</span>
              ) : (
                <span className="text-muted">Not enabled on this deployment yet</span>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {connected ? (
              <form action="/api/gmail/disconnect" method="post">
                <button
                  type="submit"
                  className="rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-reject/60 hover:text-strong"
                >
                  Disconnect
                </button>
              </form>
            ) : (
              <a
                href="/api/gmail/authorize"
                className={`rounded-lg px-4 py-2 text-sm font-medium ${
                  configured
                    ? "bg-strong text-background hover:opacity-90"
                    : "pointer-events-none border border-line text-dim opacity-60"
                }`}
                aria-disabled={!configured}
              >
                Connect Gmail
              </a>
            )}
          </div>
        </div>

        {connected ? (
          <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
            View the classified result in your{" "}
            <Link href="/inbox" className="text-strong underline-offset-4 hover:underline">
              classified inbox →
            </Link>
          </p>
        ) : null}
      </div>

      {/* ---- How it works / why it's safe ----------------------------- */}
      <div className="space-y-3">
        <h3 className="label-mono">how the connection works — and why it's safe</h3>
        <ul className="grid gap-2 text-sm text-muted">
          {[
            ["Read-only", "JobTracker requests only the gmail.readonly scope. It can read messages to classify them — it cannot send, delete, or modify anything."],
            ["Standard OAuth", "Sign-in happens on Google's own consent screen. JobTracker never sees your Google password."],
            ["Encrypted at rest", "The refresh token is stored Fernet-encrypted, scoped to your account. It is never shown in the browser, never logged, and never placed in a URL."],
            ["Revocable anytime", "Disconnect here to revoke access at Google and delete the stored token. You can also remove it at myaccount.google.com/permissions."],
          ].map(([k, v]) => (
            <li key={k} className="flex gap-2">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-live" aria-hidden />
              <span>
                <span className="text-strong">{k}.</span> {v}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* ---- Honest scale story --------------------------------------- */}
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <h3 className="label-mono mb-3">a note on scale — the honest version</h3>
        <p className="text-sm text-muted">
          <code className="text-strong">gmail.readonly</code> is a Google{" "}
          <span className="text-strong">restricted</span> scope. Until this app completes Google&apos;s
          OAuth verification and an independent CASA security assessment, it can authorize at most{" "}
          <span className="text-strong">100 test users</span> added on the OAuth consent screen. So
          direct Gmail linking works, but is intentionally gated to invited testers.
        </p>
        <p className="mt-3 text-sm text-muted">
          The path that scales to the public <span className="text-strong">without</span> restricted-scope
          verification is <span className="text-strong">forwarding ingestion</span>: you set a Gmail
          filter that auto-forwards job-related mail to a per-user JobTracker address, and the same
          classifier labels what arrives — no account access required. That is the recommended route
          for broad, public use; the direct OAuth connection above is the right fit for a small,
          invited group and for the desktop app.
        </p>
      </div>
    </section>
  );
}
