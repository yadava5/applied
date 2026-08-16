/**
 * Where a sign-in is allowed to land.
 *
 * `/login`, `/callback` and the Google button all carry a caller-supplied
 * `?redirect=` through the auth flow, and all three used to vet it with
 * `value.startsWith("/") ? value : "/dashboard"` under a comment that read
 * "Refuse open redirects: only allow same-origin paths". It did not: a
 * protocol-relative `//evil.com` starts with a slash and resolves off-origin,
 * so `?redirect=//evil.com` handed a freshly signed-in user to an attacker's
 * site — from `router.replace` on the client, and as a real 302 from
 * `/callback` on the server.
 *
 * String tests are what failed, so this does not add more of them: the
 * candidate is RESOLVED against a fixed dummy origin with the same parser the
 * browser uses, and only a result that stayed on that origin is accepted.
 * Parsing is also what normalises the smuggled variants — a tab or newline
 * inside `/<TAB>/evil.com` is stripped BEFORE resolution, `/\evil.com` has its
 * backslash read as a slash — so they are judged as what the browser will
 * actually navigate to rather than as what they look like.
 *
 * Pure and dependency-free on purpose, so `tests/unit` can import it under
 * Node's type stripping and assert every vector with no browser at all.
 */

/** Where a rejected — or absent — destination goes instead. */
export const DEFAULT_REDIRECT = "/dashboard";

/**
 * A parse target that is guaranteed not to be anyone's real origin. `.invalid`
 * is reserved (RFC 2606), so nothing can register it and make a candidate
 * "same-origin" by owning the host.
 */
const RESOLUTION_ORIGIN = "https://redirect.invalid";

/**
 * Reduce `candidate` to a path this app may navigate to, or `DEFAULT_REDIRECT`.
 *
 * The return value is REBUILT from the parsed URL rather than echoed back from
 * the input: an absolute URL that happens to name the resolution origin would
 * otherwise pass the origin check and reach the caller still absolute. It is
 * idempotent — feeding a returned value back in yields the same value — which
 * is what lets the navigation sites re-apply it as a second gate.
 */
export function safeRedirectPath(candidate: string | null | undefined): string {
  // A path, not a reference to somewhere else. `dashboard` would resolve to
  // `/dashboard` and be silently accepted, and `javascript:` / `data:` /
  // `http:` are refused here before the parser is asked about them.
  if (!candidate || !candidate.startsWith("/")) return DEFAULT_REDIRECT;

  // `/\evil.com` is protocol-relative to a browser, and a backslash has no
  // business in a route this app owns. The parser already folds it to a slash,
  // so this is belt-and-braces against a future parser that does not.
  if (candidate.includes("\\")) return DEFAULT_REDIRECT;

  let resolved: URL;
  try {
    resolved = new URL(candidate, RESOLUTION_ORIGIN);
  } catch {
    return DEFAULT_REDIRECT;
  }

  // `//evil.com`, `///evil.com`, `/<TAB>/evil.com` all land here with someone
  // else's origin — and `javascript:`/`data:` with the string "null".
  if (resolved.origin !== RESOLUTION_ORIGIN) return DEFAULT_REDIRECT;

  const path = `${resolved.pathname}${resolved.search}${resolved.hash}`;

  // `/..//evil.com` resolves ON this origin, but its pathname normalises to
  // `//evil.com` — protocol-relative again the moment it is handed to a router.
  // The origin check cannot see that; only re-reading the OUTPUT can.
  if (!path.startsWith("/") || path.startsWith("//")) return DEFAULT_REDIRECT;

  return path;
}
