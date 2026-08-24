import Link from "next/link";

import { createServerApiClient } from "@/lib/api/server";
import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { DashboardEmptyState, ForwardRoutes } from "@/components/dashboard/DashboardEmptyState";
import { RetryLoadButton } from "@/components/dashboard/RetryLoadButton";
import { ReviewQueue, type ReviewItem } from "@/components/dashboard/ReviewQueue";
import { SinceLastLook } from "@/components/dashboard/SinceLastLook";
import { RebuildWindowButton, SyncBar, type SyncGmailState } from "@/components/dashboard/SyncBar";
import { LOCKED_PAGE_CLASS } from "@/components/shell/geometry";
import { getReviewQueue } from "@/lib/applications/server";
import { getGmailStatus } from "@/lib/gmail/server";
import { BOARD_PAGE_SIZE } from "@/lib/dashboard/boardPage";
// Both derivations the notification prefs drive here are pure and now live in
// `lib/dashboard/boardPrefs.ts` — a Server Component page cannot be imported
// by `node --test`, so nothing about them was assertable while they sat in
// this file (#216).
import { buildSubtitle, reviewSlotFor } from "@/lib/dashboard/boardPrefs";
import { LAST_LOOK_KEY } from "@/lib/dashboard/lastLook";
import { toChangeRow } from "@/lib/dashboard/lastLookStore";
import {
  stageCountsOf,
  summarizeCounts,
  type Application,
  type PipelineSummary,
} from "@/lib/dashboard/summary";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { getCurrentUser } from "@/lib/supabase/auth";

/**
 * The signed-in product: a work surface, not a metrics poster.
 *
 * The page answers exactly two questions, in this order: "what needs me?"
 * (the review queue) and "where does everything stand?" (the worklist). One
 * honest line of state — the subtitle — carries the totals; the board's stage
 * spine carries the per-stage counts. Nothing on the page restates either.
 *
 * The geometry is viewport-locked at desktop: the shell is one screen tall,
 * this page fills its pane exactly (`lg:min-h-0 lg:flex-1`), and the ONLY
 * thing that scrolls is the worklist inside `PipelineBoard`. Below `lg` the
 * lock releases and the page flows normally.
 *
 * The page spends ONE line of chrome above the board's pulse band: the shell's
 * top bar carries the route title now, and everything this page used to stack
 * — the header row, the notice line, the board's own in-column search row —
 * shares the board's command row instead. The SyncBar (subtitle · the
 * change-ledger chip · recency · Sync · ⋯ · +) rides that row through the
 * board's `toolbar` slot, so the /demo twin inherits the identical
 * composition by construction and the worklist gets every reclaimed line.
 * The in-app weekly digest is not a line anywhere — it restated the
 * subtitle's own numbers plus one (task #59), so its one new number
 * (+N this wk) folds into the subtitle itself when the pref asks for it.
 *
 * The pulse's four derived signals — filed-per-week momentum, the age
 * distribution of open rows, deadlines, and how much of the board arrived
 * from mail / is held for review — render as a full-width band across the
 * top of the board's body (`PipelineBoard`'s `pulse` prop). That is the
 * pre-#136 home the owner asked back, at band density instead of the old
 * ~200px strip; the shell rail and the stage spine are both measured,
 * rejected homes for it. They derive from the same rows the board renders,
 * so the board is where they live.
 *
 * Data path unchanged: the counts come from the O(1) `GET
 * /applications/summary`, the board from one bounded page of
 * `GET /applications`, fetched in parallel (and shared with the shell's rail
 * fetch by request memoization — identical URLs). Failure modes stay
 * first-class — an unreachable backend degrades to a labelled error state
 * with a retry and the routes forward, never sample rows dressed as the
 * user's own pipeline.
 */

/**
 * Why the board isn't rendering. The three failures are kept apart because the
 * user's next step differs for each — the same discrimination
 * `lib/gmail/server.ts` makes (`classifyBadResponse`), and for the same reason:
 * collapsing them told everyone their session was the problem. A 500 is not a
 * sign-in problem, and offering "sign in again" for one sends a user round a
 * loop that cannot help.
 */
type LoadState =
  | {
      kind: "ok";
      summary: PipelineSummary;
      applications: Application[];
      total: number;
      needsReview: number;
    }
  /** The backend rejected the JWT (401/403) — expired session or JWKS misconfig. */
  | { kind: "auth"; message: string }
  /** Any other non-2xx: a backend fault. The session is fine; retrying is the move. */
  | { kind: "backend"; message: string; status: number }
  /** The request never completed (network / DNS / timeout). */
  | { kind: "offline"; message: string };

