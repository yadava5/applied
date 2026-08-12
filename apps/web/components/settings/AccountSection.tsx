"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut } from "lucide-react";

import { SettingsSection } from "./SettingsSection";
import { Dialog } from "@/components/ui/Dialog";
import { dangerBtnClass, inputClass, secondaryBtnClass } from "@/components/ui/formStyles";
import { createClient } from "@/lib/supabase/client";

const CONFIRM_WORD = "DELETE";

/**
 * Account: sign out, and a gated "danger zone" delete. Deletion requires typing
 * DELETE to arm, then calls the server route that removes the account. If the
 * deployment hasn't enabled deletion (no service-role key), the route says so
 * honestly rather than silently doing nothing — the button is never a no-op.
 */
export function AccountSection({ email }: { email: string }) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signOut() {
    setSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    router.refresh();
    router.replace("/login");
  }

  async function deleteAccount() {
    setDeleting(true);
    setError(null);
    try {
      const res = await fetch("/api/account/delete", { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        setError(
          typeof body.detail === "string"
            ? body.detail
            : "Account deletion isn’t available on this deployment yet.",
        );
        setDeleting(false);
        return;
      }
      const supabase = createClient();
      await supabase.auth.signOut();
      router.replace("/");
    } catch {
      setError("Couldn’t reach the server. Try again shortly.");
      setDeleting(false);
    }
  }

  return (
    <SettingsSection title="Account" description="Sign out, or remove your account entirely." tone="danger">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={signOut} disabled={signingOut} className={secondaryBtnClass}>
          <LogOut className="h-4 w-4" aria-hidden="true" />
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
        <button type="button" onClick={() => setOpen(true)} className={dangerBtnClass}>
          Delete account
        </button>
      </div>

      <p className="mt-3 text-[12px] leading-relaxed text-dim">
        Deleting removes your applications and revokes any connected Gmail. This can’t be undone.
      </p>

      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setConfirm("");
          setError(null);
        }}
        title="Delete your account?"
        description={
          <>
            This permanently deletes <span className="text-strong">{email}</span> and everything
            filed under it. This action cannot be undone.
          </>
        }
      >
        <div className="space-y-4">
          <label className="grid gap-1">
            <span className="label-caps">
              type <span className="font-mono text-reject-ink">{CONFIRM_WORD}</span> to confirm
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="off"
              className={inputClass}
              aria-label={`Type ${CONFIRM_WORD} to confirm account deletion`}
            />
          </label>

          {error ? (
            <p role="alert" className="text-xs text-reject-ink">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setConfirm("");
                setError(null);
              }}
              className={secondaryBtnClass}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={deleteAccount}
              disabled={confirm !== CONFIRM_WORD || deleting}
              className={dangerBtnClass}
            >
              {deleting ? "Deleting…" : "Permanently delete"}
            </button>
          </div>
        </div>
      </Dialog>
    </SettingsSection>
  );
}
