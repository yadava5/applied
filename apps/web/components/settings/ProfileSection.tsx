"use client";

import { useState } from "react";

import { ReadonlyField, SaveStatus, SettingsSection } from "./SettingsSection";
import { inputClass, primaryBtnClass, fieldLabelClass } from "@/components/ui/formStyles";
import { createClient } from "@/lib/supabase/client";

type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * Profile: an editable, persisted display name plus honest read-only account
 * facts. The name is written to the Supabase user's `user_metadata` via
 * `auth.updateUser`, so it survives reloads and is available anywhere the
 * session is read. Email, sign-in method, and member-since are real values
 * passed from the server — never editable stand-ins.
 */
export function ProfileSection({
  initialName,
  email,
  memberSince,
}: {
  initialName: string;
  email: string;
  memberSince: string | null;
}) {
  const [name, setName] = useState(initialName);
  const [state, setState] = useState<SaveState>("idle");
  const dirty = name.trim() !== initialName.trim();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setState("saving");
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ data: { display_name: name.trim() } });
    setState(error ? "error" : "saved");
  }

  return (
    <SettingsSection title="Profile" description="How you show up in Applied.">
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
          <ReadonlyField label="sign-in method" value="Email & password" />
          {memberSince ? <ReadonlyField label="member since" value={memberSince} /> : null}
        </div>

        <div className="flex items-center gap-3">
          <button type="submit" disabled={!dirty || state === "saving"} className={primaryBtnClass}>
            Save profile
          </button>
          <SaveStatus state={state} />
        </div>
      </form>
    </SettingsSection>
  );
}
