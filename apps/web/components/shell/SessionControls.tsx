"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

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
 * Fixture-mode provenance (/demo/shell): there is no session to sign out of,
 * so the session edge carries this pill instead — an anonymous visitor is
 * never handed a control that can only bounce them to /login.
 */
export function DemoFixturePill() {
  return (
    <Link
      href="/demo"
      aria-label="Demo shell on fixture data — back to the demo overview"
      className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-line px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-muted transition-colors hover:text-strong focus-accent"
    >
      demo · fixture data
    </Link>
  );
}