/**
 * The needs-review queue (uncertain verdicts). Fetched server-side via the
 * plain-fetch helper (the endpoint is not in the seed OpenAPI schema); never
 * throws — a failure just yields an empty queue so the board still renders.
 */
async function loadReviewQueue(): Promise<ReviewItem[]> {
  try {
    const r = await getReviewQueue();
    if (!r.ok || typeof r.data !== "object" || r.data === null) return [];
    const items = (r.data as { items?: unknown }).items;
    return Array.isArray(items) ? (items as ReviewItem[]) : [];
  } catch {
    return [];
  }
}

function failureMessage(error: unknown, status: number): string {
  return typeof error === "object" && error && "detail" in error
    ? String((error as { detail: unknown }).detail)
    : `Backend responded ${status}`;
}

/**
 * A non-2xx from either dashboard call, labelled by what it actually means.
 * 401/403 are the only statuses a fresh sign-in can fix; everything else
 * (500, 502, 503, 429…) is ours to answer for and is said as such.
 */
function failureState(error: unknown, status: number): LoadState {
  const message = failureMessage(error, status);
  return status === 401 || status === 403
    ? { kind: "auth", message }
    : { kind: "backend", message, status };
}

async function loadDashboard(): Promise<LoadState> {
  try {
    const api = await createServerApiClient();
    const [summaryRes, listRes] = await Promise.all([
      api.GET("/applications/summary"),
      api.GET("/applications", {
        params: { query: { page: 1, page_size: BOARD_PAGE_SIZE } },
      }),
    ]);

    if (summaryRes.error || !summaryRes.data) {
      return failureState(summaryRes.error, summaryRes.response.status);
    }
    if (listRes.error || !listRes.data) {
      return failureState(listRes.error, listRes.response.status);
    }

    const summary = summarizeCounts(
      summaryRes.data.status_counts,
      summaryRes.data.total,
      summaryRes.data.this_week,
    );
    return {
      kind: "ok",
      summary,
      applications: listRes.data.applications,
      total: summaryRes.data.total,
      needsReview: summaryRes.data.needs_review ?? 0,
    };
  } catch (err) {
    return {
      kind: "offline",
      message: err instanceof Error ? err.message : "Unknown fetch error",
    };
  }
}

