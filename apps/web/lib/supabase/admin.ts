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
