"use client";

import Link from "next/link";

import { LastSynced } from "@/components/gmail/LastSynced";
import type { RailGmailData } from "@/lib/shell/rail";
import { useDemoMode } from "./demo-mode";
import { demoHrefFor } from "./nav";
import { DemoSignupCta } from "./SessionControls";

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
 * So the identity row leads, and the connection is a subordinate line beneath
 * it. The order flipped with it — identity used to sit under the chip; it is
 * now the anchor, because the account is the thing and the connection is
 * something the account *has*. (Flipping the two lines back was considered
 * again in Aug 2026 and rejected — the order stands.) Identity still lives
 * bottom-left (the Linear/Notion convention); sign-out lives in the top
 * chrome — the bar, or the board header's ⋯ menu where the bar yields at
 * `lg`+ (#172) — never here.
 *
 * The identity row shows the user's NAME, not the address — chosen explicitly
 * ("(A) Ayush Yadav" over the email), falling back to the address only when no
 * name is set. The email still ARRIVES as a prop and still matters: it is what
 * `distinctMailbox` compares the connected Gmail account against, and it rides
 * in the row's `title` and aria-label. When the two accounts genuinely DIFFER
 * — signed in as one, Gmail connected as another — the connection line names
 * its own address ("connected as billing@corp.com"). Which means the *absence*
 * of a second address is what asserts the two are the same mailbox. That is a
 * quiet read, and it is the deliberate trade — so never stop passing
 * `userEmail` just because the row no longer prints it: the comparison is the
 * assertion's whole basis.
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
 * one click away (line → dashboard → `Sync`), and this component still holds
 * no fetch and no state — just what it was handed, plus one context read.
 * (It is a client component now, and honestly was before: `Sidebar`, its one
 * importer, is `"use client"`, so this always compiled into the client graph.
 * The directive arrived with `useDemoMode`, which merely made it true on the
 * label too.)
 *
 * Fixture mode (`useDemoMode`, /demo and /demo/shell): the demo's conversion
 * block (`DemoSignupCta`) lives HERE, in chrome the signed-in shell spends on
 * identity, because the board is the pitch and must not be covered, shifted
 * or shortened by an ad for itself — the rail is a fixed 240px column and the
 * footer anchors to its bottom, so nothing about the BOARD's geometry moves.
 * What CAN move is the rail's own middle run, and that is a hard budget, not
 * a vibe — measured on the production build: the logo block is 67px, the
 * nav + stage lens + search content is 469px, so a 693px window (the owner's
 * real 1309×693, the exact height PR #122 died on) leaves 157px for this
 * footer. The signed-in footer spends ~115. The first cut of this block
 * ADDED 163px to that and silently scrolled the lens's `closed` row below
 * the fold — the #122 failure mode with a new author. So the footer is
 * tiered on viewport height, and the short tier REPLACES the identity
 * theater instead of stacking under it:
 *
 *   - under 860px: `DemoSignupCta compact` alone (~144px total) — sentence,
 *     button, beta line. The fixture identity and connection rows yield;
 *     what they said ("this is a stand-in account") stays said by the board
 *     row's one honesty badge, which is per-width since #212: the
 *     `demo · fixture data` pill at `lg`+ (every width this tier serves on
 *     desktop), the "simulated account · nothing is read" phrase below `lg`,
 *     where the pill's trailing slot is gone. An earlier revision of this
 *     note credited the phrase at ALL widths — wrong, it is `lg:hidden`
 *     beside the pill; session-edge.spec asserts both halves.
 *   - 860px and up: the full block — identity row, connection line, then the
 *     pitch (~281px; an 860px window affords 324). Links resolve to the
 *     public twins (`demoNavHrefs`), because /settings and /dashboard are
 *     auth bounces for the anonymous visitor this shell serves.
 *
 * Both tiers are in the DOM (CSS `min-height` media picks one), so the SSR
 * payload and every executing locator see one stable tree; specs that touch
 * the CTA must scope to the visible tier.
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
  /** Display name; `null` falls back to the email so the row is never blank. */
  userName?: string | null;
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
  "group flex rounded-md px-2 py-1.5 transition-colors hover:bg-surface-2 focus-accent";

function ConnectionLine({ gmail, userEmail }: { gmail: RailGmailData; userEmail: string | null }) {
  // In fixture mode both destinations are auth bounces; resolve to the twins.
  const demo = useDemoMode();
  if (!gmail.connected) {
    return (
      <Link
        href={demo ? demoHrefFor("/settings") : "/settings"}
        aria-label="Gmail is not connected — connect it in settings"
        className={`${ROW} items-start gap-2`}
      >
        <span
          aria-hidden="true"
          className="mt-[0.3rem] h-[0.45rem] w-[0.45rem] shrink-0 rounded-full bg-line-strong"
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[11px] text-dim">Gmail not connected</span>
          {/* `muted`, not `dim`, and brighter than the state above it: this is
              the only actionable thing in the not-connected state, and `dim` is
              the ramp's FLOOR for text this size (Lc 60.7, see globals.css) —
              the call to action must not be the quietest thing in the block. */}
          <span className="block truncate text-[11px] text-muted transition-colors group-hover:text-strong">
            connect in settings <span aria-hidden="true">→</span>
          </span>
        </span>
      </Link>
    );
  }

  const otherMailbox = distinctMailbox(gmail.email, userEmail);

  return (
    <Link
      href={demo ? demoHrefFor("/dashboard") : "/dashboard"}
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

export function RailFooter({ gmail, userName = null, userEmail }: FooterProps) {
  const demo = useDemoMode();
  // The avatar initial follows whatever the row prints, so the two agree.
  const identity = userName ?? userEmail;
  const initial = identity?.charAt(0).toUpperCase() ?? "·";

  const identityBlock = (
    <div className="space-y-0.5">
      <Link
        href={demo ? demoHrefFor("/settings") : "/settings"}
        // Named, not just "Account": this link and the not-connected Gmail line
        // both point at /settings, and two adjacent links with near-identical
        // accessible names is how a screen reader loses the plot. The email
        // stays in the name beside the visible text (WCAG 2.5.3 wants the
        // rendered name contained in the accessible name) — with hover gone,
        // this is where a screen reader still gets the mailbox.
        aria-label={
          userName && userEmail
            ? `Signed in as ${userName} (${userEmail}) — open settings`
            : identity
              ? `Signed in as ${identity} — open settings`
              : "Account — open settings"
        }
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
          {identity ?? "account"}
        </span>
      </Link>
      {gmail ? <ConnectionLine gmail={gmail} userEmail={userEmail} /> : null}
    </div>
  );

  if (!demo) return identityBlock;

  // The height-tiered demo footer — the budget arithmetic is in the header
  // note. 860px: the full block needs 281px under a 536px fixed run, plus
  // headroom for font metrics; below it, the compact tier's 144px fits the
  // 693px floor with 13px to spare.
  return (
    <>
      {/* Tall rails: the identity theater, then the invitation under its own
          rule — where the stand-in identity ends, the ask begins. */}
      <div className="hidden [@media(min-height:860px)]:block">
        {identityBlock}
        <div className="mt-2 border-t border-line-soft px-2 pb-1 pt-3">
          <DemoSignupCta />
        </div>
      </div>
      {/* Short rails: the invitation alone, inside the signed-in footer's own
          height budget, so the stage lens above never loses a row to it. */}
      <div className="px-2 pb-1 [@media(min-height:860px)]:hidden">
        <DemoSignupCta compact />
      </div>
    </>
  );
}
