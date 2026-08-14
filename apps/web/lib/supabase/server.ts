import { cookies } from "next/headers";
import { createServerClient, type CookieOptions } from "@supabase/ssr";

import { publicEnv } from "@/lib/env";

/**
 * Create a Supabase client for Server Components, Server Actions, and Route
 * Handlers.
 *
 * `cookies()` is async in Next.js 16, so the factory itself is async.
 *
 * `setAll` is wrapped in a try/catch because Server Components cannot mutate
 * cookies — attempting to do so throws. This is the pattern the Supabase
 * docs recommend: let the proxy (see `proxy.ts` + `lib/supabase/middleware`)
 * handle the session refresh on every request; the server client here only
 * needs to **read** the resulting cookies.
 *
 * WHY `setAll`'s SECOND PARAMETER IS ACCEPTED AND NOT USED (#242)
 * --------------------------------------------------------------
 * Since `@supabase/ssr` 0.12.x the library calls `setAll(cookies, headers)`,
 * where `headers` is `Cache-Control: private, no-cache, no-store,
 * must-revalidate, max-age=0` + `Expires: 0` + `Pragma: no-cache` — the
 * directives that stop a shared cache serving one user's session token to
 * another. `lib/supabase/middleware.ts` applies them; this factory cannot.
 * `next/headers`' `headers()` is read-only, and there is no response object
 * here to put them on: `createClient()` hands back a Supabase client, and the
 * caller builds its own `NextResponse` afterwards. Applying them would mean
 * changing what this function returns, i.e. every call site.
 *
 * WHAT THAT COSTS, MEASURED. The one caller that writes session cookies rather
 * than reading them is `app/(auth)/callback/route.ts`, the PKCE handler. Driven
 * against a local fake auth server on a production build, a successful exchange
 * returns:
 *
 *     HTTP/1.1 307 Temporary Redirect
 *     location:   /dashboard
 *     set-cookie: sb-<ref>-auth-token=<the INITIAL session>
 *                              <- no cache-control, expires or pragma at all
 *
 * So `cookieStore.set` does succeed in a Route Handler (#242 reasoned this but
 * could not observe it), and the response really does carry a session with no
 * cache directive. It is not, however, reachable by a shared cache: 307 is not
 * one of the status codes a cache may store heuristically, so with no explicit
 * freshness header there is nothing to license storing it — and the Vercel CDN
 * stores a function response only when it opts in with `s-maxage` /
 * `CDN-Cache-Control`. That is why #242 stays open rather than being fixed with
 * an API change: the header is missing, and nothing currently caches it.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
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
          // Declared so the next reader does not have to re-derive #242 from
          // the library source. Deliberately unused — see the block comment
          // above. The disable is per-line rather than an `argsIgnorePattern`
          // in eslint.config.mjs: a config change would silence every unused
          // argument in the app to buy silence for this one.
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          _headers: Record<string, string>,
        ) {
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
}
