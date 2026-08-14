import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import {
  RECOVERY_MARKER_COOKIE,
  expiredRecoveryMarkerCookieOptions,
} from "@/lib/auth/recoverySession";

/**
 * Spend the recovery marker.
 *
 * The marker is proof of ONE thing — that this browser turned a recovery link
 * into a session — and a proof that outlives its use is a hole: without this,
 * the marker would sit in the browser for the rest of its ten minutes and
 * `/reset-password` would keep accepting whoever holds the next session in
 * that browser. `SetNewPasswordForm` calls this the moment `updateUser`
 * succeeds, which makes the proof single-use in practice as well as in intent.
 *
 * It is deliberately powerless: it reads no body, touches no session, returns
 * no content, and the only thing it can do is expire one cookie in the caller's
 * own browser. The `Origin` check is therefore about tidiness rather than
 * defence — the worst a cross-site caller could achieve is making someone
 * request a fresh reset link — but a state-changing endpoint that accepts
 * anyone's form post is a habit worth not forming.
 *
 * Best-effort by contract: the caller ignores the outcome, because the
 * password is already changed by the time this is called and a failure here
 * must never be reported as a failed reset.
 */
export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== new URL(request.url).origin) {
    return new NextResponse(null, { status: 403 });
  }

  const cookieStore = await cookies();
  cookieStore.set(
    RECOVERY_MARKER_COOKIE,
    "",
    expiredRecoveryMarkerCookieOptions(process.env.NODE_ENV === "production"),
  );

  return new NextResponse(null, { status: 204 });
}
