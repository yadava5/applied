"use client";

import { useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { dangerBtnClass, secondaryBtnClass } from "@/components/ui/formStyles";

const DEMO_REASON = "Simulated account — there is no real connection to revoke.";

/**
 * The Disconnect control on the Gmail card, confirmed in the same centred
 * Dialog as the other sensitive Settings actions (#213). Revocation used to be
 * one bare click; now the destructive step lives behind a dialog that says
 * what it does (revoke at Google, delete the stored token, filed mail stays —
 * the privacy policy §8 sentence, at the moment it matters).
 *
 * The confirm stays a native form POST to `/api/gmail/disconnect` — no token
 * or fetch in the browser, exactly as before; the dialog only adds the
 * deliberate second step. On the `/demo/settings` twin that POST would 401
 * without a session, so the confirm — not the whole flow — is disabled with
 * the reason as visible text: the dialog family stays reviewable and
 * e2e-drivable, and a dead button still says why it is dead.
 */
export function DisconnectGmailButton({
  email,
  demo = false,
}: {
  email: string | null;
  demo?: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-lg border border-line px-4 py-2 text-sm text-foreground transition-colors hover:border-reject/60 hover:text-strong"
      >
        Disconnect
      </button>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Disconnect Gmail?"
        description={
          <>
            This revokes Applied’s access at Google and deletes the stored token
            {email ? (
              <>
                {" "}
                for <span className="text-strong">{email}</span>
              </>
            ) : null}
            . Mail it has already classified stays on your board.
          </>
        }
      >
        <div className="space-y-4">
          {demo ? (
            <p role="status" className="text-xs text-dim">
              {DEMO_REASON}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setOpen(false)} className={secondaryBtnClass}>
              Cancel
            </button>
            {demo ? (
              <button type="button" disabled title={DEMO_REASON} className={dangerBtnClass}>
                Disconnect and revoke
              </button>
            ) : (
              <form action="/api/gmail/disconnect" method="post">
                <button type="submit" className={dangerBtnClass}>
                  Disconnect and revoke
                </button>
              </form>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}
