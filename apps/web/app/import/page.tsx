import Link from "next/link";
import type { Metadata } from "next";

import { AppShell } from "@/components/shell/AppShell";
import { ImportMail } from "@/components/import/ImportMail";
import { Logo } from "@/components/brand/Logo";
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
 */
export default async function ImportPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const intro = (
    <div className="space-y-3">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Import your mail</h1>
        {/* Header voice shared by every tab: h1 + one quiet line of state. */}
        <p className="mt-1 text-[13px] text-muted">
          on-device · classified in your browser · nothing is uploaded
        </p>
      </header>
      <p className="max-w-2xl text-muted">
        Classify your own job-search mail without connecting Gmail and without signing in. Export
        your mail from <span className="text-strong">Google Takeout</span> (or drop a single{" "}
        <span className="font-mono text-dim">.eml</span>), and Applied runs the classifier on it
        right here in your browser. Nothing is uploaded — this is the same privacy guarantee as the
        rest of the app, made literal.
      </p>
    </div>
  );

  // --- Signed in: keep the whole app shell around the import tool ----------
  if (user) {
    return (
      <AppShell userEmail={user.email ?? null}>
        {/* Measure capped, but on the shell's shared left edge (no mx-auto). */}
        <div className="max-w-3xl space-y-8">
          {intro}
          <ImportMail />
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
        </div>
      </AppShell>
    );
  }

  // --- Signed out: the standalone public page ------------------------------
  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-6 pb-20">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-y-2 border-b border-line-soft py-2">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/"
            aria-label="Applied — home"
            className="brand-logo-link min-h-11 items-center text-strong"
          >
            <Logo className="h-6 w-auto" />
          </Link>
          <span className="whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted">
            import · on-device · no upload
          </span>
        </div>
        <Link
          href="/demo/inbox"
          className="inline-flex min-h-11 items-center font-mono text-xs uppercase tracking-widest text-muted transition-colors hover:text-strong"
        >
          sample inbox →
        </Link>
      </header>

      <section className="mt-8">{intro}</section>

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
