import { NextResponse, type NextRequest } from "next/server";
import {
  createServerClient,
  type CookieOptions,
} from "@supabase/ssr";

import { publicEnv } from "@/lib/env";
import { isProtectedPath } from "@/lib/supabase/protectedRoutes";

/**
 * Paths under this prefix require an authenticated Supabase session. In the
 * App Router, route groups `(auth)`, `(app)` and `(protected)` are **not**
 * reflected in the URL, so gating happens on the literal URL prefix
 * `/dashboard` (and future protected segments added inside
 * `app/(app)/(protected)/`). Extend `PROTECTED_PREFIXES` rather than the
 * negative matcher in `proxy.ts` when adding new protected pages — that way,
 * the proxy keeps running on all app routes but only *redirects* for
 * known-protected ones.
 */
const PUBLIC_AUTH_PATHS = new Set(["/login", "/signup", "/callback"]);

/**
 * A redirect that still carries everything `@supabase/ssr` wrote during this
 * request: the rotated auth cookies, and the no-store headers it passes to
 * `setAll`.
 *
 * `NextResponse.redirect(url)` is a BRAND-NEW response. Returning one throws
 * away `supabaseResponse` — and Supabase has by then already rotated the
 * refresh token server-side and spent the old one, so the browser is left
 * presenting a token the server will not accept again. That is the "random
 * logout" shape the module comment below warns about, arrived at from the
 * other direction (#241). On the signed-out branch the discarded writes are
 * `maxAge: 0` deletions, so dropping them strands chunked auth cookies.
 *
 * Two details that are not obvious:
 *
 *   - Cookies are copied through the cookie JAR, not by copying the
 *     `set-cookie` header. `ResponseCookies` parses the header once when it is
 *     constructed, so a response built by appending raw `set-cookie` strings
 *     serves them to the browser correctly but reports `cookies.get(name)` as
 *     `undefined` — which would leave every reader, tests included, blind.
 *
 *   - Headers are taken from what the library handed to `setAll`, NOT copied
 *     off `supabaseResponse`. That response also carries Next's own
 *     `x-middleware-next` / `x-middleware-override-headers` /
 *     `x-middleware-request-*` plumbing, which instructs Next to continue to
 *     the route with rewritten request headers. On a 307 there is no route to
 *     continue to; copying the header set wholesale is the way this fix breaks
 *     redirecting altogether.
 */
function redirectPreservingSession(
  url: URL,
  from: NextResponse,
  sessionHeaders: Record<string, string>,
): NextResponse {
  const redirect = NextResponse.redirect(url);
  from.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
  Object.entries(sessionHeaders).forEach(([name, value]) =>
    redirect.headers.set(name, value),
  );
  return redirect;
}

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
 * EVERY exit — the two redirects included — must hand back what step 2 wrote.
 * `redirectPreservingSession` is how the redirects do it, and
 * `tests/unit/middleware-redirect-session.test.mjs` enumerates the returns in
 * this function to make sure a new branch cannot quietly skip it.
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
  // What the library handed to `setAll` this request, kept so a redirect exit
  // can carry it too. Recorded rather than read back off `supabaseResponse`,
  // for the reason spelled out on `redirectPreservingSession`.
  let sessionHeaders: Record<string, string> = {};

  const supabase = createServerClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      // The library ships no `secure` in `DEFAULT_COOKIE_OPTIONS`, so the
      // refreshed session cookies this proxy writes on EVERY request went out
      // without it. Same gate and same reasoning as `lib/supabase/server.ts`,
      // which spells it out — including why `httpOnly` stays `false`.
      cookieOptions: { secure: process.env.NODE_ENV === "production" },
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
          sessionHeaders = { ...sessionHeaders, ...headers };
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
    return redirectPreservingSession(url, supabaseResponse, sessionHeaders);
  }

  if (user && PUBLIC_AUTH_PATHS.has(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return redirectPreservingSession(url, supabaseResponse, sessionHeaders);
  }

  return supabaseResponse;
}
