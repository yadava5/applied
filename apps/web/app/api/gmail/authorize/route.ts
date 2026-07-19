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
 * When we can't get a consent URL we bounce back with an HONEST outcome
 * rather than a single misleading "unavailable" for every cause:
 *
 *   - no session      → `/login?redirect=/settings` (sign in, then retry)
 *   - JWT rejected    → `/settings?gmail=auth`       (session/auth problem)
 *   - not configured  → `/settings?gmail=unavailable`(Gmail off on this deploy)
 *   - backend error   → `/settings?gmail=error`      (transient — try again)
 *
 * This is the fix for the "Can't connect Gmail" dead end: a signed-in tester
 * whose token was rejected used to be told "Gmail isn't enabled on this
 * deployment yet", which is both wrong and actionless.
 */
export async function GET(request: NextRequest) {
  const { origin } = new URL(request.url);
  const result = await getGmailAuthorizeUrl();

  if (result.kind === "ok") {
    return NextResponse.redirect(result.url);
  }

  if (result.kind === "unauthenticated") {
    const login = new URL("/login", origin);
    login.searchParams.set("redirect", "/settings");
    return NextResponse.redirect(login);
  }

  const flag =
    result.kind === "auth" ? "auth" : result.kind === "unavailable" ? "unavailable" : "error";
  const back = new URL("/settings", origin);
  back.searchParams.set("gmail", flag);
  return NextResponse.redirect(back);
}
