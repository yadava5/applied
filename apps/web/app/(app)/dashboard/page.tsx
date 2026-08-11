import Link from "next/link";

import { createServerApiClient } from "@/lib/api/server";
import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { DashboardEmptyState, ForwardRoutes } from "@/components/dashboard/DashboardEmptyState";
import { RetryLoadButton } from "@/components/dashboard/RetryLoadButton";
import { ReviewQueue, type ReviewItem } from "@/components/dashboard/ReviewQueue";
import { SinceLastLook } from "@/components/dashboard/SinceLastLook";
import { RebuildWindowButton, SyncBar, type SyncGmailState } from "@/components/dashboard/SyncBar";
import { getReviewQueue } from "@/lib/applications/server";
import { getGmailStatus } from "@/lib/gmail/server";
import { LAST_LOOK_KEY } from "@/lib/dashboard/lastLook";
import { toChangeRow } from "@/lib/dashboard/lastLookStore";
import { summarizeCounts, type Application, type PipelineSummary } from "@/lib/dashboard/summary";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { getCurrentUser } from "@/lib/supabase/auth";

/**
 * The signed-in product: a work surface, not a metrics poster.
 *
 * The page answers exactly two questions, in this order: "what needs me?"
 * (the review queue) and "where does everything stand?" (the board). One
 * honest line of state — the subtitle — carries the totals; the board columns
 * carry the per-stage counts. Nothing on the page restates either. The stat
 * tiles, the classifier-context strip, the distribution bars and the
 * recent-activity feed are gone: each was a second (or sixth) rendering of a
 * number already on screen, and the classifier strip was CI provenance shown
 * to somebody trying to find a job.
 *
 * The pulse strip (`PipelinePulse`) is not those coming back: every cell on it
 * is DERIVED signal the subtitle and the columns cannot express — filed-per-
 * week momentum, the age distribution of open rows, and how much of the board
 * the classifier built / is holding — each computed once, in `lib/dashboard/
 * age.ts`, from the same rows the board renders.
 *
 * Data path unchanged: the counts come from the O(1) `GET
 * /applications/summary`, the board from one bounded page of
 * `GET /applications`, fetched in parallel. Failure modes stay first-class —
 * an unreachable backend degrades to a labelled error state with a retry and
 * the routes forward, never sample rows dressed as the user's own pipeline.
 */

/**
 * Upper bound on rows pulled for the board in one page. Large enough that a
 * typical account sees its whole board, capped so a pathological account never
 * ships thousands of rows to the client — the subtitle stays exact regardless
 * via the counts-only summary endpoint.
 */
const BOARD_PAGE_SIZE = 200;

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

/** The page's one prose data line — its only rendering of the totals. The
 *  needs-review count is NOT here anymore: the pulse strip's classifier cell
 *  owns it (with the deep link), so the number renders once. */
