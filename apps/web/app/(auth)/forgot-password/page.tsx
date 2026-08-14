"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { emailProblem, type CredentialField } from "@/lib/auth/credentials";
import { remainingCooldown, requestPasswordReset } from "@/lib/auth/recovery";
import { createClient } from "@/lib/supabase/client";

/**
 * "Reset your password" — step one: ask Supabase to email a recovery link.
 *
 * The page never learns whether the address belongs to an account, and that is
 * structural rather than careful: `requestPasswordReset` returns a value with
 * no field that could carry Supabase's answer (`lib/auth/recovery.ts`). What is
 * shown after a submit is one constant sentence, for every address.
 *
 * The link lands on `/reset-password/callback`, which exchanges the recovery
 * code for a session server-side and sends the browser on to `/reset-password`
 * with nothing left in the URL.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState<{
    field: CredentialField;
    message: string;
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  /** When the last link was requested — drives the resend cooldown. */
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const errorId = useId();
  const emailRef = useRef<HTMLInputElement>(null);

  // One tick a second, and only while a cooldown is actually running. The
  // effect subscribes and nothing more: `now` is seeded alongside `sentAt` in
  // the submit handler, because setting state synchronously in an effect body
  // is a cascading render (and `react-hooks/set-state-in-effect` rejects it).
  useEffect(() => {
    if (sentAt === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [sentAt]);

  const cooldown = sentAt === null ? 0 : remainingCooldown(sentAt, now);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || cooldown > 0) return;

    // Same shape check `/login` and `/signup` run before the network, from the
    // same module. It is identical for every address, so it says nothing about
    // whether one is registered — it only stops a typo costing a real request.
    const address = email.trim();
    const emailIssue = emailProblem(address);
    if (emailIssue) {
      setProblem(emailIssue);
      emailRef.current?.focus();
      return;
    }

    setProblem(null);
    setIsSubmitting(true);

    const supabase = createClient();
    const outcome = await requestPasswordReset(address, (recipient) =>
      supabase.auth.resetPasswordForEmail(recipient, {
        // Supabase appends the recovery `?code=` to this URL and will only
        // redirect here if the origin is on the project's Redirect URLs
        // allowlist (see DEPLOY.md → "URL Configuration").
        redirectTo: `${window.location.origin}/reset-password/callback`,
      }),
    );

    const sentNow = Date.now();
    setNotice(outcome.notice);
    setSentAt(sentNow);
    setNow(sentNow);
    setIsSubmitting(false);
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
      <div className="space-y-6">
        <header className="space-y-2">
          <Link href="/" aria-label="Applied — home" className="brand-logo-link mb-4 text-strong">
            <Logo className="h-7 w-auto" />
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            Reset your password
          </h1>
          <p className="text-sm text-muted">
            Enter your email and we’ll send you a link to set a new one.
          </p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-1">
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            {/* `required` / `type` stay as the declaration of intent even
                though `noValidate` makes them inert — they are the rules
                `emailProblem` mirrors, and they still describe the field to
                assistive tech. */}
            <input
              id="email"
              ref={emailRef}
              type="email"
              autoComplete="email"
              required
              aria-invalid={problem !== null}
              aria-describedby={problem ? errorId : undefined}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
            />
          </div>

          {problem ? (
            <p
              id={errorId}
              role="alert"
              className="rounded-md border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject-ink"
            >
              {problem.message}
            </p>
          ) : null}

          {notice ? (
            <p
              role="status"
              className="rounded-md border border-live/40 bg-live/10 px-3 py-2 text-sm text-live"
            >
              {notice}
            </p>
          ) : null}

          <Button
            type="submit"
            disabled={isSubmitting || cooldown > 0}
            className="w-full"
          >
            {isSubmitting
              ? "Sending…"
              : notice
                ? "Send another link"
                : "Send reset link"}
          </Button>

          {cooldown > 0 ? (
            <p className="text-xs text-dim">
              You can request another link in {cooldown} seconds.
            </p>
          ) : null}
        </form>

        {/* Shown to everyone, unconditionally: an account that only ever
            signed in with Google has no password to reset, and this is the
            sign-in side of that answer. Making it conditional would require
            knowing which identities the address has, which is precisely what
            this page must not reveal. */}
        <p className="text-sm text-muted">
          Signed up with Google? You have no password to reset — use{" "}
          <span className="text-strong">Continue with Google</span> on the
          sign-in page.
        </p>

        <p className="text-sm text-muted">
          Remembered it?{" "}
          <Link
            href="/login"
            className="text-strong underline underline-offset-4 hover:text-foreground"
          >
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
