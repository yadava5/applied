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
 *
 * `origin` does double duty now (#333): it is where we send the user on a
 * failure, and it is what we ask the backend to return them to on success.
 * The backend used to answer the second question from its own
 * `JOBTRACKER_WEB_APP_URL`, which is a different Vercel project's idea of
 * which host we are — it named a pre-rename alias for 26 days and every
 * returning user landed signed out, because cookies are scoped to a host.
 * This request arrived on the host whose cookie the user actually holds, so
 * it is the only reliable answer, and it is the one we send.
 */
export async function GET(request: NextRequest) {
  const { origin } = new URL(request.url);
  const result = await getGmailAuthorizeUrl(origin);

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