function buildSubtitle(summary: PipelineSummary): string {
  return `${summary.total} filed · ${summary.inMotion} in motion · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;
}

export default async function DashboardPage() {
  const [state, gmailStatus, user] = await Promise.all([
    loadDashboard(),
    getGmailStatus(),
    getCurrentUser(),
  ]);
  const notifPrefs = readNotificationPrefs(
    (user?.user_metadata ?? {}) as Record<string, unknown>,
  );

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
  const connected = gmail?.connected === true;

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
        : "We couldn't load your pipeline.";
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
        <SyncBar subtitle="connection issue · your data could not be loaded" gmail={null}>
          <AddApplicationForm compact />
        </SyncBar>
        <div
          className="rounded-2xl border border-reject/40 bg-surface p-6 sm:p-8"
          role="alert"
          aria-live="polite"
        >
          <p className="label-caps text-reject">load failed</p>
          <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
            {headline}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-muted">{detail}</p>
          <p className="mt-2 max-w-xl text-xs text-dim">
            This is a loading failure, not an empty pipeline — nothing below is your data, because
            we have none to show yet.
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
  if (state.total === 0) {
    // Connected but empty → honest real-empty state (never fake sample rows).
    // The SyncBar's staleness rule runs its one additive scan on arrival and
    // reports in the header's status line.
    if (connected) {
      // Zero *filed* applications does not mean zero work: the classifier may
      // be holding low-confidence lifecycle mail for review.
      const reviewItems = state.needsReview > 0 ? await loadReviewQueue() : [];
      const reviewNote =
        state.needsReview > 0
          ? ` · ${state.needsReview} ${state.needsReview === 1 ? "needs" : "need"} review`
          : "";
      return (
        <section className="space-y-6">
          <SyncBar
            subtitle={`connected · ${
              scanCompleted ? "no applications detected yet" : "no applications filed yet"
            }${reviewNote}`}
            gmail={gmail}
          >
            <AddApplicationForm compact />
          </SyncBar>
          <div className="rounded-2xl border border-line-soft bg-surface p-6 sm:p-8">
            <p className="label-caps">
              {scanCompleted ? "connected to gmail" : "no completed scan yet"}
            </p>
            <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
              {scanCompleted
                ? "No application emails detected yet."
                : "We haven't completed a scan of your mail yet."}
            </h2>
            <p className="mt-2 max-w-xl text-sm text-muted">
              {scanCompleted
                ? "We scan your recent mail when you arrive. If your applications are older than 12 months, rebuild from a wider window."
                : scanFailed
                  ? "Nothing is filed because nothing has been read successfully — this is not a verdict that your mailbox holds no applications. The line above says how the last attempt failed and offers a retry; you can also rebuild from a wider window."
                  : "Nothing is filed because your mail hasn't been read yet — this is not a verdict that your mailbox holds no applications. Sync, or choose a window, to run the first scan."}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <RebuildWindowButton />
              <AddApplicationForm align="start" />
            </div>
            <div className="mt-6">
              <ForwardRoutes />
            </div>
          </div>
          {reviewItems.length > 0 ? (
            <ReviewQueue items={reviewItems} applications={state.applications} />
          ) : null}
        </section>
      );
    }

    // Genuinely fresh user (not connected, nothing imported) → scaffold + sample.
    return (
      <section className="space-y-6">
        <SyncBar subtitle="0 filed · start your pipeline" gmail={gmail}>
          <AddApplicationForm compact />
        </SyncBar>
        <DashboardEmptyState />
      </section>
    );
  }

  // --- Populated dashboard ---------------------------------------------------
  const { summary } = state;
  const subtitle = buildSubtitle(summary);

  // Only fetch the queue's rows when the summary says there is something to show.
  const reviewItems = state.needsReview > 0 ? await loadReviewQueue() : [];

  const queue =
    reviewItems.length > 0 ? (
      <ReviewQueue items={reviewItems} applications={state.applications} />
    ) : null;

  return (
    <section className="space-y-6">
      <SyncBar subtitle={subtitle} gmail={gmail}>
        <AddApplicationForm compact />
      </SyncBar>

      {/* What happened while you were away — the one thing a board of
          identical cards cannot say. Client-only (the marker is this
          browser's), per user, and silent until it has a previous visit to
          compare against. The rows are projected here so the flight payload
          carries six fields per row rather than the whole record twice. */}
      <SinceLastLook
        rows={state.applications.map(toChangeRow)}
        total={state.total}
        scope={user?.id ?? "anon"}
        storageKey={LAST_LOOK_KEY}
      />

      {/* The three signals the rows carry that the board can't show as
          columns: momentum over time, how the open pipeline is ageing, and
          what the classifier built/held (see PipelinePulse). */}
      <PipelinePulse
        applications={state.applications}
        total={state.total}
        needsReview={state.needsReview}
      />

      {/* The in-app weekly digest — pref-gated, and only when there is a week
          to report. The review half of the old NotificationCues banner is gone:
          the queue itself now sits where the banner pointed. */}
      {notifPrefs.weekly && summary.total > 0 && summary.thisWeek > 0 ? (
        <div
          role="status"
          className="rounded-xl border border-line-soft bg-surface px-4 py-3 text-[13px] text-muted"
        >
          <span className="text-strong">This week</span> · {summary.thisWeek} new application
          {summary.thisWeek === 1 ? "" : "s"} · {summary.inMotion} in motion · {summary.offers}{" "}
          offer{summary.offers === 1 ? "" : "s"}
        </div>
      ) : null}

      {/* "Needs review alerts" now decides whether held mail interrupts the
          board (above) or waits under it (below) — the quiet-board promise the
          Settings toggle describes, kept real. */}
      {notifPrefs.reviewAlerts ? queue : null}

      {/* `total` is the account's true count, not the page's: past
          BOARD_PAGE_SIZE the board says which slice it is showing, so the
          subtitle's "250 filed" and four columns summing to 200 stop
          contradicting each other. */}
      <PipelineBoard applications={state.applications} total={state.total} />

      {!notifPrefs.reviewAlerts ? queue : null}
    </section>
  );
}
