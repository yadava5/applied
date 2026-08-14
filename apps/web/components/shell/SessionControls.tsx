"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

/**
 * The session-edge controls. One sign-out implementation, two mount shapes:
 * the shell `TopBar` renders the button (every route below `lg`, every
 * non-board route above it); on the board at `lg`+, where TopBar yields to
 * the header row, that row's `⋯` menu carries sign-out through `useSignOut`
 * instead — a row-level button there is what wrapped the row at 1024 (#172).
 */

export function useSignOut() {
  const router = useRouter();
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function signOut() {
    // Guarded here, not only by a disabled button: the menu mount closes on
    // select, so nothing visual stops a second press mid-flight.
    if (isSigningOut) return;
    setIsSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    // Refresh so the proxy re-evaluates and redirects us to /login.
    router.refresh();
    router.replace("/login");
  }

  return { signOut, isSigningOut };
}

export function SignOutButton() {
  const { signOut, isSigningOut } = useSignOut();

  return (
    <Button type="button" variant="ghost" onClick={() => void signOut()} disabled={isSigningOut}>
      {isSigningOut ? "Signing out…" : "Sign out"}
    </Button>
  );
}

/**
 * Fixture-mode provenance (/demo, /demo/shell): there is no session to sign
 * out of, so the session edge carries this pill instead — an anonymous visitor
 * is never handed a control that can only bounce them to /login. It points at
 * the landing, which is where the demo's provenance is actually explained —
 * it used to point at /demo, back when /demo was a separate overview page
 * rather than the shell this pill renders inside, and a pill that links to
 * the page it is on answers nothing.
 */
export function DemoFixturePill() {
  return (
    <Link
      href="/"
      aria-label="Demo on fixture data — what Applied is, on the landing page"
      className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted transition-colors hover:text-strong focus-accent"
    >
      demo · fixture data
    </Link>
  );
}

/**
 * The anonymous visitor's session edge, stated as an invitation. The signed-in
 * shell spends this chrome on identity and sign-out; the demo's honest
 * equivalents are "nobody owns this board" and "make it yours", so the rail
 * footer (desktop) and the mobile menu (below `md`) both mount THIS — one
 * copy, one place, so the demo's single conversion line cannot fork between
 * the two chromes the way the twins this route family exists to prevent did.
 *
 * The line is the product's own claim in the product's own vocabulary: the
 * landing opens on "Your inbox already holds the verdict", the board counts
 * rows "filed", and what a new account does is read mail that already exists.
 * The beta line keeps the promise honest — Gmail connect is seat-gated
 * (Google's OAuth test-user cap, disclosed on the landing) — and doubles as
 * the sign-in path for anyone who already holds a seat.
 *
 * `compact` is a HEIGHT budget, not a style preference, and the budget is
 * measured (see `RailFooter`): on short windows the rail cannot afford the
 * full sentence without pushing the stage lens's last row below the fold —
 * the #122 failure mode. The compact sentence drops the Sam framing because
 * its antecedent (the identity row) is exactly what the short tier cannot
 * show; what survives is the owner's own line. The button and the beta line
 * are identical in both tiers, so the action never changes name.
 */
export function DemoSignupCta({
  compact = false,
  onNavigate,
}: {
  compact?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <div className="space-y-2">
      {compact ? (
        <p className="text-xs leading-relaxed text-muted">
          Your applications are waiting in your inbox.
        </p>
      ) : (
        <p className="text-xs leading-relaxed text-muted">
          <span className="text-strong">Sam isn&apos;t real. Your applications are</span> — already
          written down in your inbox, waiting to be filed.
        </p>
      )}
      <Link
        href="/signup"
        onClick={onNavigate}
        className={cn(buttonVariants({ size: "sm" }), "w-full")}
      >
        Create your account
      </Link>
      <p className="text-[11px] leading-relaxed text-dim">
        Beta — Gmail connect is invite-only. Have a seat?{" "}
        <Link
          href="/login"
          onClick={onNavigate}
          className="text-muted underline-offset-4 transition-colors hover:text-strong hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
