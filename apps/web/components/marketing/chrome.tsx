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
 * "Get access" is the third same-tab case and for the same reason: it never
 * leaves the page at all.
 */
export const NEW_TAB = { target: "_blank", rel: "noopener noreferrer" } as const;

/**
 * The one persistent path for a visitor who is sold early. Access lives at
 * roughly 85% depth, and the rest of the nav is no use to a new reader —
 * "Sign in" belongs to the hundred seat-holders and "Live demo" leaves the
 * page — so somebody convinced at the first beat had no way to act for the
 * next several viewports. This is a quiet in-page anchor rather than a second
 * loud CTA: one path, always reachable, never competing with the real one.
 * `AccessSection` owns the target id and its scroll offset.
 */
export const ACCESS_ANCHOR = "#access";

const SYSTEM_CARD = "/system-card";

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
          <a
            href={ACCESS_ANCHOR}
            className="inline-flex min-h-11 items-center text-sm text-muted transition-colors hover:text-strong"
          >
            Get access
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

/**
 * The footer is a PRODUCT's, not a project's — recut 2026-08-19 at the
 * owner's direction ("this is for scaling purposes, and not a project
 * anymore"). What left, and why:
 *
 *   · "built and run by Ayush Yadav" — the maker's byline is what marks a
 *     page as a side project. The name still signs the work everywhere it
 *     should (the repo, the System Card); the footer is the product's.
 *   · the personal Gmail address — a raw mailto in a footer is a spam
 *     magnet and does not scale past one inbox. Superseded 2026-08-19: the
 *     seat ask no longer carries an address either. It resolves to
 *     `ACCESS.seatHref` (/signup), because the account list is the queue the
 *     cap sentence already describes. No landing surface renders a mailto.
 *   · "Live demo" — already in the nav on every page of this family; a
 *     footer that restates the nav is filler.
 *
 * What stays: Privacy (the homepage link Google's OAuth verification looks
 * for — do not remove it) and the System Card, which is a differentiator no
 * competitor can echo and earns a place in both the privacy phase's prose
 * and here, where product-trust links conventionally live.
 */
export function MarketingFooter() {
  return (
    <footer className="border-t border-line-soft">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-3 px-6 py-8 sm:flex-row sm:items-center">
        <span className="text-[0.8125rem] text-dim">© 2026 Applied</span>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[0.8125rem] text-dim">
          <a href="/privacy" {...NEW_TAB} className="transition-colors hover:text-strong">
            Privacy
          </a>
          <a href={SYSTEM_CARD} {...NEW_TAB} className="transition-colors hover:text-strong">
            System Card
          </a>
        </nav>
      </div>
    </footer>
  );
}
