import Link from "next/link";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { LastSynced } from "@/components/gmail/LastSynced";
import { Disclosure } from "@/components/ui/Disclosure";
import type { GmailStatusResult } from "@/lib/gmail/server";

/**
 * The Gmail connection surface, server-rendered. Status is read from the
 * backend with the user's JWT; "Connect" links to the server-side authorize
 * route; "Disconnect" is a native form POST — no token ever reaches the
 * browser. Failure modes stay DISTINCT and honest (auth rejection vs. not
 * enabled vs. transient backend error), and every state routes forward (the
 * import fallback, the sample inbox) so the card is never a dead end.
 *
 * The card leads with the STATE and the one control; the safeguards brief and
 * the restricted-scope scale story still live here — they are the product's
 * honesty and they stay — but behind disclosures, because they are reference
 * material, not something to re-read on every visit. That cut is most of what
 * "too much text for the user to read" was reacting to on this page.
 *
 * A connected account also gets its sync state: when the board was last built,
 * whether the last attempt failed, and — only when a cursor actually exists —
 * that the next sync resumes from it. With `has_cursor` false the next sync is
 * a full scan, so nothing is claimed about it beyond the time.
 *
 * `demo` renders the same card on `/demo/settings` over a fixture status: the
 * disconnect POST would 401 without a session, so the control is disabled and
 * says why — a dead button with a reason beats a live one that lies.
 */

/** One safeguard, one line — the details element carries the paragraph. */
const SAFEGUARDS: [string, string][] = [
  [
    "Read-only",
    "Applied requests only the gmail.readonly scope. It can read messages to classify them — it cannot send, delete, or modify anything.",
  ],
  [
    "Standard OAuth",
    "Sign-in happens on Google's own consent screen. Applied never sees your Google password.",
  ],
  [
    "Encrypted at rest",
    "The refresh token is stored Fernet-encrypted, scoped to your account. It is never shown in the browser, never logged, and never placed in a URL.",
  ],
  [
    "Revocable anytime",
    "Disconnect here to revoke access at Google and delete the stored token. You can also remove it at myaccount.google.com/permissions.",
  ],
];

