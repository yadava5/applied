import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/Logo";

/**
 * The auth pages' shared front door: the lockup at display size assembling
 * over the page's greeting (`.auth-hero`, globals.css — the closing act's
 * stroke-draw applied to the brand asset itself). The header owns ALL of the
 * entrance; the form each page renders below it is deliberately outside the
 * choreography and interactive at first paint. Reduced motion renders the
 * composed lockup with the greeting already in place.
 *
 * Server component on purpose — the motion is pure CSS, so the one page in
 * the group that renders on the server (`/reset-password`) animates the same
 * way the client pages do.
 */
export function AuthHeader({
  title,
  intro,
}: {
  title: string;
  intro: ReactNode;
}) {
  return (
    <header className="auth-hero space-y-2">
      <Link
        href="/"
        aria-label="Applied — home"
        className="brand-logo-link mb-5 text-strong"
      >
        <Logo className="h-10 w-auto" />
      </Link>
      <h1 className="auth-hero__title text-3xl font-semibold tracking-tight">
        {title}
      </h1>
      <p className="auth-hero__intro text-[0.9375rem] text-muted">{intro}</p>
    </header>
  );
}
