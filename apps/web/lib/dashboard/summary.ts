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
import { filedAt } from "@/lib/dashboard/dates";

/**
 * A board row, as the cloud backend actually serves it. The name on the wire is
 * `CloudApplicationResponse` (`backend/jobtracker/cloud/applications.py`); the
 * old alias pointed at a hand-written `Application` schema that no endpoint has
 * ever returned, so `status` read as a free `string` and the row's
 * `dismissed_at` / `dismissed_reason` fields were invisible to the compiler.
 */
export type Application = components["schemas"]["CloudApplicationResponse"];

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
  // `--stage-applied`, not `--text-muted`: the resting stage stays achromatic
  // on purpose, but the old text-ramp value measured 2.56:1 in the card-border
  // wash — dimmer than the chrome around it. The dedicated token is a
  // luminance fix only (measured 9.25:1 solid, 3.62:1 at the 55% wash).
  { key: "applied", label: "applied", statuses: ["applied"], color: "var(--stage-applied)" },
  {
    key: "interviewing",
    label: "interviewing",
    statuses: ["interviewing", "interview", "assessment"],
    color: "var(--viz-embeddings)",
  },
  { key: "offered", label: "offered", statuses: ["offered", "offer", "accepted"], color: "var(--green)" },
  {
    key: "rejected",
    // Labelled "closed" because the bucket is not only rejections: a withdrawal
    // is the user's own decision and a ghosting is nobody's. `PipelineSummary`
    // has always called this `closed` (see :111), so this makes the board agree
    // with the summary rather than the two using different words for one thing.
    // The key stays `rejected` because it is the counts object's shape.
    label: "closed",
    // `ghosted` belongs here explicitly. It is a real `ApplicationStatus` and it
    // was in no stage at all, so `stageOf` fell through to its `?? "applied"`
    // default and a ghosted application was counted as applied AND as in-motion.
    // Harmless while nothing could set it; it became reachable the moment the
    // stage vocabulary was corrected to include it.
    statuses: ["rejected", "rejection", "withdrawn", "ghosted"],
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

/**
 * A status that is a terminal qualifier we tag on the card. These are statuses
 * whose stage does not tell you what happened: "closed" covers a rejection, a
 * withdrawal and a ghosting, and "offered" covers both an open offer and an
 * accepted one, so the card has to say which.
 */
export function qualifierOf(status: string): string | null {
  const s = status.toLowerCase();
  return s === "accepted" || s === "withdrawn" || s === "ghosted" ? s : null;
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
 * The summary's per-stage counts as a keyed record — the shape the board's
 * spine reads. Folded here rather than at the call site so the spine's numbers
 * and the subtitle's numbers keep coming out of one implementation of stage
 * semantics; a second `for` loop over `status_counts` somewhere else is how
 * two surfaces start disagreeing about what "closed" contains.
 */
export function stageCountsOf(summary: PipelineSummary): Record<StageKey, number> {
  const counts: Record<StageKey, number> = {
    applied: 0,
    interviewing: 0,
    offered: 0,
    rejected: 0,
  };
  for (const { stage, count } of summary.stages) counts[stage.key] = count;
  return counts;
}

/**
 * The slice of a row the pulse's four derived signals actually read (see
 * `components/dashboard/PipelinePulse.tsx`): filed date (momentum, ageing),
 * status (which rows count as open), deadline, source (classifier share) and
 * the company name the deadline cell prints. Kept a projection on purpose —
 * these rows ride to the client twice on /dashboard (board props and shell
 * rail props), and the rail must not ship the whole board a second time.
 * `Application` is structurally assignable, so callers that hold full rows
 * (the demo twin) pass them as-is.
 */
export type PulseRow = Pick<
  Application,
  "company" | "status" | "source" | "due_at" | "applied_date" | "created_at"
>;

/** Project a full row down to exactly what the pulse reads. */
export function toPulseRow(app: Application): PulseRow {
  return {
    company: app.company,
    status: app.status,
    source: app.source,
    due_at: app.due_at,
    applied_date: app.applied_date,
    created_at: app.created_at,
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

/**
 * Most-recently-filed applications first — drives the recent-activity feed.
 *
 * Ordered by the SAME field the feed displays (`filedAt`: the mail's received
 * date, falling back to the row's creation time). Sorting by `created_at` while
 * rendering `applied_date` would let the feed show "Aug 12" above "Aug 10".
 */
export function recentApplications(applications: Application[], limit = 6): Application[] {
  return [...applications]
    .sort((a, b) => Date.parse(filedAt(b)) - Date.parse(filedAt(a)))
    .slice(0, limit);
}
