/**
 * The password-reset request, with the one property the feature exists for:
 * **the answer must not depend on whether the account exists.**
 *
 * That property is a type here, not a promise. `requestPasswordReset` swallows
 * whatever `resetPasswordForEmail` produced — a returned `{ error }`, a thrown
 * fetch failure, a 429 — and hands back a value with no field capable of
 * carrying it. The page therefore *cannot* render a provider message: it never
 * holds one. Discipline in the component would have been the alternative, and
 * discipline is exactly what regresses.
 *
 * The 429 is the specific trap. Supabase's documented limits are two different
 * things: a project-wide "2 emails per hour with the built-in email provider",
 * and — on `/auth/v1/recover` — "a 60 seconds window before a new request is
 * allowed to the same user". The second only fires for an address that HAS a
 * user, so surfacing "you can only request this after 51 seconds" would confirm
 * the account exists as surely as printing "no such user" would.
 * (https://supabase.com/docs/guides/auth/rate-limits, read 2026-08-14.)
 *
 * Pure and dependency-free — no `@/` alias, no Supabase import, the sender is
 * injected — so `tests/unit` can load it under Node's type stripping and assert
 * the property against a fake that fails in each of those ways.
 */

/**
 * The single sentence the request form ever shows on success. Conditional
 * copy is how this feature usually leaks: "we sent you a link" for a real
 * address and "no account found" for the rest is an enumeration oracle with
 * good manners.
 */
export const RESET_EMAIL_SENT_NOTICE =
  "If an account exists for that address, a link to set a new password is on its way. Check your inbox, and your spam folder.";

/** Seconds the form refuses to send again — see {@link remainingCooldown}. */
export const RESEND_COOLDOWN_SECONDS = 60;

/**
 * What the request produced. One field, and it is a constant: there is
 * deliberately nowhere to put an error, a status code, or a hint about the
 * address. Anything the caller could branch on would eventually be branched on.
 */
export interface ResetRequestOutcome {
  readonly notice: string;
}

/**
 * Ask Supabase to email a recovery link, and report the same thing either way.
 *
 * `send` is the injected `(address) => supabase.auth.resetPasswordForEmail(...)`.
 * Its resolved value is dropped on the floor and a rejection is caught, because
 * both encode whether the mailbox is a user of this product.
 *
 * The address is trimmed first — the same normalisation `/login` and `/signup`
 * apply, and what a native `type="email"` input would itself have submitted.
 * The caller validates the shape (`emailProblem`) BEFORE calling this, so a
 * typo still costs nothing; that check is identical for every address and
 * therefore leaks nothing.
 */
export async function requestPasswordReset(
  email: string,
  send: (address: string) => Promise<unknown>,
): Promise<ResetRequestOutcome> {
  try {
    await send(email.trim());
  } catch {
    // Deliberately empty. A network failure, a CSP block and a rejected
    // address must all look like a sent link — see the file header.
  }
  return { notice: RESET_EMAIL_SENT_NOTICE };
}

/**
 * Whole seconds left before the form will send another link, floored at 0.
 *
 * This is a UX bound, not a security control, and the difference matters
 * enough to say out loud: it lives in one browser tab and anyone who wants to
 * spend requests can simply not run it. The real bound is GoTrue's, quoted in
 * the header. What it buys is the accidental case this repo has already been
 * bitten by — a held Enter key spending live requests against an auth rate
 * limit — and an honest answer to "why is nothing arriving?", which is the
 * 60-second window rather than a lost email.
 */
export function remainingCooldown(
  sentAt: number,
  now: number,
  seconds: number = RESEND_COOLDOWN_SECONDS,
): number {
  return Math.max(0, Math.ceil((sentAt + seconds * 1000 - now) / 1000));
}
