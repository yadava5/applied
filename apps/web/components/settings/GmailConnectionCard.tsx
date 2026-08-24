import Link from "next/link";

import { BetaCard } from "@/components/beta/BetaCard";
import { ConnectGmailButton } from "@/components/gmail/ConnectGmailButton";
import { DisconnectGmailButton } from "@/components/gmail/DisconnectGmailButton";
import { LastSynced } from "@/components/gmail/LastSynced";
import { Disclosure } from "@/components/ui/Disclosure";
import type { GmailStatusResult } from "@/lib/gmail/server";

/**
 * The Gmail connection surface, server-rendered. Status is read from the
 * backend with the user's JWT; "Connect" links to the server-side authorize
 * route; "Disconnect" is a native form POST — no token ever reaches the
 * browser — behind the centred confirmation dialog every sensitive Settings
 * action shares (#213, `DisconnectGmailButton`). Failure modes stay DISTINCT
 * and honest (auth rejection vs. not enabled vs. transient backend error),
 * and every state routes forward — the not-connected states through the
 * <BetaCard> below (email for a seat, or import your own mail on-device),
 * a connected one to its filed mail — so the card is never a dead end.
 *
 * The card leads with the STATE and the one control. The safeguards brief
 * that used to fold here moved into the privacy policy where it belongs
 * (#201) — the app stops re-arguing its own safety on a screen, and the
 * standing `privacy policy →` link beside the control is the way to the full
 * argument. What stays folded is the scale note below: a CAPABILITY limit
 * (who can connect today), which a user needs at the moment they press
 * Connect, not in a policy document.
 *
 * A connected account also gets its sync state: when the board was last built,
 * whether the last attempt failed, and — only when a cursor actually exists —
 * that the next sync resumes from it. With `has_cursor` false the next sync is
 * a full scan, so nothing is claimed about it beyond the time.
 *
 * `demo` renders the same card on `/demo/settings` over a fixture status: the
 * disconnect POST would 401 without a session, so the dialog's confirm is
 * disabled and says why — a dead button with a reason beats a live one that
 * lies.
 */

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
              <DisconnectGmailButton email={email} demo={demo} />
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

        {/* The not-connected arm of this line offered "See exactly what the
            classifier does on a sample inbox →" (/demo/inbox) until #495, and
            is deleted rather than gated behind `demo`: /demo/settings seeds
            `fixtureGmail()` with `connected: true`, so the twin renders the
            connected arm and never reached the other one — a `demo === true`
            guard would be dead code pretending to be a decision.

            Nothing replaces it. The whole <p> is conditional now rather than
            holding an empty fragment, because its `border-t` + `mt-4 pt-4`
            would otherwise draw a rule and a gap around nothing; and the
            not-connected state already routes forward through the <BetaCard>
            a few lines below, which carries the /import action. */}
        {connected ? (
          <p className="mt-4 border-t border-line-soft pt-4 text-sm text-muted">
            Review what it has read in your{" "}
            <Link href="/inbox" className="text-strong underline-offset-4 hover:underline">
              filed mail →
            </Link>
          </p>
        ) : null}

        {/* ---- Reference material, foldered ------------------------------
            One fold, not two: the safeguards brief moved to /privacy (#201).
            This one is a capability limit — who can connect today — which
            belongs at the moment a user decides to press Connect. */}
        <div className="mt-4 space-y-3">
          <Disclosure summary="Why connecting is invite-only right now">
            <p className="text-sm text-muted">
              <code className="text-strong">gmail.readonly</code> is a Google{" "}
              {/* The space is an explicit expression because a literal one does not survive the
                  build. Production rendered "restrictedscope"; building this file's own committed
                  source with our toolchain compiles the children to `restricted"}),"scope. Until`,
                  so the bundler drops the leading whitespace of this text node. A sibling text
                  node without an entity keeps its space — the difference is the entity: a JSX text
                  node containing &apos; loses its leading space, one without keeps it. This was the only
                  such node in the app — see the landing page, where `</span> int8-ONNX` and
                  `</span> to classify` both survive. Do not "simplify" this back to a plain space. */}
              <span className="text-strong">restricted</span>{" "}
              scope. Until this app completes Google&apos;s
              OAuth verification and an independent CASA security assessment, it can authorize at most{" "}
              <span className="text-strong">100 test users</span> added on the OAuth consent screen. So
              direct Gmail linking works, but is intentionally gated to invited testers.
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
                <span className="text-strong">on-device</span>.
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
