/**
 * Server-side factory for the typed API client.
 *
 * Reads the Supabase session from the request cookie jar via
 * `@supabase/ssr` and forwards the access token to `createApiClient` so
 * every RSC / Route Handler / Server Action fetch carries the user's JWT.
 *
 * Usage inside an async Server Component:
 *
 * ```tsx
 * const api = await createServerApiClient();
 * const { data, error } = await api.GET("/auth/me");
 * ```
 *
 * Notes:
 * - This module is server-only: it imports `@/lib/supabase/server`, which
 *   in turn pulls `next/headers` / `cookies()`. Any Client Component that
 *   tries to import this file will fail the Next.js build with a clear
 *   "server-only API in client bundle" error, so no separate `server-only`
 *   guard is required.
 * - The Supabase server client already handles cookie-refresh semantics
 *   via `proxy.ts`; here we only need to READ the current session.
 * - `baseUrl` comes from `serverEnv().BACKEND_API_URL`, which is validated
 *   by zod at first access.
 */
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { serverEnv } from "@/lib/env.server";
import { getAccessToken } from "@/lib/supabase/auth";

/**
 * Build a typed API client carrying the caller's Supabase JWT (when the
 * session exists). Safe to call from any server-side async context; if
 * there is no authenticated session, the client is returned without an
 * `Authorization` header so unauthenticated endpoints like `/health`
 * still work.
 *
 * The access-token read is request-memoized (`lib/supabase/auth`), so calling
 * this multiple times in one render — the dashboard fetches summary + list —
 * does not re-read the session each time.
 */
export async function createServerApiClient(): Promise<ApiClient> {
  const token = await getAccessToken();

  const { BACKEND_API_URL } = serverEnv();

  return createApiClient({
    baseUrl: BACKEND_API_URL,
    token: token ?? undefined,
  });
}
