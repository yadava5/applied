import { NextResponse, type NextRequest } from "next/server";
import {
  createServerClient,
  type CookieOptions,
} from "@supabase/ssr";

import { publicEnv } from "@/lib/env";
import { isProtectedPath } from "@/lib/supabase/protectedRoutes";

/**
 * Paths under this prefix require an authenticated Supabase session. In the
 * App Router, route groups `(auth)` and `(app)` are **not** reflected in the
 * URL, so gating happens on the literal URL prefix `/dashboard` (and future
 * protected segments added inside `app/(app)/`). Extend this list rather
 * than the negative matcher in `proxy.ts` when adding new protected pages —
 * that way, the proxy keeps running on all app routes but only *redirects*
 * for known-protected ones.
 */
const PUBLIC_AUTH_PATHS = new Set(["/login", "/signup", "/callback"]);

/**
 * `updateSession` is called from `proxy.ts` for every request that matches
 * the matcher config. It:
 *
 *   1. Creates a Supabase server client bound to the incoming cookie jar.
 *   2. Calls `auth.getUser()` — this triggers a silent refresh of the
 *      Supabase tokens when they are close to expiring, and writes the new
 *      cookies onto the response via `setAll`.
 *   3. If the request targets a protected path and the user is missing,
 *      redirects to `/login?redirect=<original>`.
 *   4. Otherwise returns the (possibly cookie-updated) response so the
 *      refreshed session is persisted back to the browser.
 *
 * IMPORTANT: the supabase client must be constructed with both the request
 * and response cookie jars so that refreshed tokens flow through. Mutating
 * only one of them is the root cause of the "random logout" class of bugs
 * documented in `@supabase/ssr`.
 *
 * IMPORTANT: `setAll` takes a SECOND argument. Since `@supabase/ssr` 0.12.x it
 * is called as `setAll(cookies, headers)`, where `headers` is a set of
 * no-store directives that must land on the same response as the cookies —
 * `applyServerStorage` in `@supabase/ssr/src/cookies.ts` passes them, and
 * `src/types.ts` explains why: a cached response carrying auth cookies can
 * serve one user's session token to a different user. Nothing warns you if you
 * drop it. TypeScript assigns a one-parameter function to the two-parameter
 * `SetAllCookies` type without complaint, so a `setAll` written against the
 * old shape typechecks and silently discards the headers.
 */
export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(
          cookiesToSet: {
            name: string;
            value: string;
            options: CookieOptions;
          }[],
          headers: Record<string, string>,
        ) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          // Rebuilding the response is what propagates the mutated request
          // cookies onward, so it has to happen here — but it discards
          // everything already set on the old object. Both the cookies and the
          // headers are therefore applied AFTER this line, never before.
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options),
          );
          Object.entries(headers).forEach(([name, value]) =>
            supabaseResponse.headers.set(name, value),
          );
        },
      },
    },
  );

  // Touching `auth.getUser()` forces a refresh of the session cookies when
  // they are close to expiring. Do NOT replace this with `auth.getSession()`
  // (which reads cookies only) — that would skip the refresh.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  if (!user && isProtectedPath(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("redirect", pathname);
    return NextResponse.redirect(url);
  }

  if (user && PUBLIC_AUTH_PATHS.has(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}
