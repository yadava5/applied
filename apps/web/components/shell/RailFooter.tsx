import Link from "next/link";

import { LastSynced } from "@/components/gmail/LastSynced";
import type { RailGmailData } from "@/lib/shell/rail";

/**
 * The sidebar's anchored footer: ONE identity block — who is signed in, and,
 * hanging off it, whether Gmail is connected and when it last built the board.
 *
 * Why one block
 * -------------
 * This was two stacked chips, and for very nearly every user they printed the
 * SAME address twice, eight pixels apart: you sign in to Applied with the
 * Google account you then connect. "Gmail · connected / aesh…@gmail.com" over
 * "aesh…@gmail.com / SIGNED IN" does not read as two facts, it reads as a bug.
 *
 * So the address is printed ONCE, in the identity row, and the connection is a
 * subordinate line beneath it. The order flipped with it — identity used to sit
 * under the chip; it is now the anchor, because the account is the thing and
 * the connection is something the account *has*. Identity still lives
 * bottom-left (the Linear/Notion convention) and sign-out still lives in the
 * top bar.
 *
 * When the two accounts genuinely DIFFER — signed in as one, Gmail connected as
 * another — the connection line names its own address ("connected as
 * billing@corp.com") and both are on screen. Which means the *absence* of a
 * second address is what asserts the two are the same mailbox. That is a quiet
 * read, and it is the deliberate trade: the alternative is printing the
 * identical string twice, which is the defect this collapse exists to remove.
 *
 * Connection line — the same three honest states as before:
 *   - connected     → live emerald dot (`.beta-dot` ping), the state, and when
 *                     the board was last built. Links to the dashboard, where
 *                     sync now lives.
 *   - not connected → a quiet line that links to Settings, where connecting
 *                     actually lives.
 *   - unknown       → line omitted entirely (a failed status probe is not a
 *                     disconnection; never show a guessed state).
 *
 * The re-sync icon button is still GONE — it was the fourth sync trigger, an
 * unlabelled icon that did something different from the identically-iconed
 * header button. The rail keeps what a rail is for: glanceable truth. Sync is
 * one click away (line → dashboard → `Sync`), and this component remains a
 * server component — no fetch, no state, just what it was handed.
 *
 * "Last synced" survived the collapse because it is the answer to the question
 * that drove the repeated manual re-syncs: *did this thing ever run?* Whether
 * the last sync SUCCEEDED and when are two different facts — the backend leaves
 * `last_sync_at` at the last good run when one fails — so both still render,
 * one under the other, rather than one overwriting the other.
 *
 * Type: the sync label is no longer `font-mono`. "last synced 3 minutes ago" is
 * a sentence, and globals.css is explicit that a sentence in mono is a defect;
 * mono is for machine values. The machine value is still there for anything
 * that wants it — `LastSynced` puts the absolute UTC instant in `title` and
 * `dateTime`. (`.label-caps`, dropped here for other reasons, was never mono:
 * it is Atkinson, the product's structural voice.)
 */

type FooterProps = {
  gmail: RailGmailData | null;
  userEmail: string | null;
};

/**
 * Is the connected mailbox a *different* account from the signed-in one, and
 * therefore worth naming? Compared case-insensitively: Google echoes the
 * address in whatever case it was typed, and `Aesh@gmail.com` is not a second
 * account. Returns `null` when there is nothing extra to say — either the
 * addresses match, or the status probe carried no address at all, and inventing
 * a second account on screen is exactly what this component must not do.
 */
function distinctMailbox(gmailEmail: string | null, userEmail: string | null): string | null {
  if (!gmailEmail) return null;
  if (!userEmail) return gmailEmail;
  return gmailEmail.trim().toLowerCase() === userEmail.trim().toLowerCase() ? null : gmailEmail;
}

/** Shared with the identity row so the two rows behave as one control strip. */
const ROW =
  "group flex rounded-md px-2 py-1.5 transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-viz-rules";

function ConnectionLine({ gmail, userEmail }: { gmail: RailGmailData; userEmail: string | null }) {
  if (!gmail.connected) {
    return (
      <Link
        href="/settings"
        aria-label="Gmail is not connected — connect it in settings"
        className={`${ROW} items-start gap-2`}
      >
        <span
          aria-hidden="true"
          className="mt-[0.3rem] h-[0.45rem] w-[0.45rem] shrink-0 rounded-full bg-line-strong"
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[11px] text-dim">Gmail not connected</span>
          <span className="block truncate text-[11px] text-dim transition-colors group-hover:text-muted">
            connect in settings <span aria-hidden="true">→</span>
          </span>
        </span>
      </Link>
    );
  }

  const otherMailbox = distinctMailbox(gmail.email, userEmail);

  return (
    <Link
      href="/dashboard"
      aria-label={
        otherMailbox
          ? `Gmail connected as ${otherMailbox} — open dashboard`
          : "Gmail connected — open dashboard"
      }
      className={`${ROW} items-start gap-2`}
    >
      {/* The dot aligns to the FIRST line, not to the centre of the stack: it
          annotates "connected", and the lines below it are that state's detail.
          Nothing here is indented under the address above — the rail is 240px
          wide, and buying the visual indent would cost ~42px of a sync sentence
          that already truncates. */}
      <span className="beta-dot mt-[0.3rem]" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[11px] text-dim transition-colors group-hover:text-muted">
          {otherMailbox ? (
            <>
              Gmail connected as{" "}
              <span title={otherMailbox} className="text-muted">
                {otherMailbox}
              </span>
            </>
          ) : (
            "Gmail connected"
          )}
        </span>
        {/* Its own line, with no prefix or separator around it: `LastSynced`
            renders EMPTY until the browser knows `now` (it refuses to compute a
            relative label on the server), so any "· " glued to it would hang
            there with nothing after it on first paint and with JS off. */}
        <LastSynced at={gmail.lastSyncAt} className="block truncate text-[11px] text-dim" />
        {gmail.syncStatus === "error" ? (
          <span className="block truncate text-[11px] text-reject-ink">
            last sync failed{gmail.syncError ? ` · ${gmail.syncError}` : ""}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

export function RailFooter({ gmail, userEmail }: FooterProps) {
  const initial = userEmail?.charAt(0).toUpperCase() ?? "·";

  return (
    <div className="space-y-0.5">
      <Link
        href="/settings"
        // Named, not just "Account": this link and the not-connected Gmail line
        // both point at /settings, and two adjacent links with near-identical
        // accessible names is how a screen reader loses the plot.
        aria-label={userEmail ? `Signed in as ${userEmail} — open settings` : "Account — open settings"}
        className={`${ROW} items-center gap-2.5`}
      >
        <span
          aria-hidden="true"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line bg-surface-2 text-sm font-semibold text-strong"
        >
          {initial}
        </span>
        <span
          title={userEmail ?? undefined}
          className="min-w-0 flex-1 truncate text-xs text-muted transition-colors group-hover:text-strong"
        >
          {userEmail ?? "account"}
        </span>
      </Link>
      {gmail ? <ConnectionLine gmail={gmail} userEmail={userEmail} /> : null}
    </div>
  );
}
