"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { safeRedirectPath } from "@/lib/auth/redirect";
import { armBoot } from "@/lib/boot/flag";
import { createClient } from "@/lib/supabase/client";

/**
 * "Continue with Google" — Supabase Auth (Google OAuth provider) sign-in.
 *
 * `signInWithOAuth({ provider: 'google', options: { skipBrowserRedirect: true }})`
 * builds the `/auth/v1/authorize` URL client-side (writing the PKCE
 * `code_verifier` cookie that the SSR `/callback` route later reads for
 * `exchangeCodeForSession`) and returns it as `data.url` **without** navigating.
 * We then hand the browser to that URL with a top-level navigation, which 302s
 * to Google's consent screen and back to `/callback`.
 *
 * NOTE: do NOT `fetch()` `data.url` to "pre-flight" it. `/authorize` is a
 * redirect to Google's HTML consent page, not a JSON API — a cross-origin fetch
 * follows to accounts.google.com and fails CORS/503, which previously surfaced
 * as a bogus "couldn't reach Google" error even though the provider was fine.
 * `skipBrowserRedirect` does NOT make `/authorize` return JSON. A top-level
 * navigation is what Google's OAuth endpoint expects.
 */

const NOT_CONFIGURED_MESSAGE = "Google sign-in isn't configured yet.";

function GoogleGlyph() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

/**
 * A hairline "or" divider matching the monochrome system's mono label voice.
 * Purely decorative, so it is hidden from assistive tech.
 */
export function AuthOrDivider() {
  return (
    <div className="flex items-center gap-3" aria-hidden="true">
      <span className="h-px flex-1 bg-line" />
      <span className="label-mono">or</span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

export function GoogleSignInButton({
  redirectTo = "/dashboard",
  label = "Continue with Google",
}: {
  /** Same-origin path to land on after the code-exchange. */
  redirectTo?: string;
  label?: string;
}) {
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setError(null);
    setIsRedirecting(true);

    // Refuse open redirects: only ever return to a same-origin path. The check
    // is `lib/auth/redirect.ts` — `startsWith("/")` used to stand here and let
    // a protocol-relative `//evil.com` straight through to `/callback`.
    const safeRedirect = safeRedirectPath(redirectTo);
    const callbackUrl = new URL("/callback", window.location.origin);
    callbackUrl.searchParams.set("redirect", safeRedirect);

    const supabase = createClient();
    const { data, error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: callbackUrl.toString(),
        // Get the URL back instead of navigating — see the file header.
        skipBrowserRedirect: true,
      },
    });

    if (oauthError || !data?.url) {
      setError(NOT_CONFIGURED_MESSAGE);
      setIsRedirecting(false);
      return;
    }

    // Arm the post-auth Triage boot for the return document (storage only —
    // this page is about to be replaced, so the same-tab event would only
    // race the redirect). BOOT_INIT_SCRIPT raises the cover pre-paint when
    // /callback lands us back on the target route.
    armBoot(safeRedirect, { notify: false });

    // `data.url` is Supabase's `/auth/v1/authorize` URL. Hand the browser to it
    // via a top-level navigation — it 302s to Google's consent screen and back
    // to /callback (which runs exchangeCodeForSession with the PKCE verifier
    // cookie written when the URL was built above). Do NOT pre-flight it with
    // `fetch`: `/authorize` redirects to Google's HTML consent page, so fetching
    // it follows cross-origin to accounts.google.com and fails CORS/503 — which
    // is exactly what surfaced as the bogus "couldn't reach Google sign-in"
    // error. A top-level navigation is what Google's OAuth endpoint expects.
    window.location.assign(data.url);
  }

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        className="w-full"
        onClick={handleClick}
        disabled={isRedirecting}
      >
        <GoogleGlyph />
        {isRedirecting ? "Connecting…" : label}
      </Button>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject-ink"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
