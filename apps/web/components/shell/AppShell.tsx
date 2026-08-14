import { Suspense, type ReactNode } from "react";

import type { RailData } from "@/lib/shell/rail";
import { AppShellFrame } from "./AppShellFrame";
import { ConnectionLine, ConnectionReserve } from "./RailFooter";

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
 * NOTHING HERE AWAITS. That is the point, and it is the second half of the fix
 * begun in `app/(app)/layout.tsx`.
 *
 * The layout stopped queueing the rail's backend probe behind its Supabase Auth
 * round-trip, so the two now overlap. But this component still `await`ed the
 * rail before returning the tree `children` render inside — and React cannot
 * begin rendering `children` until this function resolves. So the page's own
 * data (the dashboard's four-call fan-out, the inbox's list) still started only
 * after the Gmail probe answered: a backend round-trip in front of every
 * navigation, spent on one line of chrome in the rail's footer.
 *
 * Now the promise is handed to a `<Suspense>` boundary instead. This function
 * returns synchronously, `children` are rendered immediately, and the
 * connection line streams into its reserved space when the probe lands. The
 * identity row above it never waited in the first place — the layout already
 * holds the user — so only the one line that genuinely needs a backend answer
 * is behind the boundary.
 *
 * The boundary has to live HERE rather than inside `Sidebar` because `Sidebar`
 * is a Client Component: the line is resolved on the server and passed down as
 * an already-rendered slot. `ConnectionReserve` holds exactly one line box of
 * the line's own type, so the anchored footer does not move when the answer
 * arrives (see its note). `TopBar` is a Client Component because sign-out calls
 * into supabase-js in the browser.
 */
export function AppShell({ children, rail, userEmail, userName = null }: AppShellProps) {
  return (
    <AppShellFrame
      connection={
        <Suspense fallback={<ConnectionReserve />}>
          <StreamedConnection rail={rail} userEmail={userEmail} />
        </Suspense>
      }
      userEmail={userEmail}
      userName={userName}
    >
      {children}
    </AppShellFrame>
  );
}

/**
 * The only thing in the shell that waits for the backend. Split out purely so
 * the `await` sits INSIDE the Suspense boundary rather than above it — an
 * `await` in `AppShell` itself would block `children` again, which is the whole
 * defect this file's note describes.
 */
async function StreamedConnection({
  rail,
  userEmail,
}: {
  rail: Promise<RailData>;
  userEmail: string | null;
}) {
  const { gmail } = await rail;
  return <ConnectionLine gmail={gmail} userEmail={userEmail} />;
}
