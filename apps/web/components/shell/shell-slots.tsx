"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * The shell's slot wiring — how PAGE-owned interface reaches SHELL-owned
 * geometry without a second instance of anything.
 *
 * Two facts travel down from `AppShellFrame`:
 *
 *   - `inShell` — a render-time constant (true inside the app shell, false on
 *     the shell-less /demo page and in tests that mount components bare). It
 *     is safe to branch MARKUP on: it is identical on the server pass and
 *     every client render, so hydration can never disagree with the HTML.
 *
 *   - `rail` — the DOM element of the sidebar's middle run, `null` until the
 *     sidebar mounts. `PipelineBoard` portals its stage lens (and search)
 *     into it, which is what lets the FILTERS live in the navigation column
 *     while their state stays in the one component that owns the list they
 *     filter. Portal content appears only after hydration; that is fine BY
 *     CONSTRUCTION here, because the rail is a fixed-width column whose
 *     middle is empty — content arriving in it cannot move anything else on
 *     the page (the CLS discipline the change ledger's reserve line exists
 *     for, satisfied by geometry instead of a placeholder). Everything the
 *     portal carries is interactive-only (filters, search), so the no-JS
 *     page loses nothing it could have used.
 *
 * The provider mounts once per shell; consumers outside any provider get the
 * `inShell: false` default and render their self-contained fallback.
 */

type ShellSlots = {
  inShell: boolean;
  rail: HTMLElement | null;
  setRail: (el: HTMLElement | null) => void;
};

const noop = () => undefined;

const ShellSlotsContext = createContext<ShellSlots>({
  inShell: false,
  rail: null,
  setRail: noop,
});

export function ShellSlotProvider({ children }: { children: ReactNode }) {
  const [rail, setRail] = useState<HTMLElement | null>(null);
  const value = useMemo(() => ({ inShell: true, rail, setRail }), [rail]);
  return <ShellSlotsContext.Provider value={value}>{children}</ShellSlotsContext.Provider>;
}

export function useShellSlots(): ShellSlots {
  return useContext(ShellSlotsContext);
}
