"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { notifyError } from "@/components/feedback/notify";

import { type SignInSummary } from "./accountSecurity";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { ReadonlyField, SaveStatus, SettingsSection } from "./SettingsSection";
import {
  inputClass,
  primaryBtnClass,
  fieldLabelClass,
} from "@/components/ui/formStyles";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * Profile: an editable, persisted display name plus honest read-only account
 * facts. The name is written through the settings transport (live: the
 * Supabase user's `user_metadata`, so it survives reloads and is available
 * anywhere the session is read; demo: simulated). Email, member-since, and
 * the sign-in summary are real values derived server-side — never editable
 * stand-ins, and never assumed: `signIn` comes from the account's actual
 * identity list (#199), and it also decides whether a change-password
 * control exists at all (#202) — no `email` identity, no password to change.
 */
export function ProfileSection({
  initialName,
  email,
  memberSince,
  signIn,
  mode = "live",
}: {
  initialName: string;
  email: string;
  memberSince: string | null;
  signIn: SignInSummary;
  mode?: SettingsMode;
}) {
  const [name, setName] = useState(initialName);
  const [state, setState] = useState<SaveState>("idle");
  const dirty = name.trim() !== initialName.trim();
  const transport = settingsTransport(mode);
  const router = useRouter();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setState("saving");
    const { ok } = await transport.saveMetadata({ display_name: name.trim() });
    setState(ok ? "saved" : "error");
    // A FAILED save is the one thing the inline chip cannot carry (#511).
    // Success stays inline, beside the control that caused it — a corner toast
    // for every toggle would be noise, and the chip is already where the eye
    // is. A failure is different: the control has visibly moved, nothing was
    // written, and the chip is a small word at the edge of a card the user has
    // usually already scrolled past. Error toasts never auto-dismiss.
    if (!ok)
      notifyError(
        "settings.profile",
        "Couldn't save your profile — your change wasn't kept",
      );
    // #216, same reason as `NotificationsSection.persist` — see the note
    // there. This name is server-rendered into the shell (the rail's account
    // block, the TopBar), and every one of those routes can be sitting in the
    // 30 s router cache when the save lands.
    if (ok) router.refresh();
  }

  return (
    <SettingsSection id="profile" title="Profile">
      <form onSubmit={save} className="space-y-4">
        <label className="grid gap-1">
          <span className={fieldLabelClass}>display name</span>
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setState("idle");
            }}
            placeholder="e.g. Ayush Yadav"
            className={inputClass}
            maxLength={80}
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField label="email" value={email} />
          <ReadonlyField label={signIn.label} value={signIn.value} />
          {memberSince ? (
            <ReadonlyField label="member since" value={memberSince} />
          ) : null}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!dirty || state === "saving"}
            className={primaryBtnClass}
          >
            Save profile
          </button>
          <SaveStatus state={state} />
        </div>
      </form>

      {signIn.hasEmailIdentity ? (
        <div className="mt-4">
          <ChangePasswordForm mode={mode} />
        </div>
      ) : null}
    </SettingsSection>
  );
}
