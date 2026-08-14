"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

import { SettingsSection } from "./SettingsSection";
import type { SettingsMode } from "@/lib/settings/transport";
import { THEME_CHANGE_EVENT, applyTheme, readAppliedTheme, type Theme } from "@/lib/theme";

const OPTIONS: { value: Theme; label: string; icon: typeof Moon }[] = [
  { value: "dark", label: "Dark", icon: Moon },
  { value: "light", label: "Light", icon: Sun },
];

function subscribe(onChange: () => void) {
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * Appearance: a real, immediately-applied theme switch. The active theme is
 * read from the DOM via `useSyncExternalStore` (so SSR and hydration agree on
 * the dark default, then the client syncs to the saved choice); selecting an
 * option flips `data-theme` on <html> and persists it, re-theming the whole app
 * with no reload and no flash on the next visit.
 *
 * `mode="demo"` changes nothing about the mechanism — the switch writes and
 * persists the real theme there too — but the demo family pins its own dark
 * ground (see app/demo/page.tsx), so the change is invisible ON that page. The
 * control says so rather than looking broken: a switch you flip and nothing
 * moves reads as a bug, whatever it did underneath.
 */
export function AppearanceSection({ mode = "live" }: { mode?: SettingsMode }) {
  const theme = useSyncExternalStore(subscribe, readAppliedTheme, () => "dark" as Theme);

  return (
    <SettingsSection id="appearance" title="Appearance" description="Choose how Applied looks on this device.">
      <div
        role="radiogroup"
        aria-label="Theme"
        className="inline-flex rounded-lg border border-line bg-surface-2 p-1"
      >
        {OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = theme === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => applyTheme(opt.value)}
              className={`inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                active ? "bg-strong text-background" : "text-muted hover:text-strong"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {opt.label}
            </button>
          );
        })}
      </div>
      {/* Demo-only: a switch you flip and nothing moves reads as broken, so
          the pinned-dark page says why. Live gets no caption — the theme
          changing under your cursor is its own explanation (#200). */}
      {mode === "demo" ? (
        <p className="mt-3 text-[12px] leading-relaxed text-dim">
          The demo is pinned to the product&apos;s dark theme, so this page won&apos;t change
          colour — sign in to see your choice applied.
        </p>
      ) : null}
    </SettingsSection>
  );
}
