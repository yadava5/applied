import type { ReactNode } from "react";

import type { RailData } from "@/lib/shell/rail";
import { AppShellFrame } from "./AppShellFrame";
import { ReturnRefresh } from "./ReturnRefresh";

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
  /** The ambient-mail pref, read from user metadata by the layout. */
  ambient?: boolean;
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
 *
 * `ReturnRefresh` hangs off THIS component rather than the frame, and outside
 * the frame's tree rather than among the page's children: it is the signed-in
 * half of the router-cache trade (`staleTimes.dynamic: 300` in
 * `next.config.ts`), and mounting it here is what keeps it off `/demo/shell`,
 * which renders `AppShellFrame` directly over fixtures with no server to
 * refresh from. It renders `null`, so it touches neither the geometry contract
 * nor the shared column.
 */
export async function AppShell({
  children,
  rail,
  userEmail,
  userName = null,
  ambient = true,
}: AppShellProps) {
  return (
    <>
      <ReturnRefresh />
      <AppShellFrame rail={await rail} userEmail={userEmail} userName={userName} ambient={ambient}>
        {children}
      </AppShellFrame>
    </>
  );
}
