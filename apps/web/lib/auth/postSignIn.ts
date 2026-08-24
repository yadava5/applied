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
   * Whether this is the account's FIRST sign-in — i.e. the person is signing
   * UP, not signing back in. See `isFirstSignInOfAccount` for how it is read
   * and why the two timestamps can answer it.
   */
  isFirstSignIn: boolean;
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
 *  3. Only the account's FIRST sign-in chains, and this rule is the whole
 *     reason #503 exists. Rules 1, 2 and 4 alone say "chain whenever a Google
 *     user is not connected", which is true on EVERY subsequent login too —
 *     so a user who connected Gmail and later deliberately disconnected it
 *     would be pushed at Google's consent screen every single time they signed
 *     in, forever, with no way to say no that the app would remember. That is
 *     the original complaint ("no one wants to sign up or log in again and
 *     again") reintroduced from the other end, and an earlier version of this
 *     comment claimed rule 4 PREVENTED it. It does not: a deliberately
 *     disconnected user reads `not_connected`, which is precisely the state
 *     rule 4 chains on. Rule 4 only rules out the connected user, who was
 *     never the problem.
 *
 *     THE HONEST WAY TO SAY "THEY DISCONNECTED ON PURPOSE" DOES NOT EXIST HERE,
 *     and that is why the test is first-sign-in rather than intent.
 *     `/auth/gmail/disconnect` DELETES the credential row and un-enrols the
 *     mailbox (`cloud/gmail_oauth.py`), so nothing survives a disconnect to
 *     distinguish "chose to unlink" from "never linked". Recording it would be
 *     new schema. First-sign-in needs none, and it answers the question the
 *     product actually asked: offer the mailbox once, at the moment someone
 *     signs UP, then let them come back to it in Settings.
 *
 *     WHAT THIS COSTS, stated rather than hidden: someone who signs up with
 *     Google and cancels at Google's screen is not offered the chain again
 *     automatically. They are not stranded — the empty dashboard's "Connect
 *     Gmail" card and the Settings page both offer it — but the second chance
 *     is theirs to take, not ours to insist on.
 *
 *  4. Only a user who is provably NOT connected chains. `connected` would be a
 *     pointless re-consent. `unknown` does not chain — a failed probe is not
 *     evidence of a missing connection; see `GmailLinkState`.
 *
 * Everything else lands on the dashboard, which is the pre-existing behaviour
 * this replaces nothing of.
 */
export function destinationAfterSignIn(input: PostSignInInput): string {
  const { provider, gmail, isFirstSignIn, requestedRedirect } = input;

  if (requestedRedirect !== DEFAULT_REDIRECT) return requestedRedirect;
  if (provider !== "google") return DEFAULT_REDIRECT;
  if (!isFirstSignIn) return DEFAULT_REDIRECT;
  if (gmail !== "not_connected") return DEFAULT_REDIRECT;

  return CHAINED_GMAIL_AUTHORIZE;
}

/**
 * How close `last_sign_in_at` must sit to `created_at` to mean "same request".
 *
 * Thirty seconds is deliberately loose. The observed gap is sub-second, so
 * this is not tuned to a measurement — it is tuned to be unmistakably shorter
 * than a human leaving and coming back, which is the only thing on the other
 * side of the line.
 */
const FIRST_SIGN_IN_WINDOW_MS = 30_000;

/**
 * Is this the account's first sign-in — is the person signing UP?
 *
 * Both timestamps come straight off the Supabase user the code exchange just
 * returned. GoTrue writes `last_sign_in_at` as part of the very request that
 * creates the account, so on a signup the two are the same instant to within
 * the write itself; on a return visit they are separated by however long the
 * person was away.
 *
 * MEASURED, not assumed. On this project's own `auth.users` a Google account
 * created by signing up shows the pair 0.47 SECONDS apart, while an account
 * that came back later shows 4h37m. The window below sits between those two
 * observations by three orders of magnitude in each direction, which is what
 * makes it a threshold rather than a guess — and the test pins both real
 * magnitudes so a future edit cannot quietly widen it into "always true".
 *
 * A NULL `lastSignInAt` also counts as first, and that branch is not dead
 * defensiveness: if GoTrue ever hands back the user as it stood BEFORE this
 * sign-in was recorded, a brand-new account's field is null and the delta test
 * has nothing to subtract. Either shape answers the same question correctly.
 *
 * Unparseable input answers `false` — the safe direction. A false negative
 * costs one missed offer that Settings still carries; a false positive sends
 * someone who did not just sign up to Google's consent screen.
 */
export function isFirstSignInOfAccount(input: {
  createdAt: string | null | undefined;
  lastSignInAt: string | null | undefined;
}): boolean {
  const created = Date.parse(input.createdAt ?? "");
  if (Number.isNaN(created)) return false;
  if (!input.lastSignInAt) return true;

  const lastSignIn = Date.parse(input.lastSignInAt);
  if (Number.isNaN(lastSignIn)) return false;

  return lastSignIn - created < FIRST_SIGN_IN_WINDOW_MS;
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
