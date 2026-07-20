import { createServerApiClient } from "@/lib/api/server";
import { AddApplicationForm } from "@/components/applications/AddApplicationForm";
import { PipelineBoard } from "@/components/dashboard/PipelineBoard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { ClassifierContext, StatTiles } from "@/components/dashboard/StatTiles";
import {
  DashboardEmptyState,
  ForwardRoutes,
  SamplePreview,
} from "@/components/dashboard/DashboardEmptyState";
import { StageFunnel } from "@/components/viz/StageFunnel";
import { summarizeCounts, type Application, type PipelineSummary } from "@/lib/dashboard/summary";

/**
 * The signed-in product: a real dashboard. Headline metrics + the funnel come
 * from the lightweight `GET /applications/summary` (counts only — O(1) transfer
 * that stays flat as an account grows), while the status board + recent-activity
 * feed render from a single bounded page of `GET /applications`. The two fetch
 * in parallel, so this is one round-trip of latency and never materializes every
 * row just to compute the tiles.
 *
 * Failure modes stay first-class: an unreachable or unauthorized backend
 * degrades to a labelled state that still routes the user forward and previews
 * the product, never a blank page or a crash (the shell above already
 * guarantees auth).
 */

/**
 * Upper bound on rows pulled for the board/recent-activity in one page. Large
 * enough that a typical account sees its whole board, capped so a pathological
 * account never ships thousands of rows to the client — the tiles/funnel stay
 * exact regardless via the counts-only summary endpoint.
 */
const BOARD_PAGE_SIZE = 200;

type LoadState =
  | { kind: "ok"; summary: PipelineSummary; applications: Application[]; total: number }
  | { kind: "unauthorized"; message: string }
  | { kind: "offline"; message: string };

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
    };
  } catch (err) {
    return {
      kind: "offline",
      message: err instanceof Error ? err.message : "Unknown fetch error",
    };
  }
}

function DashboardHeader({ subtitle }: { subtitle: string }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-strong">Pipeline</h1>
        <p className="mt-1 font-mono text-xs text-dim">{subtitle}</p>
      </div>
      <AddApplicationForm />
    </header>
  );
}

export default async function DashboardPage() {
  const state = await loadDashboard();

  // --- Honest degradation: unreachable / rejected backend --------------------
  if (state.kind !== "ok") {
    const message =
      state.kind === "unauthorized"
        ? `The backend rejected the session: ${state.message}`
        : `The backend is unreachable — your board renders the moment it answers. (${state.message})`;
    return (
      <section className="space-y-8">
        <DashboardHeader subtitle="connection issue · showing a preview" />
        <div
          className="rounded-xl border border-line-soft bg-surface px-4 py-3 font-mono text-sm text-muted"
          role="status"
        >
          {message}
        </div>
        <ForwardRoutes />
        <SamplePreview />
      </section>
    );
  }

  // --- Empty: nothing filed yet ---------------------------------------------
  if (state.total === 0) {
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
  const subtitle = `${summary.total} filed · ${summary.inMotion} in motion · ${summary.offers} offer${
    summary.offers === 1 ? "" : "s"
  }`;

  return (
    <section className="space-y-6">
      <DashboardHeader subtitle={subtitle} />

      <StatTiles summary={summary} />
      <ClassifierContext />

      <StageFunnel
        stages={funnelStages}
        total={summary.total}
        caption={`pipeline distribution · ${summary.total} applications`}
        highlight={`${summary.advancedPct}% advanced past applied`}
      />

      <PipelineBoard applications={state.applications} />

      <RecentActivity applications={state.applications} />
    </section>
  );
}
