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
        ) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options),
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
