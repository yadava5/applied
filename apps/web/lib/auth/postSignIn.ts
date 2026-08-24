// Relative, with the extension, so `tests/unit` can import this module under
// Node's type stripping — the `@/` alias is a bundler concern Node cannot
// resolve, and this decision has to stay executable without one.
import { DEFAULT_REDIRECT } from "./redirect.ts";

/**
 * Where a completed sign-in lands — and, specifically, when it should carry
 * straight on into the Gmail consent screen instead of stopping.
 *
 * THE COMPLAINT THIS EXISTS FOR (#494). Signing up with Google and then being
 * asked to "connect Google" was read, reasonably, as being asked to sign in
 * twice. It is not quite that — see the next paragraph — but the part that was
 * genuinely bad product is real: the second grant was never offered, it had to
 * be gone looking for. A new user landed on an empty dashboard with no mail in
 * it and had to find Settings on their own to make the product do anything.
 *
 * WHAT THIS CANNOT DO, stated here because the file name promises more than it
 * delivers. Two Google grants are two Google grants. Supabase Auth (GoTrue)
 * holds one OAuth client with `openid email profile`; the FastAPI backend
 * holds a different one with `gmail.readonly`. Google will not carry a grant
 * from one client_id to another, so the second consent screen is not
 * removable from here at any price. Collapsing them means one client — the
 * GIS + `signInWithIdToken` rewrite — which is a different project and is
 * currently blocked behind the restricted-scope review on a `supabase.co`
 * domain nobody here can own. So what this buys is ONE CLICK, TWO SCREENS,
 * back to back, instead of a click, a dead end, and a scavenger hunt.
 *
 * Pure and dependency-free apart from the shared default, so `tests/unit` can
 * table every row of the decision with no Next, no Supabase and no browser —
 * which matters more than usual here, because the flow this governs ends at
 * Google's consent screen and is therefore not drivable in CI at all.
 */

/**
 * Which provider carried THIS sign-in. Deliberately two-valued: the only
 * question the decision asks is "was this the Google button", and widening it
 * to the provider list invites reading `app_metadata.provider` — which records
 * the provider a user FIRST signed up with, not the one they just used.
 */
export type SignInProvider = "google" | "other";

/**
 * Whether the user already has Gmail linked.
 *
 * `unknown` is a real third state and not a synonym for `not_connected`: it is
 * what a failed status probe returns. Treating a probe failure as "not
 * connected" is precisely the defect phase 1 removed from the dashboard, where
 * a backend hiccup made the app show a stranger's sample data. The same
 * mistake here would push an already-connected user into a consent screen
 * because the network blipped.
 */
export type GmailLinkState = "connected" | "not_connected" | "unknown";

/** Entry point for the chained consent, tagged so the route can tell. */
export const CHAINED_GMAIL_AUTHORIZE = "/api/gmail/authorize?from=signin";

export interface PostSignInInput {
  /** Which provider carried this sign-in. */
  provider: SignInProvider;
  /** Whether Gmail is already linked, or unknowable right now. */
  gmail: GmailLinkState;
  /**
   * The destination the caller asked for, ALREADY through `safeRedirectPath`.
   *
   * `DEFAULT_REDIRECT` means "nothing in particular was asked for", and that
   * conflation is deliberate rather than sloppy. The obvious design — `null`
   * for absent, a string for explicit — CANNOT WORK HERE, and the reason is
   * worth writing down because it is invisible from this file:
   * `GoogleSignInButton` builds its callback URL with
   * `callbackUrl.searchParams.set("redirect", safeRedirect)`, where
   * `safeRedirect` has already been defaulted to `/dashboard`. The parameter is
   * therefore ALWAYS present on the Google path. A rule keyed on "was
   * `?redirect=` absent" would be false on every single Google sign-in, the
   * chain would never once fire, and every test covering the other rows would
   * still pass — a check that cannot fail, dressed as a feature.
   *
   * Reading `/dashboard` as "no preference" costs only this: a user who
   * explicitly asked for `/dashboard` may be chained. That is where they were
   * going anyway, so the cost is nil, and the security property that mattered
   * survives intact — a caller-supplied value still cannot TURN THE CHAIN ON,
   * because the chain additionally requires a Google sign-in and a provably
   * unconnected account, neither of which a URL can fake.
   */
  requestedRedirect: string;
}

/**
 * Resolve the post-sign-in destination.
 *
 * PRECEDENCE, in order, each rule existing for a case that would otherwise be
 * wrong:
 *
 *  1. A destination OTHER than the default always wins. Someone who followed
 *     `/login?redirect=/settings` asked to go to Settings; hijacking that into
 *     a consent screen would be the app overruling a stated intent. This also
 *     keeps the chain off the one input an attacker can reach: `?redirect=` is
 *     caller-supplied, so the chain must never be a thing a crafted link can
 *     TURN ON — here it can only turn it off. See `requestedRedirect` for why
 *     the test is "is it the default" and not "was it absent".
 *  2. Only the Google button chains. A password sign-in that ended here has
 *     not consented to anything Google-shaped and must not be sent to Google.
 *  3. Only a user who is provably NOT connected chains. `connected` would be
 *     a pointless re-consent, and it would fight the disconnect feature: a
 *     user who deliberately unlinked Gmail would be dragged back into consent
 *     on their next login, every time. `unknown` does not chain — see
 *     `GmailLinkState`.
 *
 * Everything else lands on the dashboard, which is the pre-existing behaviour
 * this replaces nothing of.
 */
export function destinationAfterSignIn(input: PostSignInInput): string {
  const { provider, gmail, requestedRedirect } = input;

  if (requestedRedirect !== DEFAULT_REDIRECT) return requestedRedirect;
  if (provider !== "google") return DEFAULT_REDIRECT;
  if (gmail !== "not_connected") return DEFAULT_REDIRECT;

  return CHAINED_GMAIL_AUTHORIZE;
}

/**
 * Read the provider off what `exchangeCodeForSession` just handed back.
 *
 * TWO SIGNALS, EITHER SUFFICES, and the asymmetry is deliberate:
 *
 *  - `session.provider_token` is populated only on a fresh OAuth exchange —
 *    it is not persisted and does not survive a refresh — so its presence is
 *    the most direct available evidence that THIS sign-in went through a
 *    provider rather than a password.
 *  - `user.app_metadata.provider` records the provider the account was FIRST
 *    created with, which is not the same question. It is included anyway
 *    because a Supabase account created through Google has no password to
 *    sign in with unless the user later sets one, so in practice it agrees.
 *
 * OR rather than AND, on purpose. Requiring both would make the whole feature
 * depend on a field whose presence is a provider/config detail: if Google ever
 * stopped returning an access token to GoTrue, the chain would silently never
 * fire and every test asserting the "other" rows would still pass — a check
 * that cannot fail, which is the recurring defect shape in this codebase.
 * Failing open costs at most one benign consent offer to a password user who
 * has a Google identity linked AND no Gmail connected, which is a state where
 * the offer is the right thing to show anyway.
 */
export function providerOfThisSignIn(input: {
  providerToken: string | null | undefined;
  appMetadataProvider: string | null | undefined;
  appMetadataProviders?: readonly string[] | null;
}): SignInProvider {
  if (input.providerToken) return "google";
  if (input.appMetadataProvider === "google") return "google";
  if (input.appMetadataProviders?.includes("google")) return "google";
  return "other";
}
