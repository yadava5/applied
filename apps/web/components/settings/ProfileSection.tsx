"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { type SignInSummary } from "./accountSecurity";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { ProfilePhotoField } from "./ProfilePhotoField";
import { ReadonlyField, SaveStatus, SettingsSection } from "./SettingsSection";
import { inputClass, primaryBtnClass, fieldLabelClass } from "@/components/ui/formStyles";
import type { AvatarSource } from "@/lib/profile/avatar";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * Profile: the account's picture and display name, plus honest read-only
 * account facts. The name is written through the settings transport (live: the
 * Supabase user's `user_metadata`, so it survives reloads and is available
 * anywhere the session is read; demo: simulated). Email, member-since, and
 * the sign-in summary are real values derived server-side — never editable
 * stand-ins, and never assumed: `signIn` comes from the account's actual
 * identity list (#199), and it also decides whether a change-password
 * control exists at all (#202) — no `email` identity, no password to change.
 *
 * The photo leads the card because it is the one thing on this page a reader
 * recognises before reading anything, and its own states are `ProfilePhotoField`
 * — including which source is in play, which is a fact and not a preference.
 * The monogram under it follows the name field AS IT IS TYPED rather than as it
 * was last saved: the tile is a preview of the sidebar, and a preview that
 * lagged the field it sits under would just look stale.
 */
export function ProfileSection({
  initialName,
  email,
  memberSince,
  signIn,
  avatarSource = "none",
  avatarSrc = null,
  googleAvatarSrc = null,
  mode = "live",
}: {
  initialName: string;
  email: string;
  memberSince: string | null;
  signIn: SignInSummary;
  /** Resolved server-side by `lib/profile/avatar`'s `resolveAvatar` — the same
   *  precedence the rail renders, so the two surfaces cannot disagree. */
  avatarSource?: AvatarSource;
  avatarSrc?: string | null;
  googleAvatarSrc?: string | null;
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
    // #216, same reason as `NotificationsSection.persist` — see the note
    // there. This name is server-rendered into the shell (the rail's account
    // block, the TopBar), and every one of those routes can be sitting in the
    // 30 s router cache when the save lands.
    if (ok) router.refresh();
  }

  // Same derivation as the rail's (`components/shell/RailFooter`): whatever the
  // row will print is what the tile letters, and "·" when there is nothing to
  // print at all.
  const initial = (name.trim() || email).charAt(0).toUpperCase() || "·";

  return (
    <SettingsSection id="profile" title="Profile">
      <div className="mb-6">
        <ProfilePhotoField
          source={avatarSource}
          src={avatarSrc}
          googleSrc={googleAvatarSrc}
          initial={initial}
          mode={mode}
        />
      </div>

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
          {memberSince ? <ReadonlyField label="member since" value={memberSince} /> : null}
        </div>

        <div className="flex items-center gap-3">
          <button type="submit" disabled={!dirty || state === "saving"} className={primaryBtnClass}>
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
