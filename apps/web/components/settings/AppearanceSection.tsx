"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

import { SettingsSection } from "./SettingsSection";
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
 */
export function AppearanceSection() {
  const theme = useSyncExternalStore(subscribe, readAppliedTheme, () => "dark" as Theme);

  return (
    <SettingsSection title="Appearance" description="Choose how JobTracker looks on this device.">
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
      <p className="mt-3 text-[12px] leading-relaxed text-dim">Saved on this device. Dark is the default.</p>
    </SettingsSection>
  );
}
