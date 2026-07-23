import Link from "next/link";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import type { GmailStatusResult } from "@/lib/gmail/server";

/**
 * The Gmail connection surface, server-rendered. Status is read from the
 * backend with the user's JWT; "Connect" links to the server-side authorize
 * route; "Disconnect" is a native form POST — no token ever reaches the
 * browser. Failure modes stay DISTINCT and honest (auth rejection vs. not
 * enabled vs. transient backend error), and every state routes forward (the
 * import fallback, the sample inbox) so the card is never a dead end.
 */
export function GmailConnectionCard({ result }: { result: GmailStatusResult }) {
  const connected = result.kind === "ok" && result.status.connected;
  const configured = result.kind === "ok" && result.status.configured;
  const email = result.kind === "ok" ? result.status.email : null;
  const needsSignin = result.kind === "unauthenticated" || result.kind === "auth";

  return (
    <div className="space-y-8">
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
              ) : result.kind === "auth" ? (
                <span className="text-dim">
                  Session couldn&apos;t be verified — sign in again (backend {result.status}).
                </span>
              ) : result.kind === "backend" ? (
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
            ) : needsSignin ? (
              <Link
                href="/login?redirect=/settings"
                className="rounded-lg bg-strong px-4 py-2 text-sm font-medium text-background hover:opacity-90"
              >
                Sign in
              </Link>
            ) : (
              <ConnectGmailButton configured={configured} />
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
        ) : (
          <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
            Not ready to connect? See exactly what the classifier does on a{" "}
            <Link href="/demo/inbox" className="text-strong underline-offset-4 hover:underline">
              sample inbox →
            </Link>
          </p>
        )}
      </div>

      {/* ---- No-connection path: import your own mail ----------------- */}
      {!connected ? (
        <div className="rounded-xl border border-line-soft bg-surface p-5">
          <h2 className="text-lg font-medium text-strong">Import your mail — no connection needed</h2>
          <p className="mt-1 text-sm text-muted">
            Don&apos;t want to connect an account (or waiting on a beta seat)? Export your mail from
            Google Takeout and classify it <span className="text-strong">on-device</span> — parsed and
            scored entirely in your browser, never uploaded.
          </p>
          <Link
            href="/import"
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            Open mail import <span aria-hidden>→</span>
          </Link>
        </div>
      ) : null}

      {/* ---- Beta access — invite-only direct Gmail connection -------- */}
      {!connected ? <BetaCard /> : null}

      {/* ---- How it works / why it's safe ----------------------------- */}
      <div className="space-y-3">
        <h3 className="label-mono">how the connection works — and why it&apos;s safe</h3>
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
    </div>
  );
}
