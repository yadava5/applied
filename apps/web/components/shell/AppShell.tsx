import type { ReactNode } from "react";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

type AppShellProps = {
  children: ReactNode;
  userEmail: string | null;
};

/**
 * Protected shell layout used under `app/(app)/`. Renders a persistent
 * sidebar (primary nav) and a top bar (user info + sign-out) around the
 * page content. The `TopBar` is a Client Component because sign-out calls
 * into supabase-js in the browser; the rest of the shell renders on the
 * server.
 */
export function AppShell({ children, userEmail }: AppShellProps) {
  return (
    <div className="flex min-h-screen w-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar userEmail={userEmail} />
        <main className="flex-1 overflow-y-auto px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
