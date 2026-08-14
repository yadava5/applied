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
  return emailProblem(email) ?? passwordProblem(password, minPassword);
}

/** The first problem with this address, or null. */
export function emailProblem(email: string): CredentialProblem | null {
  if (email.trim().length === 0) {
    return { field: "email", message: "Enter your email address." };
  }
  if (!isValidEmail(email)) {
    return { field: "email", message: "That doesn’t look like an email address." };
  }
  return null;
}

/**
 * The first problem with this password, or null.
 *
 * Split out of {@link credentialProblem} so that the page which sets a NEW
 * password (`/reset-password`) enforces the same floor, with the same
 * sentence, as `/signup` — one implementation rather than a second standard
 * that drifts from the first. The password is never trimmed: whitespace is a
 * legitimate part of a password.
 */
export function passwordProblem(
  password: string,
  minPassword: number,
): CredentialProblem | null {
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

/** Which field a set-a-new-password form is complaining about. */
export type NewPasswordField = "password" | "confirmation";

export interface NewPasswordProblem {
  field: NewPasswordField;
  message: string;
}

/**
 * The first problem with a password someone is setting for the first time or
 * replacing, or null when there is none.
 *
 * The floor is `SIGNUP_MIN_PASSWORD`, deliberately: this is a password being
 * chosen, so the rule is the one `/signup` promises, not the lower one
 * `/login` accepts so that older accounts can still sign in. The confirmation
 * check is an ADDITIONAL rule layered on top — it is about typing, not about
 * strength — so it runs only once the shared floor is satisfied and the form
 * has a single problem to point at.
 */
export function newPasswordProblem(
  password: string,
  confirmation: string,
): NewPasswordProblem | null {
  const problem = passwordProblem(password, SIGNUP_MIN_PASSWORD);
  if (problem) return { field: "password", message: problem.message };
  if (confirmation !== password) {
    return { field: "confirmation", message: "Those passwords don’t match." };
  }
  return null;
}
