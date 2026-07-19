import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { serverEnv } from "@/lib/env";

/**
 * Delete the caller's own account. This is the server side of the Settings
 * "danger zone": the browser has already gated it behind a typed confirmation.
 *
 * Flow:
 *   1. Identify the caller from their Supabase session (never trust a client id).
 *   2. Best-effort ask the backend to purge their rows + revoke Gmail.
 *   3. Delete the auth user with the service-role admin client.
 *
 * If the deployment has no service-role key configured, deletion can't run —
 * we return an honest 501 so the UI can tell the user plainly rather than
 * pretend it worked.
 */
export async function POST() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ detail: "Not signed in." }, { status: 401 });
  }

  const admin = createAdminClient();
  if (!admin) {
    return NextResponse.json(
      {
        detail:
          "Account deletion isn’t enabled on this deployment yet. Email the admin to have your data removed.",
      },
      { status: 501 },
    );
  }

  // Best-effort backend cleanup — ignore failures so a missing/again-deployed
  // endpoint never blocks the user from removing their auth account.
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    const { BACKEND_API_URL } = serverEnv();
    if (session?.access_token) {
      await fetch(`${BACKEND_API_URL}/account`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session.access_token}` },
      }).catch(() => undefined);
    }
  } catch {
    /* non-fatal — proceed to auth deletion. */
  }

  const { error } = await admin.auth.admin.deleteUser(user.id);
  if (error) {
    return NextResponse.json({ detail: "Couldn’t delete the account. Try again." }, { status: 502 });
  }

  return NextResponse.json({ deleted: true }, { status: 200 });
}
