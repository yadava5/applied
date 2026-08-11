import { Bell } from "lucide-react";
import Link from "next/link";

import { createServerApiClient } from "@/lib/api/server";
import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { GmailSyncTrigger } from "@/components/dashboard/GmailSyncTrigger";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { ClassifierContext, StatTiles } from "@/components/dashboard/StatTiles";
import { DashboardEmptyState, ForwardRoutes } from "@/components/dashboard/DashboardEmptyState";
import { ReSyncButton } from "@/components/dashboard/ReSyncButton";
import { RetryLoadButton } from "@/components/dashboard/RetryLoadButton";
import { ReviewQueue, type ReviewItem } from "@/components/dashboard/ReviewQueue";
import { StageFunnel } from "@/components/viz/StageFunnel";
import { getReviewQueue } from "@/lib/applications/server";
import { getGmailStatus } from "@/lib/gmail/server";
import { summarizeCounts, type Application, type PipelineSummary } from "@/lib/dashboard/summary";
import { readNotificationPrefs } from "@/lib/settings/notifications";
import { getCurrentUser } from "@/lib/supabase/auth";
import type { NotificationPrefs } from "@/components/settings/NotificationsSection";

/**
 * The signed-in product: a real dashboard. Headline metrics + the funnel come
 * from the lightweight `GET /applications/summary` (counts only — O(1) transfer
 * that stays flat as an account grows), while the status board + recent-activity
 * feed render from a single bounded page of `GET /applications`. The two fetch
 * in parallel, so this is one round-trip of latency and never materializes every
 * row just to compute the tiles.
 *
 * Failure modes stay first-class: an unreachable or unauthorized backend
 * degrades to a labelled error state that names what went wrong, offers a
 * retry, and still routes the user forward — never a blank page, never a crash,
 * and never sample rows dressed up as the user's own pipeline (the shell above
 * already guarantees auth).
 */

/**
 * Upper bound on rows pulled for the board/recent-activity in one page. Large
 * enough that a typical account sees its whole board, capped so a pathological
 * account never ships thousands of rows to the client — the tiles/funnel stay
 * exact regardless via the counts-only summary endpoint.
 */
const BOARD_PAGE_SIZE = 200;

type LoadState =
  | {
      kind: "ok";
      summary: PipelineSummary;
      applications: Application[];
      total: number;
      needsReview: number;
    }
  | { kind: "unauthorized"; message: string }
  | { kind: "offline"; message: string };

/**
 * The needs-classification queue (uncertain verdicts). Fetched server-side via
 * the plain-fetch helper (the endpoint is not in the seed OpenAPI schema);
 * never throws — a failure just yields an empty queue so the board still renders.
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
      return { kind: "unauthorized", message: failureMessage(summaryRes.error, summaryRes.response.status) };
    }
    if (listRes.error || !listRes.data) {
      return { kind: "unauthorized", message: failureMessage(listRes.error, listRes.response.status) };
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

function DashboardHeader({
  subtitle,
  connected = false,
}: {
  subtitle: string;
  /** When Gmail is connected, expose the manual "Re-sync" (purge+rebuild). */
  connected?: boolean;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Pipeline</h1>
        <p className="mt-1 font-mono text-xs text-dim">{subtitle}</p>
      </div>
      <div className="flex items-start gap-2">
        {connected ? <ReSyncButton /> : null}
        {/* Manual filing is the rare path now — the pipeline fills from Gmail —
            so the add control is a compact, unobtrusive "+" rather than a CTA. */}
        <AddApplicationForm compact />
      </div>
    </header>
  );
}

/**
 * The real in-app behavior behind the Settings → Notifications toggles.
 *
 * Those toggles used to persist to the user's metadata but drive nothing, so
 * the controls were effectively cosmetic. Here they gate genuine on-dashboard
 * cues: "Needs-review alerts" surfaces a prominent banner (deep-linked to the
 * review queue) whenever the classifier is holding mail for a decision, and
 * "Weekly pipeline summary" surfaces an in-app digest of what moved this week.
 * Both render only when their toggle is on and there is something to say, so a
 * user who wants a quiet board simply leaves them off. Email delivery is a
 * separate, not-yet-live channel — these are the in-app half, and they are real.
 */
