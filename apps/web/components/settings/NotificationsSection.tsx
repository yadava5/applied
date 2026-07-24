"use client";

import { useState } from "react";

import { SaveStatus, SettingsSection } from "./SettingsSection";
import { createClient } from "@/lib/supabase/client";

export interface NotificationPrefs {
  weekly: boolean;
  reviewAlerts: boolean;
}

type SaveState = "idle" | "saving" | "saved" | "error";

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm text-strong">{label}</p>
        <p className="mt-0.5 text-[12px] leading-snug text-muted">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-line-strong ${
          checked ? "border-live/60 bg-live/25" : "border-line bg-surface-2"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all ${
            checked ? "left-[18px] bg-live" : "left-0.5 bg-dim"
          }`}
          aria-hidden="true"
        />
      </button>
    </div>
  );
}

/**
 * Notification preferences. The choices persist to the Supabase user's
 * metadata immediately, so they survive reloads and are readable by any future
 * sender. Email delivery isn't wired on this deployment yet — the caption says
 * so plainly rather than pretending a toggle sends mail it can't.
 */
export function NotificationsSection({ initial }: { initial: NotificationPrefs }) {
  const [prefs, setPrefs] = useState<NotificationPrefs>(initial);
  const [state, setState] = useState<SaveState>("idle");

  async function persist(next: NotificationPrefs) {
    setPrefs(next);
    setState("saving");
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ data: { notifications: next } });
    setState(error ? "error" : "saved");
  }

  return (
    <SettingsSection
      title="Notifications"
      description="What Applied should keep you posted about."
    >
      <div className="divide-y divide-line-soft">
        <Toggle
          checked={prefs.weekly}
          onChange={(v) => persist({ ...prefs, weekly: v })}
          label="Weekly pipeline summary"
          description="A once-a-week digest of what moved — applied, interviews, offers, rejections."
        />
        <Toggle
          checked={prefs.reviewAlerts}
          onChange={(v) => persist({ ...prefs, reviewAlerts: v })}
          label="Needs-review alerts"
          description="Ping me when the classifier isn’t confident and an email is held for my review."
        />
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-line-soft pt-4">
        <p className="text-[12px] leading-relaxed text-dim">
          Preferences are saved to your account now. Email delivery is rolling out — until it lands,
          these govern in-app cues only.
        </p>
        <SaveStatus state={state} />
      </div>
    </SettingsSection>
  );
}
