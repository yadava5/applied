import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";
import { createAdminClient, deletionEnabled } from "@/lib/supabase/admin";
import { runAccountDeletion } from "@/lib/account/deletion";
import { serverEnv } from "@/lib/env.server";

/**
 * Delete the caller's own account. This is the server side of the Settings
 * "danger zone": the browser has already gated it behind a typed confirmation.
 *
 * The handler's only job is to bind the two privileged effects to the real
 * world — asking the backend to purge the caller's rows, and destroying the
 * Supabase auth user. The *ordering* between them, which is where the
 * data-loss bug lived (#214), is `lib/account/deletion.ts` so it can be
 * executed by a test without a Next runtime or a service-role key. See that
 * file for why a failed purge must never be followed by `deleteUser`.
 *
 * If the deployment has no service-role key, deletion can't run — we return an
 * honest 501 so the UI can tell the user plainly rather than pretend it
 * worked. That backstop stays; `GET` below is what stops the user meeting it
 * only after typing DELETE (#218).
 */

/**
 * Readiness probe: can this deployment delete an account at all?
 *
 * Deliberately unauthenticated. It reveals one boolean about the deployment's
 * own configuration — no user data, no key, not even whether an account
 * exists — and being reachable without a session is the point: it lets a
 * production smoke test assert the capability against the deployed origin
 * without deleting anything, which is the check whose absence let #218 ship.
 * The Settings page reads the same flag server-side, so the button and the
 * probe can never disagree.
 */
export async function GET() {
  return NextResponse.json({ deletionEnabled: deletionEnabled() });
}

export async function POST() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ detail: "Not signed in." }, { status: 401 });
  }

  const admin = createAdminClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  const { status, body } = await runAccountDeletion({
    // No token means we cannot ask the backend to remove anything, so there is
    // no purge to run — `null`, not a call that quietly succeeds at nothing.
    purge: token
      ? async () => {
          const { BACKEND_API_URL } = serverEnv();
          return fetch(`${BACKEND_API_URL}/account`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${token}` },
          });
        }
      : null,
    deleteAuthUser: admin ? () => admin.auth.admin.deleteUser(user.id) : null,
  });

  return NextResponse.json(body, { status });
}
