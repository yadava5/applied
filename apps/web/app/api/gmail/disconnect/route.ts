import { NextResponse, type NextRequest } from "next/server";

import { disconnectGmail } from "@/lib/gmail/server";

/**
 * Disconnect Gmail. The settings page posts a native `<form>` here; we call
 * the backend (which revokes the grant at Google and deletes the encrypted
 * token) and redirect back to the settings page with the outcome flag.
 *
 * POST (not GET) so the revocation can never be triggered by a prefetch or a
 * cross-site image/link.
 */
export async function POST(request: NextRequest) {
  const { origin } = new URL(request.url);
  const ok = await disconnectGmail();

  const back = new URL("/settings", origin);
  back.searchParams.set("gmail", ok ? "disconnected" : "error");
  return NextResponse.redirect(back, { status: 303 });
}
