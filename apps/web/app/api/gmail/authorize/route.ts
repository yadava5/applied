import { NextResponse, type NextRequest } from "next/server";

import { getGmailAuthorizeUrl } from "@/lib/gmail/server";

/**
 * Kick off the Gmail connect flow.
 *
 * The browser navigates here directly from every surface that offers the
 * connection — Settings' Connect button, `/inbox`'s not-connected state, the
 * dashboard's "Connect Gmail" tile, and the chain off a first Google sign-in.
 * None of them is a link to a page that then holds a button. We ask
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
 * The last four are the Settings-initiated landings; `?from=` redirects them
 * to `/dashboard` instead, and the `from` block below says which values do
 * that and why. The FIRST one is deliberately not redirected: a caller with no
 * session has to sign in before anything can be connected at all, and Settings
 * is where the Connect control waits on the other side of that — which is also
 * what `tests/e2e/connect.spec.ts` pins.
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

  // WHERE THIS CONNECT CAME FROM — the only thing `?from=` is for, and the
  // whole vocabulary is here. Three cases, two values:
  //
  //   `signin`     the PKCE callback chained us here straight off a first
  //                Google sign-in (#494 shape (b), wired by #510).
  //   `dashboard`  the dashboard's "Connect Gmail" tile was pressed (#494).
  //   absent       Settings' own Connect button, `/inbox`'s not-connected
  //                state, or any older link. Everything returns to Settings.
  //
  // TWO VALUES RATHER THAN ONE, even though today they route identically, and
  // the reason is that they are different facts about the reader. `signin`
  // describes a redirect NOBODY ASKED FOR: the person pressed "Sign in with
  // Google" and the app carried them onward, which is exactly why dropping
  // them on a Settings error page reads as the product malfunctioning on the
  // first screen of a brand-new account. `dashboard` describes a deliberate
  // press of a control labelled "Connect Gmail" by someone already inside the
  // product. Folded into one flag, the first surface that wants its own
  // wording, its own decline path, or its own place to return to would have to
  // reconstruct the distinction from nothing.
  //
  // Neither value can widen anything. They are read only to choose between two
  // same-origin paths this file spells out in full, and what crosses to the
  // backend is a BOOLEAN — never a path — so no caller can name a destination.
  const from = searchParams.get("from");
  const fromSignIn = from === "signin";
  const fromDashboard = from === "dashboard";

  // The one decision both values make: this connect belongs to the dashboard,
  // on success and on failure alike.
  //
  // On SUCCESS the flag travels to the backend, which signs it into the OAuth
  // state so the CALLBACK lands the browser on `/dashboard` instead of
  // Settings (#510). Before that it stopped here and only chose where a LOCAL
  // failure bounced to, which meant a connect that SUCCEEDED still ended on a
  // preferences page.
  const returnsToDashboard = fromSignIn || fromDashboard;

  const result = await getGmailAuthorizeUrl(origin, returnsToDashboard);
  const onFailure = (flag: string) => {
    // Every failure below is written for someone already inside the product
    // who chose to connect: bouncing them to `/settings?gmail=...` puts the
    // explanation next to the button they just pressed. That is right for a
    // Settings connect and wrong for both of the flags above — one would make
    // a new account's first screen a Settings error page, and the other would
    // answer a dashboard click by changing the subject.
    if (returnsToDashboard) {
      return NextResponse.redirect(new URL("/dashboard", origin));
    }
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
