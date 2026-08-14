import { cookies } from "next/headers";
import Link from "next/link";

import { SetNewPasswordForm } from "@/components/auth/SetNewPasswordForm";
import { Logo } from "@/components/brand/Logo";
import {
  RECOVERY_MARKER_COOKIE,
  hasRecoveryMarker,
} from "@/lib/auth/recoverySession";
import { getCurrentUser } from "@/lib/supabase/auth";

/**
 * Step two of the reset: the page a recovery link ends on.
 *
 * The gate is a session AND the recovery marker, and it takes both. A session
 * alone is not evidence of anything this page needs: an ordinary signed-in
 * visitor, a tab left open, a stolen cookie all have one, and none of them
 * has shown they hold the emailed link. The marker is written only by
 * `/reset-password/callback`, only when a recovery code was successfully
 * exchanged, and only into the browser that did it — see
 * `lib/auth/recoverySession.ts` for why the proof is a marker rather than the
 * token's `amr` claim.
 *
 * Both halves are read on the server — the session through the request-scoped
 * DAL (`lib/supabase/auth.ts`) — rather than in the browser: a client-side
 * `getSession()` would race the first paint and flash the wrong state.
 *
 * Everything that is not both — an expired link, one already used, one opened
 * in a browser that never requested it, or a signed-in visitor who simply
 * typed the URL — gets the same sentence and the same way back. Failing them
 * identically is deliberate: which of those happened is not the visitor's
 * business to learn from an error message.
 *
 * This path is in NEITHER route list, on purpose. `PROTECTED_PREFIXES` is
 * derived from `app/(app)/` by `tests/unit/protected-routes.test.mjs` and this
 * page is not there; `PUBLIC_AUTH_PATHS` would be worse than useless, since it
 * bounces a signed-in visitor to `/dashboard` — and after a recovery exchange
 * the visitor IS signed in.
 */
export default async function ResetPasswordPage() {
  const cookieStore = await cookies();
  const inRecovery = hasRecoveryMarker(
    cookieStore.get(RECOVERY_MARKER_COOKIE)?.value,
  );
  // Short-circuited: no marker, no reason to spend a verified `getUser()`
  // round-trip on someone who cannot be shown the form either way.
  const canSetPassword = inRecovery && (await getCurrentUser()) !== null;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-12">
      <div className="space-y-6">
        <header className="space-y-2">
          <Link href="/" aria-label="Applied — home" className="brand-logo-link mb-4 text-strong">
            <Logo className="h-7 w-auto" />
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            {canSetPassword ? "Set a new password" : "This link has expired"}
          </h1>
          <p className="text-sm text-muted">
            {canSetPassword
              ? "Choose a new password for your Applied account. You’ll sign in with it straight away."
              : "Password reset links can only be used once, they expire, and they have to be opened in the browser that asked for them."}
          </p>
        </header>

        {canSetPassword ? (
          <SetNewPasswordForm />
        ) : (
          <p className="text-sm text-muted">
            <Link
              href="/forgot-password"
              className="text-strong underline underline-offset-4 hover:text-foreground"
            >
              Request a new link
            </Link>{" "}
            and we’ll email you another one.
          </p>
        )}

        <p className="text-sm text-muted">
          <Link
            href="/login"
            className="text-strong underline underline-offset-4 hover:text-foreground"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
