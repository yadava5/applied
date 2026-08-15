"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useId, useRef, useState, type FormEvent } from "react";

import {
  AuthOrDivider,
  GoogleSignInButton,
} from "@/components/auth/GoogleSignInButton";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { armBoot } from "@/lib/boot/flag";
import {
  LOGIN_MIN_PASSWORD,
  credentialProblem,
  type CredentialField,
} from "@/lib/auth/credentials";
import { createClient } from "@/lib/supabase/client";

/**
 * Humanise the `?error=` the `/callback` route forwards when a redirect-based
 * sign-in fails (a cancelled Google consent, a disabled provider reached via a
 * stale link, or a failed code-exchange). The raw values are Supabase/GoTrue
 * strings — map the ones users can actually cause to friendly copy and fall
 * back to a generic message rather than leaking internals.
 */
function humaniseAuthError(raw: string | null): string | null {
  if (!raw) return null;
  if (/access_denied|cancel/i.test(raw)) return "Sign-in was cancelled.";
  if (/provider is not enabled/i.test(raw))
    return "Google sign-in isn't configured yet.";
  return "Sign-in failed. Please try again.";
}

/**
 * `useSearchParams` forces the nearest Suspense boundary to bail out of
 * static rendering. Wrapping only the form that reads the query string
 * keeps the rest of the page (header, footer links) pre-renderable and
 * satisfies Next.js 16's strict CSR-bailout check during `next build`.
 */
export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
      <div className="space-y-6">
        <header className="space-y-2">
          <Link href="/" aria-label="Applied — home" className="brand-logo-link mb-4 text-strong">
            <Logo className="h-7 w-auto" />
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            Sign in to Applied
          </h1>
          <p className="text-sm text-muted">
            Enter your email and password to continue.
          </p>
        </header>

        <Suspense fallback={<LoginFormSkeleton />}>
          <LoginForm />
        </Suspense>

        <p className="text-sm text-muted">
          Don&apos;t have an account?{" "}
          <Link
            href="/signup"
            target="_blank"
            rel="noopener noreferrer"
            className="text-strong underline underline-offset-4 hover:text-foreground"
          >
            Sign up
          </Link>
        </p>
      </div>
    </main>
  );
}

function LoginFormSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-4 animate-pulse text-dim">
      <div className="h-9 rounded-md bg-surface-2" />
      <div className="h-9 rounded-md bg-surface-2" />
      <div className="h-9 rounded-md bg-surface-2" />
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirect") ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(() =>
    humaniseAuthError(searchParams.get("error")),
  );
  /**
   * `/reset-password` sends the browser here with `?reset=success` after
   * `updateUser({ password })` succeeded and every session was revoked. It is
   * a flag, not a message: nothing about the account, and nothing that came
   * back from Supabase, travels in the URL.
   */
  const justReset = searchParams.get("reset") === "success";
  /** Which field the current error is about — null for a server-side one. */
  const [invalidField, setInvalidField] = useState<CredentialField | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const errorId = useId();
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // The form owns its validation. `noValidate` is deliberate — the app
    // writes its own error copy rather than showing browser bubbles — so the
    // rules the markup declares (`required`, `type="email"`, `minLength`) are
    // re-asserted here, before the network. A submit the page can already see
    // is wrong must cost nothing: this one used to spend a real
    // POST /auth/v1/token, and say nothing until the server answered.
    const address = email.trim();
    const problem = credentialProblem(address, password, LOGIN_MIN_PASSWORD);
    if (problem) {
      setError(problem.message);
      setInvalidField(problem.field);
      (problem.field === "email" ? emailRef : passwordRef).current?.focus();
      return;
    }

    setError(null);
    setInvalidField(null);
    setIsSubmitting(true);

    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      // The trimmed address, which is what was validated — and what a native
      // email input would itself have submitted.
      email: address,
      password,
    });

    if (signInError) {
      setError(signInError.message);
      setIsSubmitting(false);
      return;
    }

    // Cover the app's first render with the Triage boot before the
    // navigation starts — the overlay lives in the root layout and survives
    // this client-side transition.
    armBoot(redirectTo.startsWith("/") ? redirectTo : "/dashboard");

    // `refresh()` is required so the proxy re-runs with the newly-set
    // session cookies before navigating into the protected area.
    router.refresh();
    router.replace(redirectTo);
  }

  return (
    <div className="space-y-4">
      {justReset ? (
        <p
          role="status"
          className="rounded-md border border-live/40 bg-live/10 px-3 py-2 text-sm text-live"
        >
          Your password has been changed. Sign in with your new one.
        </p>
      ) : null}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div className="space-y-1">
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          {/* `required` / `type` / `minLength` stay as the declaration of
              intent even though `noValidate` makes them inert — they are the
              rules `credentialProblem` mirrors, and they still describe the
              field to assistive tech. */}
          <input
            id="email"
            ref={emailRef}
            type="email"
            autoComplete="email"
            required
            aria-invalid={invalidField === "email"}
            aria-describedby={invalidField === "email" ? errorId : undefined}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
          />
        </div>

        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-3">
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-sm text-muted underline underline-offset-4 hover:text-strong"
            >
              Forgot your password?
            </Link>
          </div>
          <input
            id="password"
            ref={passwordRef}
            type="password"
            autoComplete="current-password"
            required
            minLength={LOGIN_MIN_PASSWORD}
            aria-invalid={invalidField === "password"}
            aria-describedby={invalidField === "password" ? errorId : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
          />
        </div>

        {error ? (
          <p
            id={errorId}
            role="alert"
            className="rounded-md border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject-ink"
          >
            {error}
          </p>
        ) : null}

        <Button type="submit" disabled={isSubmitting} className="w-full">
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <AuthOrDivider />

      <GoogleSignInButton redirectTo={redirectTo} />
    </div>
  );
}
