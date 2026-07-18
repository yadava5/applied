"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

type TopBarProps = {
  userEmail: string | null;
};

export function TopBar({ userEmail }: TopBarProps) {
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
    <header className="flex h-14 items-center justify-between border-b border-line-soft bg-surface px-4">
      <div className="font-mono text-sm text-muted">{userEmail ?? ""}</div>
      <Button
        type="button"
        variant="ghost"
        onClick={handleSignOut}
        disabled={isSigningOut}
      >
        {isSigningOut ? "Signing out…" : "Sign out"}
      </Button>
    </header>
  );
}
