/**
 * Proof that THIS browser completed a password-recovery exchange.
 *
 * `/reset-password` must not accept just any authenticated session. A session
 * is a session — a stale one, a hijacked one, or simply the tab the user
 * already had open — and letting any of them set a new password means the
 * page changes a credential without the holder ever proving they had the
 * emailed link. So the gate is TWO things: a session, and this marker.
 *
 * Why a marker rather than the token's own `amr` claim, which is the textbook
 * answer: the claim is written by GoTrue and cannot be observed from here
 * without a live project and a real recovery email, neither of which this
 * work could reach. A gate asserted against a string nobody has seen fails in
 * exactly one direction — it denies every real user — and this repo has a
 * standing lesson about shipping checks that were never exercised. The marker
 * is written by `app/(auth)/reset-password/callback/route.ts` and by nothing
 * else, at the one moment `exchangeCodeForSession` succeeds on a recovery
 * code, so holding it proves the same property by construction, and both
 * halves of it can be exercised locally.
 *
 * It carries no secret and is not a credential: on its own it authorises
 * nothing, and it is only meaningful next to a session that the recovery
 * exchange itself created. It is `httpOnly` so no script can forge or read
 * it, scoped by `path` to the one page that consults it, short-lived, and
 * cleared the moment the new password is saved.
 */

/** The cookie's name. Prefixed like the app's own, not like Supabase's. */
export const RECOVERY_MARKER_COOKIE = "applied-password-recovery";

/** The only value ever written; anything else is not a marker this app set. */
export const RECOVERY_MARKER_VALUE = "1";

/**
 * How long the proof lasts. Long enough to choose a password and correct a
 * rejected one, short enough that an abandoned reset does not leave the page
 * reachable for the rest of the day.
 */
export const RECOVERY_MARKER_MAX_AGE_SECONDS = 10 * 60;

/** Where the cookie is sent — the reset page and its callback, nothing else. */
export const RECOVERY_MARKER_PATH = "/reset-password";

export interface RecoveryMarkerCookieOptions {
  httpOnly: boolean;
  sameSite: "lax";
  secure: boolean;
  path: string;
  maxAge: number;
}

/**
 * The attributes the marker is written with.
 *
 * `sameSite: "lax"` and not `"strict"`: the browser arrives at the callback
 * from Supabase's domain, a cross-site top-level navigation, which is exactly
 * the case Lax allows and Strict does not — the same reason the Supabase
 * session cookies this app already sets on that redirect are Lax.
 *
 * `secure` follows `NODE_ENV`, so every deployed environment gets it and only
 * `next dev` does not. A local `next start` is `NODE_ENV=production` and so
 * sets it over plain HTTP — which is fine, because browsers treat
 * `http://localhost` as a secure origin and store `Secure` cookies from it.
 */
export function recoveryMarkerCookieOptions(
  isProduction: boolean,
): RecoveryMarkerCookieOptions {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: RECOVERY_MARKER_PATH,
    maxAge: RECOVERY_MARKER_MAX_AGE_SECONDS,
  };
}

/** The same attributes, expiring the cookie instead of setting it. */
export function expiredRecoveryMarkerCookieOptions(
  isProduction: boolean,
): RecoveryMarkerCookieOptions {
  return { ...recoveryMarkerCookieOptions(isProduction), maxAge: 0 };
}

/**
 * Whether a cookie value is the marker this app writes.
 *
 * Exact match, never truthiness: an empty string, the string "false", or a
 * value some other code left under the same name must not read as proof.
 */
export function hasRecoveryMarker(value: string | undefined | null): boolean {
  return value === RECOVERY_MARKER_VALUE;
}
