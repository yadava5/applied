/**
 * The Profile card's account-security facts, derived — never assumed.
 *
 * "Sign-in method: Email & password" used to be a hardcoded literal, which
 * read as false to anyone who signs in with Google (#199). Measured against
 * the production auth tables, the accounts here are not one shape: an account
 * can hold an `email` identity, a `google` identity, or both at once — and
 * when both are linked, naming only one hides the other. Hiding that a
 * password exists is the security-relevant failure, so the summary lists
 * every linked identity and lets the password controls key off the same
 * derivation (#202): a Google-only account is never offered a change-password
 * form that cannot work.
 *
 * Pure and dependency-free (the `User` shape is structural, not imported), in
 * the same spirit as `lib/auth/credentials.ts` — which is what lets
 * `tests/unit` assert all three identity shapes with no browser at all.
 * (`node --test` cannot resolve a value import through the `@/` alias, which
 * is why the password floor arrives as a parameter, exactly as
 * `credentialProblem` takes it — the caller passes `SIGNUP_MIN_PASSWORD`.)
 */

/** The slice of a Supabase `User` the derivation reads. The real `User`
 *  satisfies it structurally; tests and the demo fixture build it literally. */
export interface IdentityBearer {
  identities?: { provider: string }[] | null;
  app_metadata?: { providers?: unknown } | null;
}

export interface SignInSummary {
  /** Pluralises with the facts: "sign-in method" vs "sign-in methods". */
  label: string;
  /** "Email & password", "Google", or "Email & password, or Google". */
  value: string;
  /** An `email` identity exists — a password is set and can be changed. */
  hasEmailIdentity: boolean;
}

/** Product names for the providers this app can actually link. Anything else
 *  (a future provider) falls back to its capitalised provider id rather than
 *  disappearing from the list. */
const PROVIDER_NAMES: Record<string, string> = {
  email: "Email & password",
  google: "Google",
};

function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/**
 * Summarise how this account signs in, from `auth.identities` — the table
 * that actually records linked identities. `app_metadata.providers` is the
 * fallback when the identities array is absent (it is a denormalised copy of
 * the same facts); an account that somehow reports neither gets "Unknown"
 * and no password controls, because claiming a method we cannot see would be
 * the original defect again.
 */
export function summarizeSignIn(user: IdentityBearer | null): SignInSummary {
  const fromIdentities = (user?.identities ?? []).map((identity) => identity.provider);
  const metaProviders = user?.app_metadata?.providers;
  const fromMeta = Array.isArray(metaProviders)
    ? metaProviders.filter((p): p is string => typeof p === "string")
    : [];

  const providers = [...new Set(fromIdentities.length > 0 ? fromIdentities : fromMeta)];
  // Email first: the credential the account was created with leads, and the
  // linked OAuth identities follow in whatever order they were linked.
  providers.sort((a, b) => Number(b === "email") - Number(a === "email"));

  if (providers.length === 0) {
    return { label: "sign-in method", value: "Unknown", hasEmailIdentity: false };
  }

  const names = providers.map(providerName);
  return {
    label: names.length > 1 ? "sign-in methods" : "sign-in method",
    // "or", not "and": each linked identity signs you in on its own.
    value:
      names.length > 1
        ? `${names.slice(0, -1).join(", ")}, or ${names[names.length - 1]}`
        : names[0],
    hasEmailIdentity: providers.includes("email"),
  };
}

export type NewPasswordField = "password" | "confirm";

/**
 * The first problem with a proposed new password, or null when there is none.
 * `minPassword` is `SIGNUP_MIN_PASSWORD` at the call site — the same floor
 * the signup form promises, passed in rather than re-invented, in the same
 * shape `credentialProblem` takes it. One problem at a time so the form can
 * point focus at one field, and the password is never trimmed for the same
 * reason as sign-in: whitespace is a legitimate part of a password.
 */
export function newPasswordProblem(
  password: string,
  confirm: string,
  minPassword: number,
): { field: NewPasswordField; message: string } | null {
  if (password.length === 0) {
    return { field: "password", message: "Enter a new password." };
  }
  if (password.length < minPassword) {
    return {
      field: "password",
      message: `Password must be at least ${minPassword} characters.`,
    };
  }
  if (confirm !== password) {
    return { field: "confirm", message: "Passwords don’t match." };
  }
  return null;
}
