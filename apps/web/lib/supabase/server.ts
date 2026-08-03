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
