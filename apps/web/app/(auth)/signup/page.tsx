"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setInfoMessage(null);
    setIsSubmitting(true);

    const supabase = createClient();
    const { data, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        // Supabase will email a confirmation link to this URL. The handler
        // at `app/(auth)/callback/route.ts` performs the PKCE code-exchange
        // and then redirects into the app.
        emailRedirectTo:
          typeof window !== "undefined"
            ? `${window.location.origin}/callback`
            : undefined,
      },
    });

    if (signUpError) {
      setError(signUpError.message);
      setIsSubmitting(false);
      return;
    }

    // When email confirmation is enabled on the Supabase project, `session`
    // is null until the user clicks the link. Surface a hint instead of
    // redirecting straight into the dashboard.
    if (!data.session) {
      setInfoMessage(
        "Check your email for a confirmation link to finish signing up.",
      );
      setIsSubmitting(false);
      return;
    }

    router.refresh();
    router.replace("/dashboard");
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
      <div className="space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            Create your JobTracker account
          </h1>
          <p className="text-sm text-muted">
            Track your job pipeline from one place.
          </p>
        </header>

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
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
            />
            <p className="text-xs text-dim">
              At least 8 characters.
            </p>
          </div>

          {error ? (
            <p
              role="alert"
              className="rounded-md border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject"
            >
              {error}
            </p>
          ) : null}

          {infoMessage ? (
            <p className="rounded-md border border-live/40 bg-live/10 px-3 py-2 text-sm text-live">
              {infoMessage}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <p className="text-sm text-muted">
          Already have an account?{" "}
          <Link href="/login" className="text-strong underline underline-offset-4 hover:text-foreground">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
