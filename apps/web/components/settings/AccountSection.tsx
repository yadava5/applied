"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LogOut } from "lucide-react";

import { SettingsSection, TransientStatus, useLinger } from "./SettingsSection";
import { Dialog } from "@/components/ui/Dialog";
import { dangerBtnClass, inputClass, secondaryBtnClass } from "@/components/ui/formStyles";
import { settingsTransport, type SettingsMode } from "@/lib/settings/transport";

const CONFIRM_WORD = "DELETE";

/**
 * Shown wherever the deployment cannot delete — the standing caption, the
 * dialog, and the disabled confirm's tooltip all say the same sentence, so the
 * user meets the limitation once and recognises it.
 */
const UNAVAILABLE_REASON =
  "Account deletion isn’t enabled on this deployment yet. Email the admin to have your data removed.";

/**
 * Account: sign out, and a gated "danger zone" delete. Deletion requires typing
 * DELETE to arm, then calls the server route that removes the account.
 *
 * `deletionEnabled` is the deployment's own answer to "can this work at all",
 * read server-side from the same predicate the route depends on
 * (`lib/supabase/admin.ts`). Before #218 it was not surfaced anywhere: the
 * route's honest 501 was correct but arrived *after* the user had read "this
 * cannot be undone", typed DELETE and pressed a destructive button. Now the
 * reason is visible standing text and the destructive confirm is the dead
 * control — the same resolution as the Gmail disconnect dialog, and for the
 * same reason: a dead button that says why beats a live one that lies. The
 * typed-DELETE gate is untouched, so the flow stays reviewable end to end.
 *
 * On the `/demo/settings` twin the same gate runs end to end; the transport's
 * answer is the one honest difference ("simulated account — nothing exists to
 * delete").
 */
export function AccountSection({
  email,
  mode = "live",
  deletionEnabled = true,
}: {
  email: string;
  mode?: SettingsMode;
  /** Defaults to `true` so the demo twin keeps exercising the whole machine. */
  deletionEnabled?: boolean;
}) {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [signOutNote, setSignOutNote] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transport = settingsTransport(mode);

  // The note is an answer to a click, not a standing fact — it rides the same
  // self-clearing status the rest of the page uses (#213).
  const showSignOutNote = useLinger(signOutNote !== null);

  async function signOut() {
    setSigningOut(true);
    setSignOutNote(null);
    await transport.signOut();
    if (transport.mode === "demo") {
      // No session exists here to end — the twin says so instead of bouncing
      // an anonymous visitor to the login wall.
      setSignOutNote("Simulated account — there is no session to sign out of.");
      setSigningOut(false);
      return;
    }
    router.refresh();
    router.replace("/login");
  }

  async function deleteAccount() {
    setDeleting(true);
    setError(null);
    const result = await transport.deleteAccount();
    if (!result.ok) {
      setError(result.detail ?? "Account deletion isn’t available on this deployment yet.");
      setDeleting(false);
      return;
    }
    await transport.signOut();
    router.replace("/");
  }

  return (
    <SettingsSection id="account" title="Account" tone="danger">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={signOut} disabled={signingOut} className={secondaryBtnClass}>
          <LogOut className="h-4 w-4" aria-hidden="true" />
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
        <button type="button" onClick={() => setOpen(true)} className={dangerBtnClass}>
          Delete account
        </button>
        {/* Inline in the button row: the row's height is set by the buttons,
            so the note appearing and clearing never re-flows the card. */}
        <TransientStatus show={showSignOutNote} className="text-dim">
          {signOutNote}
        </TransientStatus>
      </div>

      <p className="mt-3 text-[12px] leading-relaxed text-dim">
        Deleting removes your applications and revokes Applied’s access to any connected Gmail at
        Google. This can’t be undone.
      </p>

      {!deletionEnabled ? (
        <p role="status" className="mt-2 text-[12px] leading-relaxed text-reject-ink">
          {UNAVAILABLE_REASON}
        </p>
      ) : null}

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
          {!deletionEnabled ? (
            <p role="status" className="text-xs text-dim">
              {UNAVAILABLE_REASON}
            </p>
          ) : null}

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
              disabled={!deletionEnabled || confirm !== CONFIRM_WORD || deleting}
              title={deletionEnabled ? undefined : UNAVAILABLE_REASON}
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
