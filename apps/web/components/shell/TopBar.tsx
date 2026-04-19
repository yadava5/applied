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
    <header className="flex h-14 items-center justify-between border-b border-neutral-200 bg-white px-4 dark:border-neutral-800 dark:bg-neutral-950">
      <div className="text-sm text-neutral-500 dark:text-neutral-400">
        {userEmail ?? ""}
      </div>
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
