import type { ReactNode } from "react";

import type { RailData } from "@/lib/shell/rail";
import { AppShellFrame } from "./AppShellFrame";

type AppShellProps = {
  children: ReactNode;
  /**
   * The rail's data, IN FLIGHT. The caller starts the fetch so it overlaps the
   * layout's own auth round-trip instead of queueing behind it — see the note
   * in `app/(app)/layout.tsx` for why the two are independent.
   */
  rail: Promise<RailData>;
  userEmail: string | null;
  /** Display name for the identity block; `null` falls back to the email. */
  userName?: string | null;
};

/**
 * Protected shell used under `app/(app)/` (and by the signed-in branch of
 * `/import`): live data around the shared frame. The geometry itself —
 * viewport lock, the one scroll pane, the flow/locked page contract — lives
 * in `AppShellFrame`, which `/demo/shell` also mounts over fixtures so the
 * lock stays testable without a session.
 *
 * This is an async Server Component: it awaits the rail's data (the Gmail
 * connection state the footer shows) — a never-throwing backend read that
 * degrades to an honest fallback — and hands the result to the client `Sidebar`
 * as serializable props. The FETCH is started by the layout rather than here,
 * so it runs alongside the layout's Supabase Auth round-trip instead of after
 * it; awaiting a promise the caller already put in flight is the whole
 * difference. The auth/session reads underneath are request-memoized, so the
 * shell shares them with the page it wraps. `TopBar` is a Client Component
 * because sign-out calls into supabase-js in the browser.
 */
export async function AppShell({ children, rail, userEmail, userName = null }: AppShellProps) {
  return (
    <AppShellFrame rail={await rail} userEmail={userEmail} userName={userName}>
      {children}
    </AppShellFrame>
  );
}
