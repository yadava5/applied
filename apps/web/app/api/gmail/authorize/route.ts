import { NextResponse, type NextRequest } from "next/server";

import { getGmailAuthorizeUrl } from "@/lib/gmail/server";

/**
 * Kick off the Gmail connect flow.
 *
 * The browser navigates here (a plain link on the settings page). We ask
 * the backend — server-side, carrying the user's Supabase JWT — for the
 * Google consent URL, then 302 the browser to Google. Doing the token-
 * bearing call here keeps the JWT and `BACKEND_API_URL` off the client,
 * and the browser only ever sees a top-level redirect to accounts.google.com.
 *
 * If the backend has not been given its Google OAuth credentials yet (or is
 * unreachable), we bounce back to the settings page with `?gmail=unavailable`
 * rather than surfacing an error — an honest "not enabled yet" state.
 */
export async function GET(request: NextRequest) {
  const { origin } = new URL(request.url);

  const authorizeUrl = await getGmailAuthorizeUrl();
  if (!authorizeUrl) {
    const back = new URL("/settings", origin);
    back.searchParams.set("gmail", "unavailable");
    return NextResponse.redirect(back);
  }

  return NextResponse.redirect(authorizeUrl);
}
