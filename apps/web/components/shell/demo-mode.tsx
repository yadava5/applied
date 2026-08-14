"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * Fixture-mode flag for the app shell, as CONTEXT rather than a prop.
 *
 * The shell's chrome is one tree with many leaves — `Sidebar`, `TopBar`,
 * `NavLink`, `RailFooter` — and several of them need to know whether the frame
 * is mounted over fixtures (/demo, /demo/shell): the nav's destinations sit
 * behind the auth proxy, the rail footer's links do too, and the anonymous
 * visitor's session edge is an invitation rather than a sign-out. Threading a
 * `demo` prop through every one of those components would put the same boolean
 * on four signatures and make each of them a merge surface; the provider puts
 * it on one (`AppShellFrame`, which already owns the flag) and lets each leaf
 * ask for itself.
 *
 * The default is `false` and there is no provider on the signed-in tree's
 * error paths that could flip it: a component that renders outside
 * `AppShellFrame` simply reads "not a demo", which is the safe answer — the
 * worst a false negative can do is render a real destination.
 */
const DemoModeContext = createContext(false);

/** Whether the surrounding shell is the fixture-mode demo. */
export function useDemoMode(): boolean {
  return useContext(DemoModeContext);
}

export function DemoModeProvider({ demo, children }: { demo: boolean; children: ReactNode }) {
  return <DemoModeContext.Provider value={demo}>{children}</DemoModeContext.Provider>;
}
