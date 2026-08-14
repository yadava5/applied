"use client";

import { useRef, useState } from "react";

import { newPasswordProblem, type NewPasswordField } from "./accountSecurity";
import { STATUS_LINGER_MS, TransientStatus, useLinger } from "./SettingsSection";
import { Dialog } from "@/components/ui/Dialog";
import { inputClass, primaryBtnClass, secondaryBtnClass, fieldLabelClass } from "@/components/ui/formStyles";
import { SIGNUP_MIN_PASSWORD } from "@/lib/auth/credentials";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

/**
 * Change the account password, from inside the Profile card (#202 — the
 * Settings half; the reset-at-sign-in flow is a separate surface and lives
 * with the auth pages).
 *
 * Only mounted when the account holds an `email` identity — ProfileSection
 * gates on the derived summary, so a Google-only account is never shown a
 * control that cannot work.
 *
 * The page holds ONE button; the form itself lives in the centred Dialog
 * (#213). The old inline form grew two fields under the card and re-flowed
 * everything beneath it, and its "Password updated" line persisted for the
 * life of the mount. Now a sensitive action is separated from the settings it
 * sits among the same way deletion always was, the card never changes shape,
 * and success is reported by a status that clears itself after
 * `STATUS_LINGER_MS`.
 *
 * Validation is the signup form's own standard (`SIGNUP_MIN_PASSWORD`,
 * imported and passed to the shared predicate — not a second floor), checked
 * before the network like both auth forms. The write goes through the
 * settings transport: live is `supabase.auth.updateUser({ password })`, the
 * demo twin simulates success, and Supabase's refusal sentence (same-password,
 * reauthentication) is surfaced verbatim because it is the actionable part.
 */
export function ChangePasswordForm({ mode = "live" }: { mode?: SettingsMode }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState(false);
  const showUpdated = useLinger(updated, STATUS_LINGER_MS);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const transport = settingsTransport(mode);

  function focusField(field: NewPasswordField) {
    (field === "password" ? passwordRef : confirmRef).current?.focus();
  }

  function close() {
    setOpen(false);
    setPassword("");
    setConfirm("");
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const problem = newPasswordProblem(password, confirm, SIGNUP_MIN_PASSWORD);
    if (problem) {
      setError(problem.message);
      focusField(problem.field);
      return;
    }
    setSaving(true);
    setError(null);
    const result = await transport.updatePassword(password);
    setSaving(false);
    if (!result.ok) {
      setError(result.message ?? "Couldn’t change the password — try again.");
      return;
    }
    setUpdated(true);
    close();
  }

  return (
    <div className="flex items-center gap-3 border-t border-line-soft pt-4">
      <button
        type="button"
        onClick={() => {
          setUpdated(false);
          setOpen(true);
        }}
        className={secondaryBtnClass}
      >
        Change password
      </button>
      <TransientStatus show={showUpdated} className="text-live">
        Password updated
      </TransientStatus>

      <Dialog
        open={open}
        onClose={close}
        title="Change password"
        description={`At least ${SIGNUP_MIN_PASSWORD} characters — you’ll use it the next time you sign in.`}
      >
        {/* `noValidate` + hand checks, the same trade both auth forms make:
            the app's own error copy and focus handling instead of browser
            bubbles. Fields stack — a dialog reads top to bottom. */}
        <form onSubmit={submit} noValidate className="space-y-4">
          <label className="grid gap-1">
            <span className={fieldLabelClass}>new password</span>
            <input
              ref={passwordRef}
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              className={inputClass}
            />
          </label>
          <label className="grid gap-1">
            <span className={fieldLabelClass}>confirm new password</span>
            <input
              ref={confirmRef}
              type="password"
              value={confirm}
              onChange={(e) => {
                setConfirm(e.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              className={inputClass}
            />
          </label>

          {error ? (
            <p role="alert" className="text-xs text-reject-ink">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={close} className={secondaryBtnClass}>
              Cancel
            </button>
            <button type="submit" disabled={saving} className={primaryBtnClass}>
              {saving ? "Updating…" : "Update password"}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