function NotificationCues({
  prefs,
  needsReview,
  total,
  thisWeek,
  inMotion,
  offers,
}: {
  prefs: NotificationPrefs;
  needsReview: number;
  total: number;
  thisWeek: number;
  inMotion: number;
  offers: number;
}) {
  const showReview = prefs.reviewAlerts && needsReview > 0;
  const showWeekly = prefs.weekly && total > 0;
  if (!showReview && !showWeekly) return null;

  return (
    <div className="space-y-2">
      {showReview ? (
        <Link
          href="#needs-classification"
          className="flex items-center gap-2.5 rounded-xl border border-review/40 bg-surface px-4 py-3 text-sm text-strong transition-colors hover:border-review"
        >
          <Bell className="h-4 w-4 shrink-0 text-review" aria-hidden />
          <span>
            {needsReview} email{needsReview === 1 ? " is" : "s are"} held for your review — classify
            {needsReview === 1 ? " it" : " them"} to keep your pipeline accurate.
          </span>
          <span className="ml-auto shrink-0 font-mono text-[11px] text-dim" aria-hidden>
            review ↓
          </span>
        </Link>
      ) : null}
      {showWeekly ? (
        <div
          role="status"
          className="rounded-xl border border-line-soft bg-surface px-4 py-3 font-mono text-[12px] text-muted"
        >
          <span className="text-strong">This week</span> · {thisWeek} new application
          {thisWeek === 1 ? "" : "s"} · {inMotion} in motion · {offers} offer{offers === 1 ? "" : "s"}
        </div>
      ) : null}
    </div>
  );
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

  // A user who has connected Gmail (or imported) is a REAL user: never show
  // them the "sample data · not yours" preview, even when empty or degraded.
  const connected = gmailStatus.kind === "ok" && gmailStatus.status.connected;
  // Sync cursor state, for the auto-sync's staleness rule. Unknown status (a
  // failed probe) leaves these null/false, which reads as "stale" — but the
  // trigger only renders under `connected`, which that same failure clears.
  const lastSyncAt = gmailStatus.kind === "ok" ? gmailStatus.status.last_sync_at : null;
  const hasCursor = gmailStatus.kind === "ok" && gmailStatus.status.has_cursor === true;

  // --- Honest degradation: unreachable / rejected backend --------------------
  //
  // This branch renders NO sample data, and deliberately does not consult
  // `connected`. It used to: a failed load plus `!connected` showed a signed-in
  // user ten fictional companies under an <h1> reading "Pipeline". But
  // `connected` comes from `getGmailStatus()`, which calls the SAME backend and
  // returns non-ok on any 401/403/503/network failure — so a single outage
  // flipped both flags together and the guard could never hold. A user whose
  // own board failed to load gets the failure, a retry, and the routes forward;
  // fixtures are only ever shown to an account we KNOW is empty (below).
  if (state.kind !== "ok") {
    const headline =
      state.kind === "unauthorized"
        ? "We couldn't load your pipeline."
        : "We couldn't reach the server.";
    const detail =
      state.kind === "unauthorized"
        ? `The backend rejected this session: ${state.message}. Signing in again usually clears it.`
        : `The backend didn't answer: ${state.message}. Nothing is lost — your board renders the moment it responds.`;
    return (
      <section className="space-y-8">
        <DashboardHeader subtitle="connection issue · your data could not be loaded" />
        <div
          className="rounded-2xl border border-reject/40 bg-surface p-6 sm:p-8"
          role="alert"
          aria-live="polite"
        >
          {/* The `.label-mono` rule in globals.css is UNLAYERED, so it beats
              any layered Tailwind colour utility — hence the metrics are
              restated here rather than composed, so the reject hue applies. */}
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.09em] text-reject">
            load failed
          </p>
          <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
            {headline}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-muted">{detail}</p>
          <p className="mt-2 max-w-xl font-mono text-[11px] text-dim">
            This is a loading failure, not an empty pipeline — nothing below is your data, because
            we have none to show yet.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <RetryLoadButton />
            {state.kind === "unauthorized" ? (
              <Link
                href="/login?redirect=/dashboard"
                className="font-mono text-[11px] text-dim underline-offset-4 hover:text-strong hover:underline"
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
    // A one-shot background sync tries to fill the board from connected Gmail.
    if (connected) {
      // Zero *filed* applications does not mean zero work for the user: the
      // classifier may be holding low-confidence lifecycle mail for review.
      // Surface that queue here so it is reachable from an otherwise-empty
      // board (otherwise the "N need classification" items are stranded).
      const reviewItems = state.needsReview > 0 ? await loadReviewQueue() : [];
      const reviewNote =
        state.needsReview > 0
          ? ` · ${state.needsReview} ${state.needsReview === 1 ? "needs" : "need"} classification`
          : "";
      return (
        <section className="space-y-6">
          <DashboardHeader
            subtitle={`connected · no applications detected yet${reviewNote}`}
            connected={connected}
          />
          <div className="rounded-2xl border border-line-soft bg-surface p-6 sm:p-8">
            <p className="label-mono">connected to gmail</p>
            <h2 className="mt-3 text-balance text-2xl font-medium tracking-tight text-strong">
              No application emails detected yet.
            </h2>
            <p className="mt-2 max-w-xl text-sm text-muted">
              We scan your recent mail on load. If your pipeline is older, widen the range from the{" "}
              <Link href="/inbox" className="text-strong underline-offset-4 hover:underline">
                classified inbox
              </Link>{" "}
              — or file an application by hand.
            </p>
            <div className="mt-4">
              <GmailSyncTrigger lastSyncAt={lastSyncAt} hasCursor={hasCursor} />
            </div>
            <div className="mt-5">
              <AddApplicationForm align="start" />
            </div>
            <div className="mt-6">
              <ForwardRoutes />
            </div>
          </div>
          {reviewItems.length > 0 ? <ReviewQueue items={reviewItems} /> : null}
        </section>
      );
    }

    // Genuinely fresh user (not connected, nothing imported) → scaffold + sample.
    return (
      <section className="space-y-6">
        <DashboardHeader subtitle="0 filed · start your pipeline" />
        <DashboardEmptyState />
      </section>
    );
  }

  // --- Populated dashboard ---------------------------------------------------
  const { summary } = state;
  const funnelStages = summary.stages.map(({ stage, count }) => ({
    label: stage.label,
    count,
    color: stage.color,
  }));
  const reviewNote = state.needsReview > 0 ? ` · ${state.needsReview} need classification` : "";
  const subtitle = `${summary.total} filed · ${summary.inMotion} in motion · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }${reviewNote}`;

  // Only fetch the queue's rows when the summary says there is something to show.
  const reviewItems = state.needsReview > 0 ? await loadReviewQueue() : [];

  return (
    <section className="space-y-6">
      <DashboardHeader subtitle={subtitle} connected={connected} />

      {/* A populated board keeps itself current too: this is silent unless the
          board is stale (30 min), in which case it folds new mail in and says
          what it found. Renders nothing at all when Gmail is not connected. */}
      {connected ? (
        <GmailSyncTrigger lastSyncAt={lastSyncAt} hasCursor={hasCursor} variant="quiet" />
      ) : null}

      <NotificationCues
        prefs={notifPrefs}
        needsReview={state.needsReview}
        total={summary.total}
        thisWeek={summary.thisWeek}
        inMotion={summary.inMotion}
        offers={summary.offers}
      />

      <StatTiles summary={summary} />
      <ClassifierContext />

      <StageFunnel
        stages={funnelStages}
        total={summary.total}
        caption={`pipeline distribution · ${summary.total} applications`}
        highlight={`${summary.advancedPct}% advanced past applied`}
      />

      <PipelineBoard applications={state.applications} />

      <ReviewQueue items={reviewItems} />

      <RecentActivity applications={state.applications} />
    </section>
  );
}
