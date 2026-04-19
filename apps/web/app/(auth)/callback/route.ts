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
 * Flow:
 *   1. Read `code` and optional `redirect` from the URL.
 *   2. Call `supabase.auth.exchangeCodeForSession(code)` — this writes the
 *      Supabase auth cookies via the `setAll` configured in
 *      `lib/supabase/server.ts`.
 *   3. Redirect to the original target (defaulting to `/dashboard`).
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const redirectParam = searchParams.get("redirect") ?? "/dashboard";

  // Refuse open redirects: only allow same-origin paths.
  const nextPath = redirectParam.startsWith("/") ? redirectParam : "/dashboard";

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
