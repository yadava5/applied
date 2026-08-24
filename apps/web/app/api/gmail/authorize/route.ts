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
 *   - beta full       → `/settings?gmail=capacity`   (ask for a place)
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
  const { origin, searchParams } = new URL(request.url);
  const result = await getGmailAuthorizeUrl(origin);

  // `?from=signin` means the PKCE callback chained us here straight off a
  // Google sign-in (#494), rather than the user clicking Connect in Settings.
  //
  // It changes only WHERE A FAILURE LANDS, and it has to. Every failure below
  // is written for someone who is already inside the product and chose to
  // connect: bouncing them to `/settings?gmail=...` puts the explanation next
  // to the button they just pressed. Do that to a chained user and the very
  // first screen of their account is a Settings error page for something they
  // never asked for by name. They go to the dashboard instead — the place the
  // sign-in was heading before the chain got involved — and Settings keeps the
  // Connect button for whenever they want it.
  //
  // The flag cannot widen anything: it is read only to pick between two
  // same-origin paths this file spells out in full, and it is never forwarded
  // to the backend or used to build a URL.
  const fromSignIn = searchParams.get("from") === "signin";
  const onFailure = (flag: string) => {
    if (fromSignIn) return NextResponse.redirect(new URL("/dashboard", origin));
    const back = new URL("/settings", origin);
    back.searchParams.set("gmail", flag);
    return NextResponse.redirect(back);
  };

  if (result.kind === "ok") {
    return NextResponse.redirect(result.url);
  }

  if (result.kind === "unauthenticated") {
    const login = new URL("/login", origin);
    login.searchParams.set("redirect", "/settings");
    return NextResponse.redirect(login);
  }

  // `at_capacity` gets its own flag rather than folding into `error`: the
  // backend refused on purpose and the user has something to do about it
  // (write to the address in the banner). "Please try again" would be a lie
  // that costs us the person who wanted the product most.
  const flag =
    result.kind === "auth"
      ? "auth"
      : result.kind === "unavailable"
        ? "unavailable"
        : result.kind === "at_capacity"
          ? "capacity"
          : "error";
  return onFailure(flag);
}
