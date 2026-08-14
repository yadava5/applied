import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { publicEnv } from "@/lib/env";
import { serverEnv } from "@/lib/env.server";

/**
 * A privileged Supabase client bound to the service-role key. Server-only, and
 * used solely for admin operations the anon session cannot perform — today,
 * deleting the caller's own account (`auth.admin.deleteUser`).
 *
 * Returns `null` when `SUPABASE_SERVICE_ROLE_KEY` is not configured on this
 * deployment, so callers can degrade to an honest "not enabled" response
 * instead of crashing. The key is read via `serverEnv()` and never reaches the
 * browser.
 */
export function createAdminClient(): SupabaseClient | null {
  const { SUPABASE_SERVICE_ROLE_KEY } = serverEnv();
  if (!SUPABASE_SERVICE_ROLE_KEY) return null;

  return createClient(publicEnv.NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

/**
 * Whether this deployment can delete an account — the same question
 * `createAdminClient()` answers, asked out loud (#218).
 *
 * It exists so the Settings page and the `/api/account/delete` readiness probe
 * read one predicate instead of two copies of `!!SUPABASE_SERVICE_ROLE_KEY`.
 * Deliberately derived from `createAdminClient()` rather than from the env var
 * directly: the flag the UI trusts must be the same construction the delete
 * route depends on, or a future change to the client's requirements would
 * leave the button confidently enabled over a route that 501s.
 */
export function deletionEnabled(): boolean {
  return createAdminClient() !== null;
}
