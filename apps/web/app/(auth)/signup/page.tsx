"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";

import { AuthHeader } from "@/components/auth/AuthHeader";
import {
  AuthOrDivider,
  GoogleSignInButton,
} from "@/components/auth/GoogleSignInButton";
import { Button } from "@/components/ui/button";
import {
  SIGNUP_MIN_PASSWORD,
  credentialProblem,
  type CredentialField,
} from "@/lib/auth/credentials";
import { createClient } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  /** Which field the current error is about — null for a server-side one. */
  const [invalidField, setInvalidField] = useState<CredentialField | null>(
    null,
  );
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const errorId = useId();
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setInfoMessage(null);

    // The form sets `noValidate` — deliberately, so the app owns its error
    // copy — which also disables `required`, `type="email"` and `minLength`.
    // Every one of those rules is re-asserted here, before the network, by the
    // same predicate `/login` runs (`lib/auth/credentials.ts`). The password
    // floor was already checked by hand; the EMAIL was not, so a malformed
    // address still cost a real POST /auth/v1/signup. Supabase's own floor is
    // 6 characters, so without SIGNUP_MIN_PASSWORD the product would accept a
    // shorter password than the hint below promises (JT-2).
    const address = email.trim();
    const problem = credentialProblem(address, password, SIGNUP_MIN_PASSWORD);
    if (problem) {
      setError(problem.message);
      setInvalidField(problem.field);
      (problem.field === "email" ? emailRef : passwordRef).current?.focus();
      return;
    }

    setInvalidField(null);
    setIsSubmitting(true);

    // The name is OPTIONAL and therefore has no problem to report: it is not
    // part of `credentialProblem`, has no `required`, and can never focus the
    // alert region. Blank is a legitimate answer — `userDisplayName` falls
    // through to the email.
    const displayName = name.trim();

    const supabase = createClient();
    const { data, error: signUpError } = await supabase.auth.signUp({
      // The trimmed address, which is what was validated — and what a native
      // email input would itself have submitted.
      email: address,
      password,
      options: {
        // Supabase will email a confirmation link to this URL. The handler
        // at `app/(auth)/callback/route.ts` performs the PKCE code-exchange
        // and then redirects into the app.
        emailRedirectTo:
          typeof window !== "undefined"
            ? `${window.location.origin}/callback`
            : undefined,
        // `options.data` becomes the new user's `user_metadata`, which is the
        // same store Settings → Profile writes and `userDisplayName` reads —
        // no table, no migration, no API route. The key is OMITTED rather
        // than written as "" when the field is blank: `userDisplayName`
        // already treats "" as unset, so an empty string would only be a
        // second spelling of absent sitting in the user's metadata.
        ...(displayName ? { data: { display_name: displayName } } : {}),
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
    <div className="space-y-6">
      <AuthHeader
        title="Welcome to Applied."
        intro="Every application, and the reply it's waiting on, on one board."
      />

      <div className="space-y-4">
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-1">
            <label htmlFor="name" className="block text-sm font-medium">
              Name <span className="text-dim">(optional)</span>
            </label>
            {/* No `required`, no `aria-invalid`, no ref: this field has no
                  error state to point at, so there is nothing for the alert
                  region to say and nothing to focus. `maxLength` mirrors the
                  cap Settings → Profile puts on the same value. */}
            <input
              id="name"
              type="text"
              autoComplete="name"
              maxLength={80}
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
            />
            <p className="text-xs text-dim">
              What Applied should call you — saved straight to your profile.
            </p>
          </div>

          <div className="space-y-1">
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            {/* `required` / `type` / `minLength` stay as the declaration of
                  intent even though `noValidate` makes them inert — they are
                  the rules `credentialProblem` mirrors, and they still
                  describe the field to assistive tech. */}
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
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              ref={passwordRef}
              type="password"
              autoComplete="new-password"
              required
              minLength={SIGNUP_MIN_PASSWORD}
              aria-invalid={invalidField === "password"}
              aria-describedby={
                invalidField === "password" ? errorId : undefined
              }
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
            />
            <p className="text-xs text-dim">
              At least {SIGNUP_MIN_PASSWORD} characters.
            </p>
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

          {infoMessage ? (
            <p className="rounded-md border border-live/40 bg-live/10 px-3 py-2 text-sm text-live">
              {infoMessage}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <AuthOrDivider />

        <GoogleSignInButton label="Sign up with Google" />
      </div>

      <p className="text-sm text-muted">
        Already have an account?{" "}
        {/*
            No target="_blank": this is the signup <-> login cross-link, and
            opening it in a new tab leaves the abandoned signup form behind in
            the original one.
          */}
        <Link
          href="/login"
          className="text-strong underline underline-offset-4 hover:text-foreground"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
