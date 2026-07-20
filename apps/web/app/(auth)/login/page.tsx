"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import {
  AuthOrDivider,
  GoogleSignInButton,
} from "@/components/auth/GoogleSignInButton";
import { Button } from "@/components/ui/button";
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
          <h1 className="text-2xl font-semibold tracking-tight">
            Sign in to JobTracker
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
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (signInError) {
      setError(signInError.message);
      setIsSubmitting(false);
      return;
    }

    // `refresh()` is required so the proxy re-runs with the newly-set
    // session cookies before navigating into the protected area.
    router.refresh();
    router.replace(redirectTo);
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div className="space-y-1">
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="password" className="block text-sm font-medium">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            minLength={6}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
          />
        </div>

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject"
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
