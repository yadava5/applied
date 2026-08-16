import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

import { publicEnv } from "@/lib/env";

/**
 * Create a Supabase client for Server Components, Server Actions, and Route
 * Handlers, together with the headers `@supabase/ssr` wants on any response
 * that carries the cookies it wrote.
 *
 * `cookies()` is async in Next.js 16, so the factory itself is async.
 *
 * `setAll` is wrapped in a try/catch because Server Components cannot mutate
 * cookies — attempting to do so throws. This is the pattern the Supabase
 * docs recommend: let the proxy (see `proxy.ts` + `lib/supabase/middleware`)
 * handle the session refresh on every request; the server client there only
 * needs to **read** the resulting cookies.
 *
 * `setAll`'s SECOND PARAMETER (#242)
 * ----------------------------------
 * Since `@supabase/ssr` 0.12.x the library calls `setAll(cookies, headers)`,
 * where `headers` is `Cache-Control: private, no-cache, no-store,
 * must-revalidate, max-age=0` + `Expires: 0` + `Pragma: no-cache` — the
 * directives that stop a shared cache serving one user's session token to
 * another. `lib/supabase/middleware.ts` applies them to the response it owns;
 * this factory has no response to put them on, because `createClient()` hands
 * back a Supabase client and the caller builds its own `NextResponse`
 * afterwards. `next/headers`' `headers()` is read-only, so there is no
 * `cookieStore` equivalent to write them into either.
 *
 * WHAT THAT COST, MEASURED. The callers that WRITE session cookies rather than
 * read them are the two PKCE handlers, `app/(auth)/callback/route.ts` and
 * `app/(auth)/reset-password/callback/route.ts`. Driven against a local fake
 * auth server on a production build (`next build && next start`), a successful
 * exchange returned:
 *
 *     HTTP/1.1 307 Temporary Redirect
 *     location:   /dashboard
 *     set-cookie: sb-<ref>-auth-token=<the INITIAL session>
 *                              <- no cache-control, expires or pragma at all
 *
 * and the same run showed `setAll` firing once with all three headers and
 * `cookieStore.set` SUCCEEDING — the catch below does not fire in a Route
 * Handler. (#242 reasoned that; it is now observed. The control, the same
 * request with no PKCE verifier cookie, returns the same 307 with no
 * `set-cookie` at all, which is what makes the first run an observation of a
 * real exchange rather than of nothing happening.)
 *
 * WHAT THE EDGE ADDS, ALSO MEASURED. The argument for leaving this alone was
 * that a 307 is not a status a cache may store heuristically, so with no
 * explicit freshness header nothing licenses storing it. That argument does not
 * survive contact with the platform. Probing the deployed app on a branch of
 * this same handler that carries no session — `/callback` with a deliberately
 * invalid `code`, which 307s to `/login?error=…` — Vercel returns:
 *
 *     HTTP/2 307
 *     cache-control: public, max-age=0, must-revalidate
 *     x-vercel-cache: MISS
 *
 * Identical on both production hosts, on both code-less branches, and identical
 * to what the prerendered routes get. So when this handler sets no
 * `Cache-Control`, the edge supplies one — and it says `public`, which is
 * precisely a licence for a SHARED cache to store the response. The heuristic
 * argument is moot because nothing is left to heuristics.
 *
 * `max-age=0, must-revalidate` means a stored copy cannot be reused without
 * revalidating, so this is not #234's `s-maxage=31536000`. It is still the
 * wrong header on a response that returns a user's initial session, and it is
 * the platform's default rather than anyone's decision — the kind that changes
 * under you. The limit of the measurement, stated plainly: the probe could not
 * carry a successful exchange without a real sign-in, so the SUCCESS branch's
 * edge header is inferred from the two failure branches and the static routes
 * agreeing, not observed. Setting the header ourselves removes the question.
 *
 * So the headers are collected here and handed to the caller as
 * {@link createClientWithSessionHeaders}'s `applySessionHeaders`, which is
 * additive: `createClient()` keeps its old shape and the Server Component
 * callers — which cannot set a header anyway, and whose cookie writes the catch
 * below swallows — are untouched.
 */
