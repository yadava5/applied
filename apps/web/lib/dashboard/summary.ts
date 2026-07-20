/**
 * Pure, presentation-agnostic derivation of the pipeline summary from a list
 * of applications. Kept free of React and I/O so it is trivial to reason about
 * and reuse across the real dashboard (API rows) and the public demo (fixture
 * rows adapted to the same shape).
 *
 * Every number the dashboard shows comes from here, so "honest states/numbers"
 * has exactly one implementation to audit.
 */
import type { components } from "@/lib/api/schema";

export type Application = components["schemas"]["Application"];

/** The four pipeline stages, in flow order, with their semantic accent. */
export type StageKey = "applied" | "interviewing" | "offered" | "rejected";

export interface StageDef {
  key: StageKey;
  label: string;
  /** Raw backend statuses that fold into this stage. */
  statuses: string[];
  /** CSS custom-property reference for the stage's accent hue. */
  color: string;
}

export const STAGES: StageDef[] = [
  { key: "applied", label: "applied", statuses: ["applied"], color: "var(--text-muted)" },
  {
    key: "interviewing",
    label: "interviewing",
    statuses: ["interviewing", "interview", "assessment"],
    color: "var(--viz-embeddings)",
  },
  { key: "offered", label: "offered", statuses: ["offered", "offer", "accepted"], color: "var(--green)" },
  {
    key: "rejected",
    label: "rejected",
    statuses: ["rejected", "rejection", "withdrawn"],
    color: "var(--red)",
  },
];

const STATUS_TO_STAGE = new Map<string, StageKey>(
  STAGES.flatMap((stage) => stage.statuses.map((status) => [status, stage.key] as const)),
);

/** Map a raw backend status to a pipeline stage. Unknown statuses fall to
 * `applied` so no application is ever invisible on the board. */
export function stageOf(status: string): StageKey {
  return STATUS_TO_STAGE.get(status.toLowerCase()) ?? "applied";
}

/** A status that is a terminal qualifier we tag on the card (accepted/withdrawn). */
export function qualifierOf(status: string): string | null {
  const s = status.toLowerCase();
  return s === "accepted" || s === "withdrawn" ? s : null;
}

export interface PipelineSummary {
  total: number;
  thisWeek: number;
  /** applied + interviewing — live, not-yet-resolved applications. */
  inMotion: number;
  /** offered + accepted. */
  offers: number;
  /** rejected + withdrawn. */
  closed: number;
  /** Share of applications that advanced past "applied" (interviewing+offered). */
  advancedPct: number;
  /** Per-stage counts, in flow order. */
  stages: { stage: StageDef; count: number }[];
}

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Fold raw per-status counts into the display-stage summary. This is the
 * single implementation of stage semantics (which raw statuses roll into
 * which pipeline stage) — both the array path (`summarize`) and the
 * counts-only path (the `GET /applications/summary` endpoint) funnel through
 * here so the dashboard can never show one number derived two different ways.
 *
 * `statusCounts` is keyed by raw backend status; unknown statuses fall to the
 * `applied` stage via `stageOf`, matching the board's "never invisible" rule.
 */
export function summarizeCounts(
  statusCounts: Record<string, number>,
  total: number,
  thisWeek: number,
): PipelineSummary {
  const counts: Record<StageKey, number> = {
    applied: 0,
    interviewing: 0,
    offered: 0,
    rejected: 0,
  };
  let advanced = 0;

  for (const [status, n] of Object.entries(statusCounts)) {
    const stage = stageOf(status);
    counts[stage] += n;
    if (stage === "interviewing" || stage === "offered") advanced += n;
  }

  return {
    total,
    thisWeek,
    inMotion: counts.applied + counts.interviewing,
    offers: counts.offered,
    closed: counts.rejected,
    advancedPct: total > 0 ? Math.round((advanced / total) * 100) : 0,
    stages: STAGES.map((stage) => ({ stage, count: counts[stage.key] })),
  };
}

/**
 * Derive every headline number from the application list. `now` is injectable
 * so tests are deterministic; production passes the real clock.
 *
 * Kept for the demo twin (which holds the full fixture array in memory) and
 * as the reference the counts-only endpoint is validated against. The real
 * dashboard uses `summarizeCounts` fed by the O(1) summary endpoint instead of
 * materializing every row just to count.
 */
export function summarize(applications: Application[], now: number = Date.now()): PipelineSummary {
  const statusCounts: Record<string, number> = {};
  let thisWeek = 0;

  for (const app of applications) {
    statusCounts[app.status] = (statusCounts[app.status] ?? 0) + 1;

    const filed = Date.parse(app.created_at);
    if (!Number.isNaN(filed) && now - filed >= 0 && now - filed <= WEEK_MS) thisWeek += 1;
  }

  return summarizeCounts(statusCounts, applications.length, thisWeek);
}

/** Most-recently-filed applications first — drives the recent-activity feed. */
export function recentApplications(applications: Application[], limit = 6): Application[] {
  return [...applications]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, limit);
}
