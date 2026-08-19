/**
 * Request-scoped auth reads (a tiny Data Access Layer).
 *
 * Every server render of an `(app)` route needs the current user and/or the
 * Supabase access token, and several places asked for them independently:
 * the protected layout calls `getUser()`, then the page (Settings, the Gmail
 * helpers, the API client factory) each re-read the user/session — so a single
 * Settings render fanned out to ~3 Supabase Auth round-trips.
 *
 * `getUser()` is the expensive one: `@supabase/ssr` verifies the JWT against
 * the Supabase Auth server on every call (a network round-trip), unlike
 * `getSession()` which only decodes the cookie. Wrapping both in React's
 * `cache()` memoizes them for the duration of one server request, so the
 * layout + page share ONE verified `getUser()` and ONE session read no matter
 * how many components ask.
 *
 * This is purely a de-duplication of reads within a single render pass — it
 * does not cache across requests and does not weaken any check: the layout's
 * defence-in-depth `redirect('/login')` and the backend's own JWT
 * verification are both untouched.
 *
 * Server-only: transitively imports `@/lib/supabase/server` → `next/headers`,
 * so importing this from a Client Component fails the build (same guarantee
 * `lib/api/server.ts` relies on).
 */
import { cache } from "react";
import type { Session, User } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/server";

/**
 * The authenticated user for this request, verified against Supabase Auth,
 * memoized so repeat callers in the same render share one round-trip. Returns
 * `null` when there is no valid session.
 */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
});

/**
 * The user's display name for shell chrome (the rail footer, the mobile
 * menu). Pure — no request read; callers already hold the user.
 *
 * The chain: `display_name` (written by `/signup`'s optional Name field and by
 * Settings → Profile; the signup form omits the key rather than storing "",
 * and an empty string is UNSET here, not a name) → `full_name` (written by
 * Google sign-in, which is live — `components/auth/GoogleSignInButton.tsx`)
 * → `null`. Callers fall back to the email on `null` — the rail must never
 * render a blank identity row.
 *
 * What Google actually writes, read off the one `auth.identities` row this
 * project has for the google provider (linked onto an email-primary account,
 * so this is an observation and not a spec): `full_name`, `name` (the same
 * string), `email`, `avatar_url`, `picture`, `provider_id`, `sub`, `iss`,
 * `email_verified`, `phone_verified`. Supabase merges that into
 * `user_metadata`, so `full_name` is populated there and this chain needs no
 * provider-specific branch.
 */
export function userDisplayName(user: User | null): string | null {
  const meta = (user?.user_metadata ?? {}) as Record<string, unknown>;
  for (const key of ["display_name", "full_name"]) {
    const value = meta[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/**
 * The Supabase session for this request (cookie-decoded; no network call),
 * memoized for the render pass.
 */
export const getCurrentSession = cache(async (): Promise<Session | null> => {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session;
});

/**
 * The current request's Supabase access token, or `null` when signed out.
 * Convenience over {@link getCurrentSession} for the many callers that only
 * need the bearer token to forward to the FastAPI backend.
 */
export const getAccessToken = cache(async (): Promise<string | null> => {
  const session = await getCurrentSession();
  return session?.access_token ?? null;
});
