/**
 * The credential checks both auth forms run BEFORE they touch the network.
 *
 * Both forms set `noValidate` on purpose — the app writes its own error copy
 * instead of showing browser-chrome bubbles — and that switch also turns off
 * `required`, `type="email"` and `minLength`. On `/login` nothing replaced
 * them, so every submit reached Supabase's token endpoint: an empty form, a
 * `not-an-email`, a three-character password all fired a real
 * `POST /auth/v1/token`, and the only feedback was whatever the server
 * eventually answered. A held Enter key spent live requests against an auth
 * rate limit this project has already been bitten by. `/signup` hand-checked
 * the password length but never the email, so a malformed address still cost
 * a real `POST /auth/v1/signup`.
 *
 * So the checks live here, once, and both pages run the same ones. They are
 * pure and dependency-free, which is what lets `tests/unit` import them under
 * Node's type stripping and assert the boundaries with no browser at all.
 */

/**
 * The two floors are deliberately NOT the same number.
 *
 * `/signup` promises "At least 8 characters" in its hint and must enforce what
 * it promises — Supabase's own floor is 6, so without this check the product
 * would silently accept a shorter password than the UI asked for. `/login`
 * must accept every password an account already has, so it mirrors that
 * Supabase floor of 6: raising it here would lock out anyone who signed up
 * under the older policy, which is a check that breaks sign-in rather than
 * protecting it.
 */
export const LOGIN_MIN_PASSWORD = 6;
export const SIGNUP_MIN_PASSWORD = 8;

/**
 * Deliberately not an RFC 5322 parser. It asserts the shape a mistyped address
 * fails and a real one passes — one `@`, no whitespace, a dotted domain — in
 * the same spirit as `isValidUrl` in the file-an-application form: enough to
 * catch the typo without rejecting an address someone actually owns. The
 * server remains the authority on whether the mailbox exists.
 */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/;

/** The RFC 5321 ceiling on a whole address — a cheap upper bound. */
const EMAIL_MAX_LENGTH = 254;

export function isValidEmail(value: string): boolean {
  // Trimmed first because a native `type="email"` input strips leading and
  // trailing whitespace from its own value; `noValidate` removed that too, so
  // the check restores it rather than failing a paste with a stray space.
  const email = value.trim();
  return email.length > 0 && email.length <= EMAIL_MAX_LENGTH && EMAIL_SHAPE.test(email);
}

export type CredentialField = "email" | "password";

/** Which field is wrong, and the sentence to show for it. */
export interface CredentialProblem {
  field: CredentialField;
  message: string;
}

/**
 * The first problem with these credentials, or null when there is none.
 *
 * One problem at a time, in reading order: the form has a single alert region
 * and pointing at one field is what lets focus move there. The password is
 * never trimmed — whitespace is a legitimate part of a password.
 */
export function credentialProblem(
  email: string,
  password: string,
  minPassword: number,
): CredentialProblem | null {
  if (email.trim().length === 0) {
    return { field: "email", message: "Enter your email address." };
  }
  if (!isValidEmail(email)) {
    return { field: "email", message: "That doesn’t look like an email address." };
  }
  if (password.length === 0) {
    return { field: "password", message: "Enter your password." };
  }
  if (password.length < minPassword) {
    return {
      field: "password",
      message: `Password must be at least ${minPassword} characters.`,
    };
  }
  return null;
}
