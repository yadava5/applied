"use client";

import { createBrowserClient } from "@supabase/ssr";

import { publicEnv } from "@/lib/env";

/**
 * Create a Supabase client for use inside Client Components.
 *
 * `@supabase/ssr`'s `createBrowserClient` reads/writes cookies via
 * `document.cookie`, which is the correct transport for browser-side auth
 * (and is picked up on the server by `createServerClient` + `proxy.ts` on
 * the next request).
 *
 * `cookieOptions.secure` is set for the same reason, and on the same gate, as
 * `lib/supabase/server.ts` — which spells it out: the library's
 * `DEFAULT_COOKIE_OPTIONS` has no `secure` key, so without this the cookies
 * written from a tab carry no `Secure` attribute. `httpOnly` is left at the
 * library's `false` on purpose; THIS client is why, since `document.cookie`
 * cannot see an HttpOnly cookie.
 */
export function createClient() {
  return createBrowserClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    { cookieOptions: { secure: process.env.NODE_ENV === "production" } },
  );
}
