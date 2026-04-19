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
 */
export function createClient() {
  return createBrowserClient(
    publicEnv.NEXT_PUBLIC_SUPABASE_URL,
    publicEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  );
}
