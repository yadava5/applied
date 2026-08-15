import Link from "next/link";

import { Logo } from "@/components/brand/Logo";

/**
 * Shared chrome for the three landing candidates. One nav and one footer so
 * the variants differ only in how they stage the board and the claims.
 *
 * Same convention as the current landing (`app/page.tsx`): links that leave
 * the page for the live app or a document open in a NEW TAB so the pitch
 * survives behind them; signing in is the one deliberate same-tab move —
 * a second tab after auth strands the visitor on a stale marketing page.
 */
export const NEW_TAB = { target: "_blank", rel: "noopener noreferrer" } as const;

const SYSTEM_CARD = "/system-card";
const CONTACT = "aesh.03.23@gmail.com";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-50 border-b border-line-soft bg-background">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-6">
        <Link
          href="/"
          aria-label="Applied — home"
          className="brand-logo-link min-h-11 items-center text-strong"
        >
          <Logo className="h-6 w-auto" />
        </Link>
        <nav className="flex items-center gap-5">
          <a
            href="/demo"
            {...NEW_TAB}
            className="hidden min-h-11 items-center text-sm text-muted transition-colors hover:text-strong sm:inline-flex"
          >
            Live demo
          </a>
          <Link
            href="/login"
            className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 py-1.5 text-sm text-foreground transition-colors hover:border-line-strong hover:text-strong"
          >
            Sign in
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-line-soft">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-3 px-6 py-8 sm:flex-row sm:items-center">
        <span className="text-[0.8125rem] text-dim">
          Applied · built and run by Ayush Yadav
        </span>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[0.8125rem] text-dim">
          {/* Privacy stays here in every variant: it is the homepage link
              Google's OAuth verification looks for. Do not remove it. */}
          <a href="/privacy" {...NEW_TAB} className="transition-colors hover:text-strong">
            Privacy
          </a>
          <a href={SYSTEM_CARD} {...NEW_TAB} className="transition-colors hover:text-strong">
            System Card
          </a>
          <a href="/demo" {...NEW_TAB} className="transition-colors hover:text-strong">
            Live demo
          </a>
          <a href={`mailto:${CONTACT}`} className="transition-colors hover:text-strong">
            {CONTACT}
          </a>
        </nav>
      </div>
    </footer>
  );
}