export async function createClientWithSessionHeaders() {
  const cookieStore = await cookies();

  // What the library handed to `setAll` during this request. Accumulated
  // rather than assigned: `setAll` can fire more than once (a PKCE exchange
  // clears the verifier and writes the session), and a later call must not
  // erase what an earlier one asked for.
  let sessionHeaders: Record<string, string> = {};

  const supabase = createServerClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      // `Secure` ON THE AUTH COOKIES (CASA 2.3.1 / 2.3.2)
      // -------------------------------------------------
      // `@supabase/ssr` 0.12.4's `DEFAULT_COOKIE_OPTIONS`
      // (`dist/main/utils/constants.js`) is exactly `{ path: "/",
      // sameSite: "lax", httpOnly: false, maxAge: 400 * 24 * 60 * 60 }`. There
      // is no `secure` key in it at all, and nothing else supplies one — so
      // every session cookie this app wrote went out without `Secure`, which
      // is a session token a browser will replay over plain HTTP. Both cookie
      // paths in the library build their options as `{ ...DEFAULT_COOKIE_OPTIONS,
      // ...options.cookieOptions, maxAge }` (`applyServerStorage`, and the
      // browser storage's `setItem`), so what is set here is what goes on the
      // wire. `sameSite: "lax"` and `path: "/"` already come from the defaults;
      // `tests/unit/cookie-attributes.test.mjs` asserts all three against the
      // installed library rather than trusting that.
      //
      // `NODE_ENV` is the gate, for the same reason
      // `lib/auth/recoverySession.ts` gives for the recovery marker: every
      // deployed environment gets it and only `next dev` does not. A local
      // `next start` is `NODE_ENV=production` and so sets it over plain HTTP —
      // which is fine, because browsers treat `http://localhost` as a secure
      // origin and store `Secure` cookies from it.
      //
      // `httpOnly` is deliberately NOT raised here and must stay the library's
      // `false`. The browser client (`lib/supabase/client.ts`) carries the
      // session in `document.cookie`; an HttpOnly auth cookie is invisible to
      // it and breaks sign-in outright. That is a compensating-control
      // decision, not an oversight.
      cookieOptions: { secure: process.env.NODE_ENV === "production" },
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(
          cookiesToSet: {
            name: string;
            value: string;
            options: CookieOptions;
          }[],
          headers: Record<string, string>,
        ) {
          // Recorded BEFORE the cookie writes. In a Server Component the loop
          // below throws on the first `set` and the catch swallows it; the
          // headers are still what the library asked for, and recording them
          // first means the two cannot drift apart depending on where this ran.
          sessionHeaders = { ...sessionHeaders, ...headers };
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Server Components cannot set cookies. The proxy middleware is
            // responsible for refreshing the Supabase session, so it is safe
            // to no-op here.
          }
        },
      },
    },
  );

  /**
   * Put the no-store headers on a response the caller is about to return.
   *
   * A no-op when the library never wrote a cookie, so a route can call it on
   * every exit without first asking whether an exchange happened — which is
   * the point, since "did this branch write a session?" is exactly the question
   * a future edit gets wrong.
   *
   * Typed structurally rather than as `NextResponse` so this module does not
   * have to import `next/server`; anything with a `Headers` will do.
   */
  function applySessionHeaders<T extends { headers: Headers }>(response: T): T {
    Object.entries(sessionHeaders).forEach(([name, value]) =>
      response.headers.set(name, value),
    );
    return response;
  }

  return { supabase, applySessionHeaders };
}

/**
 * The Supabase client alone, for the callers that only READ the session —
 * Server Components, the request-scoped DAL in `lib/supabase/auth.ts`, and any
 * route that never causes a cookie write.
 *
 * A caller that returns a response which may carry cookies the library wrote
 * wants {@link createClientWithSessionHeaders} instead.
 */
export async function createClient() {
  const { supabase } = await createClientWithSessionHeaders();
  return supabase;
}
