import Link from "next/link";
import type { Metadata } from "next";

import { AppShell } from "@/components/shell/AppShell";
import { ImportMail } from "@/components/import/ImportMail";
import { Logo } from "@/components/brand/Logo";
import { getGmailStatus } from "@/lib/gmail/server";
import { userDisplayName } from "@/lib/supabase/auth";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = {
  title: "Import your mail",
  description:
    "Classify your own job-search mail with no Google connection and no sign-in. Your file is parsed and classified entirely in your browser — nothing is uploaded.",
};

/**
 * Auth-free, connection-free mail import. A visitor drops a Google Takeout
 * .mbox (or an .eml / JSON export) and sees it classified on-device by the
 * same layer-1 rules engine the sample inbox runs live. No OAuth, no server,
 * no upload — the privacy-preserving way to try the classifier on your OWN
 * mail.
 *
 * The route lives outside the `(app)` group so signed-out visitors can reach
 * it, but it is dual-mode:
 *   - Signed in  → rendered INSIDE the app shell (sidebar + sign-out), with
 *     "Import mail" active, so a user who arrives from the sidebar or an inbox/
 *     settings CTA is never stranded on a shell-less page with no way back.
 *   - Signed out → the standalone public page, which carries its own header
 *     and links so it, too, is never a dead end.
 *
 * Naming: signed in, the page prints NO title of its own — the rail and the
 * top bar both already say "Import mail", and a third copy in the window was
 * pure repetition (#198). An sr-only h1 keeps the document outline; the
 * visible title is the chrome's. Signed out there is no chrome, so that mode
 * keeps its visible h1 (pinned by import.spec.ts).
 */
export default async function ImportPage() {
  // Fired BEFORE the auth read, not after it: the probe resolves its own
  // token from the cookie jar (no network) and never throws, so nothing is
  // gained by serialising it behind `getUser` — and that serial chain (auth
  // round-trip, THEN backend round-trip) was this page's entire origin cost.
  // Signed out, the floating promise resolves to `unauthenticated` without
  // touching the network and is simply never awaited; `getGmailStatus`
  // returns labelled failures rather than rejecting, so it cannot become an
  // unhandled rejection (same contract the dashboard's floated review-queue
  // read relies on).
  const gmailPromise = getGmailStatus();
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // --- Signed in: keep the whole app shell around the import tool ----------
  if (user) {
    // The same GET the rail footer's probe makes in this render pass
    // (request-memoized fetch — same URL, same headers — so no second backend
    // call). The page must not claim a connection state the rail contradicts:
    // the old static subtitle said "no Gmail connection" beside a rail saying
    // "Gmail connected" (#198). Anything stateful here now derives from the
    // same probe the rail reads.
    const gmail = await gmailPromise;
    const gmailKnownDisconnected =
      gmail.kind === "ok" && !(gmail.status.configured && gmail.status.connected);

    return (
      <AppShell userEmail={user.email ?? null} userName={userDisplayName(user)}>
        {/* Centred BOTH ways. The signed-out branch below has always centred
            this same measure; this branch sat it on the left edge, so the two
            modes of the one page disagreed — that inconsistency was the #198
            layout defect, and its acceptance bar is "the drop zone is the
            visual centre of the page". `my-auto` centres the short pre-drop
            state in the scroll pane and degrades to normal top flow once
            results outgrow it.
            `relative` parents the sr-only h1 (a containing block, so the
            absolutely-positioned helper can never stretch the document). */}
        <div className="relative mx-auto my-auto w-full max-w-3xl space-y-8">
          <h1 className="sr-only">Import mail</h1>
          <ImportMail />
          {/* Rendered only on a POSITIVELY known disconnected state — shown to
              a connected user this is a second state contradiction, and on an
              unknown probe the rail's never-guess rule applies here too. */}
          {gmailKnownDisconnected ? (
            <p className="border-t border-line-soft pt-6 text-center text-xs leading-relaxed text-dim">
              Prefer to connect the source directly?{" "}
              <Link
                href="/settings"
                className="text-muted underline-offset-4 hover:text-strong hover:underline"
              >
                Connect Gmail read-only in Settings
              </Link>{" "}
              — invite-only while we&apos;re in beta.
            </p>
          ) : null}
        </div>
      </AppShell>
    );
  }

  // --- Signed out: the standalone public page ------------------------------
  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-6 pb-20">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
        {/* No mode pill here — it restated the on-device claim that now lives
            exactly once, in ImportMail's note; the h1 two lines down already
            names the page. */}
        <Link
          href="/"
          aria-label="Applied — home"
          className="brand-logo-link min-h-11 items-center text-strong"
        >
          <Logo className="h-6 w-auto" />
        </Link>
        <Link
          href="/demo/inbox"
          className="inline-flex min-h-11 items-center font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
        >
          sample inbox →
        </Link>
      </header>

      {/* h1 + one quiet line. The subtitle is verb-led — what the page DOES —
          because its old fragment form ("no Gmail connection · no sign-in")
          read as a status readout, and signed in it sat beside a rail footer
          asserting the opposite (#198). Signed out nothing contradicts it,
          but the same words should not mean "feature" here and "state" there. */}
      <section className="mt-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-strong">Import your mail</h1>
          <p className="mt-1 text-[13px] text-muted">
            Classify your own job-search mail without connecting Google or signing in.
          </p>
        </header>
      </section>

      <div className="mt-8">
        <ImportMail />
      </div>

      <p className="mt-10 text-center text-xs leading-relaxed text-dim">
        Prefer to connect the source directly?{" "}
        <Link href="/login?redirect=/settings" className="text-muted underline-offset-4 hover:text-strong hover:underline">
          Sign in and connect Gmail read-only
        </Link>{" "}
        — invite-only while we&apos;re in beta.
      </p>
    </main>
  );
}