export function GmailConnectionCard({
  result,
  demo = false,
}: {
  result: GmailStatusResult;
  demo?: boolean;
}) {
  const status = result.kind === "ok" ? result.status : null;
  const connected = status?.connected === true;
  const configured = status?.configured === true;
  const email = status?.email ?? null;
  const needsSignin = !demo && (result.kind === "unauthenticated" || result.kind === "auth");

  // The one settings anchor that is not a <SettingsSection> (it is two cards
  // under one id), so it carries that component's scroll-mt itself:
  // `scroll-mt-16` below `lg` clears the chip strip SettingsNav pins there.
  return (
    <div id="gmail" className="scroll-mt-16 space-y-6 lg:scroll-mt-4">
      {/* ---- Gmail connection card ------------------------------------- */}
      <div className="rounded-xl border border-line-soft bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-medium text-strong">Gmail</h2>
            <p className="mt-1 text-sm text-muted">
              Read-only access so the classifier can read your job-search mail at the source.
            </p>

            <div className="mt-3 flex items-center gap-2 text-xs">
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

            {connected ? (
              <div className="mt-2 space-y-1 text-xs text-dim">
                <p>
                  {/* A sentence, so the product voice — the machine-readable
                      instant rides in the <time> element's dateTime/title.
                      This was one of the two "last synced …" mono defects. */}
                  <LastSynced at={status?.last_sync_at ?? null} className="text-xs" />
                  {status?.has_cursor ? (
                    <span> · next sync resumes from where that one stopped</span>
                  ) : null}
                </p>
                {status?.sync_status === "error" ? (
                  <p className="text-reject-ink">
                    The last sync attempt failed
                    {status.sync_error ? ` (${status.sync_error})` : ""} — the time above is the
                    last one that succeeded. Press Sync on the dashboard to retry.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 flex-col items-end gap-2">
            {connected ? (
              demo ? (
                <button
                  type="button"
                  disabled
                  title="Simulated account — there is no real connection to revoke."
                  className="cursor-not-allowed rounded-lg border border-line px-4 py-2 text-sm text-dim opacity-60"
                >
                  Disconnect
                </button>
              ) : (
                <form action="/api/gmail/disconnect" method="post">
                  <button
                    type="submit"
                    className="rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-reject/60 hover:text-strong"
                  >
                    Disconnect
                  </button>
                </form>
              )
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
            {/* STANDING, not folded — Google's API Services User Data Policy
                wants the privacy policy "prominently displayed" in the app.
                Until 2026-08 the only in-app path was inside the closed
                disclosure below, which is not prominent. It sits with the
                connect/disconnect control because that is the consent moment
                the policy is about. Do not move it back behind the fold. */}
            <Link
              href="/privacy"
              className="text-xs text-dim underline-offset-4 transition-colors hover:text-strong hover:underline"
            >
              privacy policy →
            </Link>
          </div>
        </div>

        <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
          {connected ? (
            <>
              Review what it has read in your{" "}
              <Link href="/inbox" className="text-strong underline-offset-4 hover:underline">
                filed mail →
              </Link>
            </>
          ) : (
            <>
              Not ready to connect? See exactly what the classifier does on a{" "}
              <Link href="/demo/inbox" className="text-strong underline-offset-4 hover:underline">
                sample inbox →
              </Link>
            </>
          )}
        </p>

        {/* ---- Reference material, foldered ------------------------------ */}
        <div className="mt-4 space-y-3">
          <Disclosure summary="How the connection works — and why it's safe">
            <ul className="grid gap-2 text-sm text-muted">
              {SAFEGUARDS.map(([k, v]) => (
                <li key={k} className="flex gap-2">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-live" aria-hidden />
                  <span>
                    <span className="text-strong">{k}.</span> {v}
                  </span>
                </li>
              ))}
            </ul>
            {/* The safeguards above are the short version. The page that owns
                the long one — every stored field, where it runs, how to delete
                it — is linked from the place a user decides to connect. */}
            <p className="mt-3 text-sm text-muted">
              The full account — every field Applied stores, where it runs, and how to delete it —
              is in the{" "}
              <Link href="/privacy" className="text-strong underline-offset-4 hover:underline">
                privacy policy →
              </Link>
            </p>
          </Disclosure>

          <Disclosure summary="A note on scale — the honest version">
            <p className="text-sm text-muted">
              <code className="text-strong">gmail.readonly</code> is a Google{" "}
              {/* The space is an explicit expression because a literal one does not survive the
                  build. Production rendered "restrictedscope"; building this file's own committed
                  source with our toolchain compiles the children to `restricted"}),"scope. Until`,
                  so the bundler drops the leading whitespace of this text node. The sibling
                  paragraph below keeps its space, and the difference is the entity: a JSX text node
                  containing &apos; loses its leading space, one without keeps it. This was the only
                  such node in the app — see the landing page, where `</span> int8-ONNX` and
                  `</span> to classify` both survive. Do not "simplify" this back to a plain space. */}
              <span className="text-strong">restricted</span>{" "}
              scope. Until this app completes Google&apos;s
              OAuth verification and an independent CASA security assessment, it can authorize at most{" "}
              <span className="text-strong">100 test users</span> added on the OAuth consent screen. So
              direct Gmail linking works, but is intentionally gated to invited testers.
            </p>
            <p className="text-sm text-muted">
              The path that scales to the public <span className="text-strong">without</span>{" "}
              restricted-scope verification is <span className="text-strong">forwarding ingestion</span>:
              you set a Gmail filter that auto-forwards job-related mail to a per-user Applied address,
              and the same classifier labels what arrives — no account access required. That is the
              recommended route for broad, public use; the direct OAuth connection above is the right
              fit for a small, invited group and for the desktop app.
            </p>
          </Disclosure>
        </div>
      </div>

      {/* ---- No-connection path: import your own mail ----------------- */}
      {!connected ? (
        <div className="rounded-xl border border-line-soft bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-base font-medium text-strong">
                Import your mail — no connection needed
              </h3>
              <p className="mt-1 text-sm text-muted">
                Drop a Google Takeout export and classify it{" "}
                <span className="text-strong">on-device</span> — never uploaded.
              </p>
            </div>
            <Link
              href="/import"
              className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
            >
              Open mail import <span aria-hidden>→</span>
            </Link>
          </div>
        </div>
      ) : null}

      {/* ---- Beta access — invite-only direct Gmail connection -------- */}
      {!connected ? <BetaCard /> : null}
    </div>
  );
}
