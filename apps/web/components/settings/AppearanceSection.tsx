"use client";

import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

import { SaveStatus, SettingsSection } from "./SettingsSection";
import { Toggle } from "./Toggle";
import { setAmbientOverride } from "@/lib/shell/ambient-bus";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";
import { THEME_CHANGE_EVENT, applyTheme, readAppliedTheme, type Theme } from "@/lib/theme";

const OPTIONS: { value: Theme; label: string; icon: typeof Moon }[] = [
  { value: "dark", label: "Dark", icon: Moon },
  { value: "light", label: "Light", icon: Sun },
];

type SaveState = "idle" | "saving" | "saved" | "error";

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
 * Beneath it, the ambient-mail switch: whether the sidebar's middle run runs
 * the drifting-envelope field (`components/shell/AmbientRail`). Unlike the
 * theme this one persists to the user's metadata — the rail is rendered
 * server-side from it, so the choice must live where the server reads
 * (`lib/settings/ambient.ts`), not in this device's storage. The save
 * publishes twice: `setAmbientOverride` stops or starts the field in the rail
 * beside this very card the moment the write lands, and `router.refresh()`
 * makes the server agree — the publish contract every metadata writer here
 * carries (`tests/unit/settings-publish-contract.test.mjs`; see
 * NotificationsSection for the #216 story it encodes).
 *
 * `mode="demo"` changes nothing about either mechanism — the theme switch
 * writes the real `data-theme`, the ambient switch writes the demo's own
 * cookie (`lib/demo/ambientPref.ts`) — but the demo family pins its own dark
 * ground (see app/demo/settings/page.tsx) and has no sidebar on this page, so
 * both controls say where their change is visible rather than looking broken:
 * a switch you flip and nothing moves reads as a bug, whatever it did
 * underneath.
 */
export function AppearanceSection({
  mode = "live",
  initialAmbient = true,
}: {
  mode?: SettingsMode;
  /** The saved ambient-mail pref (server-read; metadata live, cookie demo). */
  initialAmbient?: boolean;
}) {
  const theme = useSyncExternalStore(subscribe, readAppliedTheme, () => "dark" as Theme);
  const [ambient, setAmbient] = useState(initialAmbient);
  const [state, setState] = useState<SaveState>("idle");
  const transport = settingsTransport(mode);
  const router = useRouter();

  async function persistAmbient(next: boolean) {
    setAmbient(next);
    setState("saving");
    const { ok } = await transport.saveMetadata({ ambient: next });
    setState(ok ? "saved" : "error");
    if (ok) {
      // The rail is on this very screen: the override stops (or restarts) the
      // field under the user's eyes now; the refresh below re-renders the
      // layout from the metadata so the server-side truth agrees. Only on
      // `ok` — a failed save has nothing to publish.
      setAmbientOverride(next);
      router.refresh();
    }
  }

  return (
    <SettingsSection id="appearance" title="Appearance" description="Choose how Applied looks.">
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
      <div className="mt-4 border-t border-line-soft">
        <Toggle
          checked={ambient}
          onChange={(v) => void persistAmbient(v)}
          label="Ambient mail"
          description="Faint mail drifts behind the sidebar and stirs when a sync files something or a stage moves."
        />
        {/* Same honesty as the theme caption above: this page of the demo has
            no sidebar, so the switch names the page that shows its work. */}
        {mode === "demo" ? (
          <p className="text-[12px] leading-relaxed text-dim">
            The demo settings page has no sidebar of its own — open the shell demo to see this
            applied.
          </p>
        ) : null}
        {/* `min-h-4` reserves the status line's height so "Saved" arriving —
            and clearing — never re-flows the card (the #213 discipline). */}
        <div className="mt-1 flex min-h-4 justify-end">
          <SaveStatus state={state} />
        </div>
      </div>
    </SettingsSection>
  );
}
