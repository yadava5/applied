"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

/**
 * The session-edge controls, extracted so they can render in either piece of
 * top chrome: the shell `TopBar` below `lg`, and the board's own header row
 * at `lg`+ (which replaces the bar on the board route — see TopBar). One
 * implementation, two mount points, exactly one visible at a time.
 */

export function SignOutButton() {
  const router = useRouter();
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function handleSignOut() {
    setIsSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    // Refresh so the proxy re-evaluates and redirects us to /login.
    router.refresh();
    router.replace("/login");
  }

  return (
    <Button type="button" variant="ghost" onClick={handleSignOut} disabled={isSigningOut}>
      {isSigningOut ? "Signing out…" : "Sign out"}
    </Button>
  );
}

/**
 * Fixture-mode provenance (/demo/shell): there is no session to sign out of,
 * so the sign-out slot carries this pill instead — an anonymous visitor is
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
