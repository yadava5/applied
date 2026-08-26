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
// Relative, not `@/lib/dashboard/dates`, and that is the whole reason this
// module is unit-testable: `node --test` strips types but cannot resolve the
// `@/` alias, so ONE value-import through it made the entire stage vocabulary
// untestable — which is why `tests/unit/application-status.test.mjs` used to
// carry a hand-written copy of `STAGES` and could not have caught a stage
// losing its statuses. The type-only import above is erased before Node sees
// it, so it may keep the alias.
import { dailyCounts, todayISO, weekOverWeek } from "./age.ts";
import { filedAt } from "./dates.ts";

/**
 * A board row, as the cloud backend actually serves it. The name on the wire is
 * `CloudApplicationResponse` (`backend/jobtracker/cloud/applications.py`); the
 * old alias pointed at a hand-written `Application` schema that no endpoint has
 * ever returned, so `status` read as a free `string` and the row's
 * `dismissed_at` / `dismissed_reason` fields were invisible to the compiler.
 */
export type Application = components["schemas"]["CloudApplicationResponse"];

/** The five pipeline stages, in flow order, with their semantic accent. */
export type StageKey = "applied" | "assessment" | "interviewing" | "offered" | "rejected";

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
    // A stage of its own since 2026-08-12, and NOT folded into `interviewing`
    // any more. The reasons are in `CATEGORY_TO_STATUS`
    // (`backend/jobtracker/database/models.py`); the reason it matters HERE is
    // `stageOf`'s `?? "applied"` fallback: leaving `assessment` out of every
    // stage would not fail a build, it would quietly file every assessment row
    // under `applied` — the same bug `ghosted` had, documented four lines down.
    //
    // Colour: the sky of the viz sub-palette. The board already borrows that
    // palette for its chromatic stages (`interviewing` is the embeddings
    // purple), and the alternative — `--amber` — already means "needs your
    // attention" everywhere else in this dashboard, including the pulse's
    // "due ≤7d" rung that assessment rows will populate.
    key: "assessment",
    label: "assessment",
    statuses: ["assessment"],
    color: "var(--viz-rules)",
  },
  {
    key: "interviewing",
    label: "interviewing",
    statuses: ["interviewing", "interview"],
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
 * Whether a status counts as OPEN — applied + assessment + interviewing, the
 * same trio `summarizeCounts` calls in motion. It is a `stageOf` lookup here
 * (safe: stageOf's own fallback is `applied`, which IS open, so an unknown
 * status can never silently vanish from an open-rows derivation the way it
 * could from a stage allow-list). One definition, because the pulse's ageing
 * cell, its detail panel and the board's pulse filter all ask this question
 * and must never disagree about a row.
 */
export function isOpenStage(status: string): boolean {
  const stage = stageOf(status);
  return stage === "applied" || stage === "assessment" || stage === "interviewing";
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
  /** applied + assessment + interviewing — live, not-yet-resolved applications. */
  inMotion: number;
  /** offered + accepted. */
  offers: number;
  /** rejected + withdrawn. */
  closed: number;
  /**
   * Share of applications that advanced past "applied"
   * (assessment + interviewing + offered).
   */
  advancedPct: number;
  /** Per-stage counts, in flow order. */
  stages: { stage: StageDef; count: number }[];
}

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
    assessment: 0,
    interviewing: 0,
    offered: 0,
    rejected: 0,
  };
  let advanced = 0;

  for (const [status, n] of Object.entries(statusCounts)) {
    const stage = stageOf(status);
    counts[stage] += n;
    // `assessment` counts as ADVANCED: the employer answered and asked for
    // something, which is precisely what "past applied" means. Excluding it
    // would make the number fall on the day the stage shipped, for rows that
    // did not move — the old fold counted them under `interviewing`.
    if (stage === "assessment" || stage === "interviewing" || stage === "offered") advanced += n;
  }

  return {
    total,
    thisWeek,
    // `assessment` is IN MOTION: an unmet deadline is the most live an
    // application ever gets. It is not resolved, so it is not in `closed`, and
    // the three buckets still partition the board.
    inMotion: counts.applied + counts.assessment + counts.interviewing,
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
    assessment: 0,
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

  // THE WINDOW, on the date the user APPLIED — not the date we inserted the row.
  //
  // `created_at` is when the sync wrote the row, which is a fact about our
  // batch and not about the user's week. Measured on the owner's board the day
  // this changed: the header read "+47 this wk" for applications submitted
  // across a fortnight, because one sync had just ingested them; 47 of the 47
  // dated rows had an `applied_date` in a different calendar week from their
  // `created_at`. Not one was counted correctly. The true answer was 7.
  //
  // AND COUNTED BY THE MOMENTUM PANEL'S OWN DERIVATION, not a second one that
  // agrees with it today. `filedAt` (lib/dashboard/dates.ts) already means
  // "when the user applied, falling back to when we filed it", and
  // `dailyCounts` + `weekOverWeek` already turn that into a week — the
  // MOMENTUM caption on this very screen reads a correct "7 this wk" from
  // them while the header beside it read "+50".
  //
  // So the bug was never a missing rule. It was one renderer not using the
  // rule the other renderer already had, and writing a third rule here would
  // have been the same mistake in a new place. Two things prove it: a private
  // day-window written for this line came out EIGHT calendar days wide
  // (`[today-7, today]` inclusive) against the panel's seven, so the two would
  // have disagreed by a day's filings the first time anyone applied on a
  // boundary; and the undated-row question (count them under `created_at` or
  // not at all?) stops being a judgement call the moment both sides ask
  // `filedAt`, because then they cannot answer it differently.
  //
  // Measured on the live board: 50 by `created_at`, 7 by either reading of
  // `filedAt`. All 7 undated rows are seeded demo rows outside the window, so
  // adopting the fallback changes no number today — it removes the way the two
  // lines could drift apart tomorrow.
  const days = dailyCounts(
    applications.map((app) => filedAt(app)),
    todayISO(now),
  );
  thisWeek = weekOverWeek(days).thisWeek;

  for (const app of applications) {
    statusCounts[app.status] = (statusCounts[app.status] ?? 0) + 1;
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
