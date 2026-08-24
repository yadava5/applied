import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import {
  DashboardEmptyState,
  ForwardRoutes,
} from "@/components/dashboard/DashboardEmptyState";
import { RebuildWindowButton } from "@/components/dashboard/SyncBar";
import { LOCKED_BODY_CLASS } from "@/components/shell/geometry";
import { cn } from "@/lib/utils";

/**
 * What a LOCKED dashboard shows below its sync row when nothing is filed.
 *
 * WHY THIS IS A COMPONENT AND NOT JSX INSIDE THE PAGE. It used to be the
 * latter, and that is the whole reason its geometry could be wrong without
 * anything noticing. `/demo/shell` is where this repo's viewport-lock
 * assertions actually execute — the signed-in dashboard needs a session no CI
 * environment has (#188) — and the twin could only ever mount the POPULATED
 * board. So the empty board, which is the first screen of every new account
 * and of every account whose mail is not connected, was measured nowhere, and
 * it quietly kept the flow geometry after #495 locked its populated sibling:
 * chrome scrolling away with the content, which is exactly what got reported.
 *
 * Extracting it is the strongest available fix rather than a tidy-up. A twin
 * that RE-CREATES a subtree can drift from it, and this codebase has the scar:
 * three rounds of "the dashboard is fixed" were verified against a /demo whose
 * composition had silently stopped matching. A twin that MOUNTS the subtree
 * cannot drift, because there is only one of it. `/demo/shell?empty=1` mounts
 * this, so what the specs measure there is this component, not a copy of its
 * class names.
 *
 * The scroll region lives here, on the body, and that placement is the fix
 * itself: `LOCKED_PAGE_CLASS` on the page root only makes the root fill the
 * pane — something inside still has to be the thing that moves, or a tall
 * enough body (a held-mail queue, a narrow window) pushes back out through
 * <main> and the page scrolls as one block again, with the lock still nominally
 * "on". The populated board satisfies that with its worklist; this is the
 * empty board's equivalent.
 */
export function EmptyBoardBody({
  gmailState,
  scanCompleted = false,
  scanFailed = false,
  review = null,
  mode = "live",
}: {
  /**
   * What we know about the mailbox. THREE VALUES, and `unknown` is not a
   * synonym for `disconnected`: a failed status probe is not evidence that
   * nothing is connected, and collapsing the two is the defect #495 removed
   * from this page. Each renders a different sentence because each has a
   * different next step.
   */
  gmailState: "connected" | "disconnected" | "unknown";
  /** A sync has completed successfully at least once. */
  scanCompleted?: boolean;
  /** The last sync ended in an error — changes only the explanatory sentence,
   *  because the SyncBar's own live region carries the retry. */
  scanFailed?: boolean;
  /** The held-mail queue, already built by the caller, or null when nothing is
   *  held. It rides INSIDE this scroll region on purpose: an eight-item queue
   *  must not be able to push the sync row off the screen. */
  review?: React.ReactNode;
  /** Where the two "file an application" forms write. `demo` on the fixture
   *  twin, which mounts this component rather than copying it. */
  mode?: "live" | "demo";
}) {
  return (
    // The testid names the SCROLL REGION, not the card: what the geometry specs
    // have to measure is whether this element overflows its own box, and
    // finding it positionally ("the last div under .page-locked") would quietly
    // start measuring something else the first time the composition changed.
    <div
      className={cn(LOCKED_BODY_CLASS, "space-y-6")}
      data-testid="empty-board-body"
    >
      {/* The body card, three ways. A genuinely fresh user gets the scaffold
          and its routes forward; the other two states are ABOUT the mail
          connection, and say so here — where there is room for a sentence —
          rather than in the SyncBar's single line. */}
      {gmailState === "disconnected" ? (
        <DashboardEmptyState mode={mode} />
      ) : (
        <div className="rounded-2xl border border-line-soft bg-surface p-6 sm:p-8">
          <p className="label-caps">
            {gmailState === "unknown"
              ? "mail status unavailable"
              : scanCompleted
                ? "connected to gmail"
                : "no completed scan yet"}
          </p>
          <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
            {gmailState === "unknown"
              ? "We couldn't check your mail connection."
              : scanCompleted
                ? "No application emails detected yet."
                : "We haven't completed a scan of your mail yet."}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-muted">
            {gmailState === "unknown"
              ? "The check that tells us whether your mail is connected didn't answer, so we can't say why nothing is filed — that is a fault on our side, not a verdict about your mailbox and not a claim that you never connected. Reload in a moment; nothing has been lost."
              : scanCompleted
                ? "We scan your recent mail when you arrive. If your applications are older than 12 months, rebuild from a wider window."
                : scanFailed
                  ? "Nothing is filed because nothing has been read successfully — this is not a verdict that your mailbox holds no applications. The line above says how the last attempt failed and offers a retry; you can also rebuild from a wider window."
                  : "Nothing is filed because your mail hasn't been read yet — this is not a verdict that your mailbox holds no applications. Sync, or choose a window, to run the first scan."}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {/* Offered only when the mailbox is known to be connected: a
                rebuild is a Gmail action, and on an unknown status it would be
                a control whose precondition we have just said out loud we
                could not read. */}
            {gmailState === "connected" ? <RebuildWindowButton /> : null}
            <AddApplicationForm align="start" mode={mode} />
          </div>
          <div className="mt-6">
            <ForwardRoutes />
          </div>
        </div>
      )}

      {review}
    </div>
  );
}
