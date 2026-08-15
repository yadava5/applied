import { NextResponse, type NextRequest } from "next/server";

import {
  RECOVERY_MARKER_COOKIE,
  RECOVERY_MARKER_VALUE,
  recoveryMarkerCookieOptions,
} from "@/lib/auth/recoverySession";
import { expireSpentPkceVerifierCookies } from "@/lib/supabase/pkceVerifierCookies";
import { createClientWithSessionHeaders } from "@/lib/supabase/server";

/**
 * Where a password-recovery email lands.
 *
 * It does the same job as `app/(auth)/callback/route.ts` — exchange the PKCE
 * `?code=` for a session, server-side, so the cookies are set through the
 * redirect — and it is a SEPARATE route on purpose, for two reasons:
 *
 *  1. `/callback` is in `PUBLIC_AUTH_PATHS` (`lib/supabase/middleware.ts`), so
 *     the proxy redirects anyone who ALREADY has a session away from it, to
 *     `/dashboard`, before the handler ever runs. A signed-in user clicking a
 *     recovery link would therefore never reach the exchange. (That is a
 *     pre-existing latent bug for re-doing OAuth while signed in, too — it is
 *     flagged rather than fixed in passing, since that file belongs to another
 *     track this week.)
 *  2. `/callback` forwards to an arbitrary `?redirect=` path. A recovery code
 *     has exactly one destination and should not be offered a choice.
 *
 * On success it writes the recovery marker — see `lib/auth/recoverySession.ts`
 * for what that is and why it is not the token's `amr` claim. This handler is
 * the only writer of it in the app: the marker means "this browser turned a
 * recovery link into a session", and this is the one place that can happen.
 *
 * The redirect out of here is a bare `/reset-password` — no code, no token, no
 * status. Nothing about the exchange is worth putting in a URL that the address
 * bar keeps, that an RSC navigation repeats, and that a `Referer` header could
 * carry onward. The page decides what to show from the session and the marker,
 * which between them describe every way this can fail — an expired link, one
 * already used, or one opened in a browser that never requested it (the PKCE
 * verifier cookie lives in the requesting browser, so the exchange can only
 * complete there) — and all three deserve the same sentence anyway.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const destination = NextResponse.redirect(new URL("/reset-password", origin));

  // No code, or Supabase bounced an error back instead of one: fall through
  // with no marker and let the page say the link has expired. The provider's
  // wording is deliberately not forwarded.
  if (!code || searchParams.has("error") || searchParams.has("error_code")) {
    return destination;
  }

  const { supabase, applySessionHeaders } =
    await createClientWithSessionHeaders();

  /**
   * Every exit from here on. Both halves ride the SAME already-constructed
   * `destination`: the no-store headers the exchange asked for (#242), and the
   * expiry of the verifier cookies it just spent (#321). A recovery link is
   * the flow most likely to be opened twice — once from the mail client's
   * preview, once from the real browser — so the failure branch below is not
   * hypothetical, and it is the branch `@supabase/ssr` flushes nothing on.
   */
  const finish = (response: NextResponse) =>
    expireSpentPkceVerifierCookies(request, applySessionHeaders(response));

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) return finish(destination);

  // Written onto the response being returned, not into the `next/headers`
  // store — the same way `lib/supabase/middleware.ts` writes the refreshed
  // Supabase cookies. The response object here is built before the exchange,
  // and a mutation of the request-scoped store is not guaranteed to reach an
  // already-constructed `Response`; putting it directly on `destination`
  // removes the question. If this header did not land, every valid recovery
  // link would render "This link has expired" with every test still green.
  destination.cookies.set(
    RECOVERY_MARKER_COOKIE,
    RECOVERY_MARKER_VALUE,
    recoveryMarkerCookieOptions(process.env.NODE_ENV === "production"),
  );

  // Applied HERE, after the exchange, and not at the `NextResponse.redirect`
  // above: `destination` is constructed before the client exists, so there is
  // nothing to copy from at that point — no headers yet (#242), and no spent
  // verifier yet (#321). Same reason the marker cookie is written down here.
  return finish(destination);
}
