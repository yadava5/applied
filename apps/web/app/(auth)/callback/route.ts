import { NextResponse, type NextRequest } from "next/server";

import {
  destinationAfterSignIn,
  providerOfThisSignIn,
  type GmailLinkState,
} from "@/lib/auth/postSignIn";
import { DEFAULT_REDIRECT, safeRedirectPath } from "@/lib/auth/redirect";
import { getGmailStatus } from "@/lib/gmail/server";
import { expireSpentPkceVerifierCookies } from "@/lib/supabase/pkceVerifierCookies";
import { createClientWithSessionHeaders } from "@/lib/supabase/server";

/**
 * Supabase PKCE callback handler.
 *
 * When Supabase Auth sends a confirmation / magic-link / OAuth redirect, the
 * URL contains a `?code=...` parameter. Exchanging that code for a session
 * must happen server-side so the resulting cookies are set on the correct
 * domain with HttpOnly.
 *
 * This one handler serves every redirect-based sign-in: email confirmation,
 * magic links, and the Google OAuth provider (`signInWithOAuth`) — they all
 * come back with the same `?code=...` PKCE payload.
 *
 * Flow:
 *   1. Read `code` and optional `redirect` from the URL.
 *   2. If the provider bounced back an `?error` instead (e.g. the user
 *      cancelled Google consent, or the provider is disabled), forward a
 *      readable message to `/login` rather than treating it as a missing code.
 *   3. Call `supabase.auth.exchangeCodeForSession(code)` — this writes the
 *      Supabase auth cookies via the `setAll` configured in
 *      `lib/supabase/server.ts`.
 *   4. Redirect to the original target (defaulting to `/dashboard`).
 *
 * Every exit AFTER the client is created goes through `applySessionHeaders`
 * (#242). This is the response that carries the INITIAL session — `setAll` runs
 * here in a Route Handler, where `cookieStore.set` succeeds rather than being
 * swallowed, so the cookies really do ride out on this redirect and the library
 * hands over `Cache-Control: no-store` + `Expires` + `Pragma` to go with them.
 * It is applied on the failure branches too: whether a given branch caused a
 * cookie write is not a question a future edit should have to get right, and
 * the call is a no-op when nothing was written.
 *
 * The same exits also expire the PKCE verifier cookies the exchange just spent
 * (#321) — the flow slot and, on the failure branch, the fixed key that
 * `@supabase/ssr` asks to remove but never flushes. See
 * `lib/supabase/pkceVerifierCookies.ts` for what is and is not provably spent.
 * Both are folded into one `finish` so an exit cannot acquire one and miss the
 * other.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  // Refuse open redirects: only allow same-origin paths. `startsWith("/")`
  // used to be the whole check and did not do that — `?redirect=//evil.com`
  // starts with a slash, and `new URL("//evil.com", origin)` below resolves to
  // `https://evil.com`, so this handler answered with a 302 off-origin. See
  // `lib/auth/redirect.ts`.
  const nextPath = safeRedirectPath(searchParams.get("redirect"));

  // A provider (OAuth) that fails or is cancelled redirects here with an
  // `error` / `error_description` instead of a `code`. Surface it on /login,
  // which humanises the message, rather than the misleading "missing_code".
  const providerError =
    searchParams.get("error_description") ?? searchParams.get("error");
  if (providerError) {
    const failUrl = new URL("/login", origin);
    failUrl.searchParams.set("error", providerError);
    return NextResponse.redirect(failUrl);
  }

  if (!code) {
    const failUrl = new URL("/login", origin);
    failUrl.searchParams.set("error", "missing_code");
    return NextResponse.redirect(failUrl);
  }

  const { supabase, applySessionHeaders } =
    await createClientWithSessionHeaders();

  /** Every exit from here on. One shape, so no branch can carry less. */
  const finish = (response: NextResponse) =>
    expireSpentPkceVerifierCookies(request, applySessionHeaders(response));

  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const failUrl = new URL("/login", origin);
    failUrl.searchParams.set("error", error.message);
    return finish(NextResponse.redirect(failUrl));
  }

  // #494: a Google sign-in carries straight on into the Gmail grant instead of
  // stopping at a dashboard with nothing in it. The decision — and every
  // reason behind it, including what it deliberately does NOT do — lives in
  // `lib/auth/postSignIn.ts`, which is pure so the whole table is unit-tested;
  // this handler only gathers the three inputs.
  //
  // The status probe is asked ONLY when the answer can change the destination:
  // a non-Google sign-in, or one with a real destination already requested,
  // skips it and pays nothing. When it is asked, it is asked with the access
  // token the exchange just returned, because the cookies carrying this
  // session are on the response being built and not on the inbound request.
  const provider = providerOfThisSignIn({
    providerToken: data.session?.provider_token,
    appMetadataProvider: data.user?.app_metadata?.provider,
    appMetadataProviders: data.user?.app_metadata?.providers,
  });

  let gmail: GmailLinkState = "unknown";
  if (provider === "google" && nextPath === DEFAULT_REDIRECT) {
    const status = await getGmailStatus(data.session?.access_token);
    // Anything other than a clean answer stays `unknown`, which does not
    // chain. A probe that failed is not evidence of a missing connection.
    if (status.kind === "ok") {
      gmail = status.status.connected ? "connected" : "not_connected";
    }
  }

  const destination = destinationAfterSignIn({
    provider,
    gmail,
    requestedRedirect: nextPath,
  });

  return finish(NextResponse.redirect(new URL(destination, origin)));
}
