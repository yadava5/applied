"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  SIGNUP_MIN_PASSWORD,
  newPasswordProblem,
  type NewPasswordField,
} from "@/lib/auth/credentials";
import { createClient } from "@/lib/supabase/client";

/**
 * Step two of the reset: choose the new password.
 *
 * By the time this renders, `/reset-password/callback` has exchanged the
 * recovery code for a session, so `updateUser` is an ordinary authenticated
 * write — there is no token to hold, pass around, or accidentally log, and
 * nothing about the recovery link is in the URL any more.
 *
 * The rules come from `lib/auth/credentials.ts`, the same module `/signup`
 * validates against, so a password refused here is refused there and the
 * sentence shown is the same sentence.
 */
export function SetNewPasswordForm() {
  const router = useRouter();

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  /** Which field the current error is about — null for a server-side one. */
  const [invalidField, setInvalidField] = useState<NewPasswordField | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const errorId = useId();
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // `noValidate` is deliberate — the app writes its own error copy — so the
    // rules the markup declares are re-asserted here, before the network, by
    // the module `/signup` shares.
    const problem = newPasswordProblem(password, confirmation);
    if (problem) {
      setError(problem.message);
      setInvalidField(problem.field);
      (problem.field === "password" ? passwordRef : confirmationRef).current?.focus();
      return;
    }

    setError(null);
    setInvalidField(null);
    setIsSubmitting(true);

    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });

    if (updateError) {
      // Safe to surface: this request is already authenticated as the account
      // whose password is changing, so its message ("should be different from
      // the old password", a session that expired mid-form) describes the
      // password, not who exists.
      setError(updateError.message);
      setIsSubmitting(false);
      return;
    }

    // The password is changed; everything below is best-effort and none of it
    // may turn into an error the user sees. Telling them something went wrong
    // here would send them to reset a password that is already new.
    try {
      // Spend the recovery marker, so the proof that got them onto this page
      // cannot be used again by whatever session comes next in this browser.
      await fetch("/api/auth/recovery/complete", { method: "POST" });
    } catch {
      // Deliberately empty — the marker expires on its own regardless.
    }

    try {
      // A reset is what someone does when they think a session is not theirs
      // any more, so ending every session for this user is the point of it:
      // the recovery link is itself a sign-in, and leaving the others live
      // would mean the reset changed a credential without evicting anyone
      // holding the old one. If this fails the proxy will bounce them to
      // /dashboard instead of /login, which is the correct outcome for a
      // session that survived.
      await supabase.auth.signOut({ scope: "global" });
    } catch {
      // Deliberately empty — see above.
    }

    router.refresh();
    router.replace("/login?reset=success");
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div className="space-y-1">
        <label htmlFor="password" className="block text-sm font-medium">
          New password
        </label>
        <input
          id="password"
          ref={passwordRef}
          type="password"
          autoComplete="new-password"
          required
          minLength={SIGNUP_MIN_PASSWORD}
          aria-invalid={invalidField === "password"}
          aria-describedby={invalidField === "password" ? errorId : undefined}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="block w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-strong outline-none placeholder:text-dim focus:border-line-strong focus:ring-1 focus:ring-line-strong"
        />
        <p className="text-xs text-dim">At least {SIGNUP_MIN_PASSWORD} characters.</p>
      </div>

      <div className="space-y-1">
        <label htmlFor="confirmation" className="block text-sm font-medium">
          Confirm new password
        </label>
        <input
          id="confirmation"
          ref={confirmationRef}
          type="password"
          autoComplete="new-password"
          required
          aria-invalid={invalidField === "confirmation"}
          aria-describedby={invalidField === "confirmation" ? errorId : undefined}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
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
        {isSubmitting ? "Saving…" : "Set new password"}
      </Button>
    </form>
  );
}
