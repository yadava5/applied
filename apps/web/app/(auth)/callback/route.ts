import { NextResponse, type NextRequest } from "next/server";

import { createClient } from "@/lib/supabase/server";

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
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const redirectParam = searchParams.get("redirect") ?? "/dashboard";

  // Refuse open redirects: only allow same-origin paths.
  const nextPath = redirectParam.startsWith("/") ? redirectParam : "/dashboard";

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

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const failUrl = new URL("/login", origin);
    failUrl.searchParams.set("error", error.message);
    return NextResponse.redirect(failUrl);
  }

  return NextResponse.redirect(new URL(nextPath, origin));
}