export default async function DashboardPage() {
  /**
   * Started here, awaited below — the queue used to be fetched only AFTER the
   * three calls below had all resolved, because the `needsReview > 0` gate it
   * sits behind is read off the summary. Two ~850 ms backend calls in series
   * where one wait would do: measured at 1090 ms for the dashboard's own RSC
   * render (issue #203 §8).
   *
   * This is NOT free, and calling it a pure win would be wrong. The gate is
   * what made it serial, so the only way to overlap the two is to issue the
   * request before its answer is known — which means a user with nothing in
   * review now pays one extra backend call they did not make before. It costs
   * them no wall-clock time (it runs inside the same wait), but it takes the
   * dashboard's fan-out from 3 concurrent calls to 4, and issue #203 §4
   * measured CONCURRENCY, not idleness, as what triggers a cold start. 4 is
   * well inside the fan-out that came back clean there (3 → zero cold starts;
   * 8 → three), so the trade is taken deliberately rather than assumed away.
   *
   * Floating it until the gate is read is safe because `loadReviewQueue` never
   * rejects — every failure path returns `[]` — so an un-awaited promise
   * cannot become an unhandled rejection.
   */
  const reviewQueue = loadReviewQueue();
  const [state, gmailStatus, user] = await Promise.all([
    loadDashboard(),
    getGmailStatus(),
    getCurrentUser(),
  ]);
  const notifPrefs = readNotificationPrefs((user?.user_metadata ?? {}) as Record<string, unknown>);

  // A failed status probe is UNKNOWN, not disconnected — the SyncBar renders
  // no gmail cluster at all rather than a guessed state.
  const gmail: SyncGmailState | null =
    gmailStatus.kind === "ok"
      ? {
          connected: gmailStatus.status.configured && gmailStatus.status.connected,
          lastSyncAt: gmailStatus.status.last_sync_at,
          hasCursor: gmailStatus.status.has_cursor === true,
          syncStatus: gmailStatus.status.sync_status ?? null,
          syncError: gmailStatus.status.sync_error ?? null,
        }
      : null;

  /**
   * Three states, not two.
   *
   * `connected` used to be `gmail?.connected === true` and nothing else, which
   * is false both when Gmail is genuinely not connected AND when the status
   * probe itself failed — `getGmailStatus()` returns a non-"ok" kind on a
   * network fault, a backend 500 or a rejected session, and every one of those
   * collapsed into "you have not connected your mail". A user whose probe
   * timed out was told, in the product's own voice, a fact about their account
   * that we had not established.
   *
   * The SyncBar's handling of the same null is deliberate and stays exactly as
   * it was: it renders no gmail cluster at all rather than a guessed one. This
   * value is for the BODY copy, which has the room to say "we couldn't check".
   */
  const gmailState: "connected" | "disconnected" | "unknown" =
    gmailStatus.kind !== "ok" ? "unknown" : gmail?.connected === true ? "connected" : "disconnected";
  const connected = gmailState === "connected";

  // Has a scan actually COMPLETED? "No application emails detected yet" is a
  // verdict about the mailbox, and only a finished scan can deliver it. The
  // backend holds `last_sync_at` at the last SUCCESSFUL sync and flips
  // `sync_status` to "error" when one fails, so both facts are needed: a user
  // whose first sync errored was being told the scan ran and found nothing,
  // directly above the SyncBar's alert saying it failed.
  //
  // The two not-completed cases are kept apart because their next step is not
  // the same, and because only ONE of them puts a line in the SyncBar: a
  // failed run renders "last sync failed · try again", while a never-attempted
  // one leaves that live region empty (the arrival auto-sync is bounded by a
  // per-tab cooldown), so pointing at a retry line that isn't there would be
  // the very thing this fix is about.
  const scanFailed = connected && gmail?.syncStatus === "error";
  const scanCompleted = connected && gmail?.lastSyncAt != null && !scanFailed;

  // --- Honest degradation: unreachable / rejected backend --------------------
  //
  // This branch renders NO sample data, and deliberately does not consult
  // `connected` (a single backend outage flips both flags together — see the
  // git history of this file). A user whose own board failed to load gets the
  // failure, a retry, and the routes forward.
  if (state.kind !== "ok") {
    const headline =
      state.kind === "offline"
        ? "We couldn't reach the server."
        : "We couldn't load your applications.";
    // Only an auth rejection is a session problem. A 500 told through the same
    // words sent people to sign in again — a loop that could not help them.
    const detail =
      state.kind === "auth"
        ? `The backend rejected this session: ${state.message}. Signing in again usually clears it.`
        : state.kind === "backend"
          ? `The backend answered ${state.status}: ${state.message}. That's a fault on our side, not a problem with your session or your account — try again in a moment.`
          : `The backend didn't answer: ${state.message}. Nothing is lost — your board renders the moment it responds.`;
    return (
      <section className="space-y-8">
        <SyncBar
          subtitle="connection issue · your data could not be loaded"
          gmail={null}
          title="Applications"
          signedIn
        >
          <AddApplicationForm compact />
        </SyncBar>
        <div
          className="rounded-2xl border border-reject/40 bg-surface p-6 sm:p-8"
          role="alert"
          aria-live="polite"
        >
          <p className="label-caps text-reject-ink">load failed</p>
          <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
            {headline}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-muted">{detail}</p>
          <p className="mt-2 max-w-xl text-xs text-dim">
            This is a loading failure, not an empty board — nothing below is your data, because we
            have none to show yet.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <RetryLoadButton />
            {state.kind === "auth" ? (
              <Link
                href="/login?redirect=/dashboard"
                className="text-xs text-dim underline-offset-4 hover:text-strong hover:underline"
              >
                or sign in again →
              </Link>
            ) : null}
          </div>
        </div>
        <ForwardRoutes />
      </section>
    );
  }

  // --- Empty: nothing filed yet ---------------------------------------------
  //
  // ONE branch for every empty board. There used to be two — connected, and
  // everything else — and the split cost real work: the review queue was
  // rendered ONLY inside the connected branch, so a user with held mail whose
  // Gmail was disconnected (or whose token had expired, or whose status probe
  // merely failed) could not reach it from the one surface that offers it. The
  // queue is gated on the queue's own quantity now, not on the mail connection
  // (#495).
  //
  // Never fake rows in any of the three states: the fixture board that used to
  // sit under this page left with `SamplePreview` in the same issue. The
  // SyncBar's staleness rule still runs its one additive scan on arrival and
  // reports in the header's status line.
  if (state.total === 0) {
    // Zero *filed* applications does not mean zero work: the classifier may be
    // holding low-confidence lifecycle mail for review. Deliberately NOT gated
    // on `connected` — that gate is the defect described above.
    const reviewItems = state.needsReview > 0 ? await reviewQueue : [];
    const reviewNote =
      state.needsReview > 0
        ? ` · ${state.needsReview} ${state.needsReview === 1 ? "needs" : "need"} review`
        : "";

    const subtitle =
      gmailState === "connected"
        ? `connected · ${
            scanCompleted ? "no applications detected yet" : "no applications filed yet"
          }${reviewNote}`
        : gmailState === "unknown"
          ? `0 filed · mail connection unknown${reviewNote}`
          : `0 filed · nothing tracked yet${reviewNote}`;

    return (
      <section className="space-y-6">
        <SyncBar subtitle={subtitle} gmail={gmail} title="Applications" signedIn>
          <AddApplicationForm compact />
        </SyncBar>

        {/* The body card, three ways. A genuinely fresh user gets the scaffold
            and its routes forward; the other two states are ABOUT the mail
            connection, and say so here — where there is room for a sentence —
            rather than in the SyncBar's single line. */}
        {gmailState === "disconnected" ? (
          <DashboardEmptyState />
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
                  rebuild is a Gmail action, and on an unknown status it would
                  be a control whose precondition we have just said out loud we
                  could not read. */}
              {gmailState === "connected" ? <RebuildWindowButton /> : null}
              <AddApplicationForm align="start" />
            </div>
            <div className="mt-6">
              <ForwardRoutes />
            </div>
          </div>
        )}

        {reviewItems.length > 0 ? (
          <ReviewQueue items={reviewItems} applications={state.applications} />
        ) : null}
      </section>
    );
  }

  // --- Populated dashboard ---------------------------------------------------
  const { summary } = state;
  const subtitle = buildSubtitle(summary, notifPrefs.weekly);

  // Only fetch the queue's rows when the summary says there is something to show.
  const reviewItems = state.needsReview > 0 ? await reviewQueue : [];

  const queue =
    reviewItems.length > 0 ? (
      <ReviewQueue items={reviewItems} applications={state.applications} />
    ) : null;

  return (
    <section className={LOCKED_PAGE_CLASS}>
      {/* The sync surface is the page's top line: at `lg`+ the shell's TopBar
          yields on this route and this row carries the title, the state, the
          change ledger and the sync controls — one line where a 92%-empty bar
          plus a second header row used to sit. Sign-out rides inside the
          row's ⋯ menu (`signedIn`), not as a row-level button: the button
          is what wrapped this row to 82px at 1024 (#172). The /demo twin
          composes the identical row (with the demo pill in the trailing
          slot), so the two cannot drift.

          SinceLastLook is the notification chip overlaid on that row's
          centre (#212): client-only (the marker is
          this browser's), per user, and silent until it has a previous visit
          to compare against. The rows are projected here so the flight
          payload carries six fields per row rather than the whole record
          twice.

          No id, no ledger — never a shared "anon" scope. One marker key holds
          one board, so a record written under a fallback scope would OVERWRITE
          the signed-in owner's, silently destroying the unread digest this
          feature's whose-marker-advances rules exist to protect. The layout
          redirects a session-less request before this page's HTML ships, so
          the branch should be unreachable; borrowing that guarantee from
          another file is what makes it worth stating here. Same discipline as
          the SyncBar's gmail cluster: an unknown state renders nothing rather
          than a guessed one. */}
      <SyncBar
        subtitle={subtitle}
        gmail={gmail}
        title="Applications"
        signedIn
        since={
          user?.id ? (
            <SinceLastLook
              rows={state.applications.map(toChangeRow)}
              total={state.total}
              scope={user.id}
              storageKey={LAST_LOOK_KEY}
            />
          ) : null
        }
      >
        <AddApplicationForm compact />
      </SyncBar>

      {/* The board owns the rest of the pane. Its stage lens + search live in
          the shell's rail (portaled by the board itself — state stays with
          the list they filter), so the worklist takes the full measure.

          "Needs review alerts" decides whether held mail interrupts the list
          (above the rows) or waits under it — the quiet-board promise the
          Settings toggle describes, kept real. Both placements live INSIDE the
          list's scroll context, so an eight-item queue can never starve the
          worklist of its viewport.

          `total` and `stageTotals` both come from the summary endpoint, and
          the board's prop type makes them inseparable: the stage lens states
          the ACCOUNT's per-stage counts (a `GROUP BY status` in the
          database), not the shape of the page that happened to load. Past
          BOARD_PAGE_SIZE the two differ, and a lens summing to the page while
          the subtitle says the account is exactly the contradiction the scope
          note exists for. */}
      <PipelineBoard
        variant="locked"
        applications={state.applications}
        total={state.total}
        stageTotals={stageCountsOf(state.summary)}
        pulse={{ needsReview: state.needsReview }}
        beforeList={reviewSlotFor(notifPrefs) === "before" ? queue : null}
        afterList={reviewSlotFor(notifPrefs) === "after" ? queue : null}
      />
    </section>
  );
}
