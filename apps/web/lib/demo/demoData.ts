/**
 * Fixture data for the auth-free /demo experience. Entirely synthetic —
 * companies and roles reuse the vocabulary of the backend's mock
 * training generator. No inbox is read; nothing here touches Supabase
 * or the API.
 *
 * Dates are RELATIVE, and that is load-bearing. They used to be absolute
 * (`2026-07-15`), so the fixtures aged a day per day against a clock that kept
 * moving: by August every applied card in the dashboard's sample preview — the
 * one screen whose whole job is to show a healthy board — carried an amber
 * "· quiet 27d" tag, and the momentum strip was two months from eight flat
 * bars. Each seed carries `filedDaysAgo` instead, resolved against a single
 * "now" per render, so the demo's SHAPE is fixed while its dates stay current.
 *
 * The offsets encode a deliberate ageing spread across the 14 open rows — 6
 * under a week, 5 waiting, 3 past the quiet line (`QUIET_AFTER_DAYS`) — so all
 * three pulse buckets draw, the quiet signal is demonstrated without the board
 * looking abandoned, and every row lands inside the 8-week momentum window.
 * Deadlines (`dueInDays`) are relative for the same reason the filed dates
 * are: an absolute due date is "comfortably ahead" for exactly as long as the
 * calendar allows and then silently becomes a fourth overdue row, changing
 * every count the e2e asserts. Changing an offset changes what the e2e sees:
 * the counts, the "quiet Nd" tag and the deadline phrases asserted in
 * tests/e2e/demo.spec.ts are the contract.
 */
import { todayISO } from "@/lib/dashboard/age";
import { dueDayISO } from "@/lib/dashboard/deadline";

export type DemoStatus = "applied" | "interviewing" | "offered" | "rejected";

export interface DemoApplication {
  id: string;
  company: string;
  position: string;
  status: DemoStatus;
  /** Calendar day filed — resolved from the seed against the render's "today". */
  appliedAt: string;
  lastSignal: string; // the most recent classified email, one line
  /** ISO instant the row is due by (end of its calendar day, UTC — the same
   *  shape the deadline control writes), when its mail stated one. */
  dueAt?: string;
}

/** A fixture row before its date is resolved: an age, not a calendar day. */
type DemoSeed = Omit<DemoApplication, "appliedAt" | "dueAt"> & {
  /** Whole days before "today" this application was filed. */
  filedDaysAgo: number;
  /** Whole days after "today" this row's assessment is due (negative =
   *  already missed). Only rows whose mail states a deadline carry one. */
  dueInDays?: number;
};

export interface DemoReviewItem {
  subject: string;
  from: string;
  category: string;
  confidence: number;
  method: "rules" | "embeddings" | "setfit";
  needsReview: boolean;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * `today` minus n whole days, as a plain calendar-day string. UTC arithmetic —
 * exactly what `daysBetween` inverts — so a row seeded at 16 reads back as "16
 * days old" on the server and in the browser alike, in any timezone.
 */
function daysBefore(today: string, days: number): string {
  return new Date(Date.parse(`${today}T00:00:00Z`) - days * DAY_MS).toISOString().slice(0, 10);
}

function resolve(seed: DemoSeed, today: string): DemoApplication {
  const { filedDaysAgo, dueInDays, ...row } = seed;
  return {
    ...row,
    appliedAt: daysBefore(today, filedDaysAgo),
    // `dueDayISO` is what the deadline control PUTs, so fixture deadlines and
    // user-set ones are byte-identical in shape. `?? undefined` can't fire —
    // `daysBefore` always yields a valid day — it just keeps the type honest.
    ...(dueInDays !== undefined
      ? { dueAt: dueDayISO(daysBefore(today, -dueInDays)) ?? undefined }
      : {}),
  };
}

/**
 * Shaped like a REAL early-search board, not a brochure: the applied column is
 * heavy (10 of 17), offered is empty, and one employer holds several
 * applications in different stages — the owner's own board has four Amazon
 * requisitions, so the fixtures must exercise the same truths the live board
 * does: company+role as the card identity, the "N more at …" affordance,
 * cross-column same-company cards, an applied column past the collapse
 * threshold, and an honestly empty column.
 *
 * Order matters as much as the dates: the applied column renders in this
 * order, and the collapse expander test depends on Copperline and Waypoint
 * being the two that wait behind "show all 10".
 */
const APPLICATION_SEEDS: DemoSeed[] = [
  // Northstar Systems ×3 — one advanced, two still applied. Three cards, three
  // distinct roles, two different columns: an application is not a company.
  { id: "a1", company: "Northstar Systems", position: "ML Engineer", status: "interviewing", filedDaysAgo: 18, lastSignal: "Interview availability — technical round" },
  { id: "a2", company: "Northstar Systems", position: "ML Engineer, Platform", status: "applied", filedDaysAgo: 16, lastSignal: "Your application was received" },
  { id: "a3", company: "Northstar Systems", position: "Research Engineer, Applied ML", status: "applied", filedDaysAgo: 15, lastSignal: "Thanks for applying" },
  // Cedar Labs ×2 — one open, one already closed.
  { id: "a4", company: "Cedar Labs", position: "Software Engineer, Platform", status: "applied", filedDaysAgo: 12, lastSignal: "Your application was received" },
  { id: "a5", company: "Cedar Labs", position: "Site Reliability Engineer", status: "rejected", filedDaysAgo: 34, lastSignal: "Moving forward with other candidates" },
  // Single-application employers — the common case, which stays untaxed.
  { id: "a6", company: "Harbor Analytics", position: "Backend Engineer", status: "applied", filedDaysAgo: 11, lastSignal: "Application under review" },
  { id: "a7", company: "Summit Platform", position: "Full-Stack Engineer", status: "applied", filedDaysAgo: 9, lastSignal: "Application under review" },
  { id: "a8", company: "Quarry Data", position: "Data Engineer", status: "applied", filedDaysAgo: 8, lastSignal: "Thanks for applying" },
  { id: "a9", company: "Beacon Health", position: "ML Engineer, Risk", status: "applied", filedDaysAgo: 6, lastSignal: "We received your application" },
  { id: "a10", company: "Fernworks", position: "Systems Engineer", status: "rejected", filedDaysAgo: 45, lastSignal: "Update on your application" },
  { id: "a11", company: "Atlas Freight", position: "Software Engineer II", status: "rejected", filedDaysAgo: 38, lastSignal: "Moving forward with other candidates" },
  { id: "a12", company: "Juniper Cloud", position: "Infrastructure Engineer", status: "applied", filedDaysAgo: 5, lastSignal: "We received your application" },
  { id: "a13", company: "Copperline", position: "Backend Engineer, Payments", status: "applied", filedDaysAgo: 3, lastSignal: "We received your application" },
  { id: "a14", company: "Waypoint Robotics", position: "Software Engineer, Controls", status: "applied", filedDaysAgo: 2, lastSignal: "Thanks for applying" },
  // Assessments with deadlines ×3 — the landing's own opening problem ("its
  // 48-hour deadline passes unseen") demonstrated in all three states: one
  // comfortably ahead, one inside the DUE_SOON_DAYS window, one already
  // missed. Status is `interviewing` (an assessment mail advances the row;
  // `assessment` is a classifier category, not an API status — see
  // lib/dashboard/status.ts), and every deadline here is mail-extracted
  // (`due_source: "mail"` via the adapter): this account is auto-filed, and
  // the e2e sets/clears the one "user" deadline through the sheet instead.
  // The offsets are the contract demo.spec.ts asserts (due in 9d / due in 2d /
  // overdue 2d) — change them and the spec's phrases change with them.
  { id: "a15", company: "Meridian Grid", position: "Software Engineer, Energy", status: "interviewing", filedDaysAgo: 1, dueInDays: 9, lastSignal: "Online assessment — complete within two weeks" },
  { id: "a16", company: "Kestrel Dynamics", position: "Software Engineer, Simulation", status: "interviewing", filedDaysAgo: 3, dueInDays: 2, lastSignal: "Next step: online assessment (90 min)" },
  { id: "a17", company: "Tidewater Labs", position: "Platform Engineer", status: "interviewing", filedDaysAgo: 7, dueInDays: -2, lastSignal: "Take-home exercise — 72 hour window" },
];

/**
 * Fixture mail the demo account has NOT synced yet. Pressing `Sync` on /demo
 * files these into the board through the real SyncBar state machine, so the
 * demo demonstrates the product's actual loop (sync → new cards appear) on
 * data that is still entirely synthetic. Kept out of the board seeds so the
 * initial counts stay the honest 14, and dated as the newest mail there is —
 * they are what "new since your last sync" means.
 */
const UNSYNCED_SEEDS: DemoSeed[] = [
  { id: "u1", company: "Twitch", position: "Software Engineer, Creator Tools", status: "applied", filedDaysAgo: 1, lastSignal: "Your application was received" },
  { id: "u2", company: "DoorDash", position: "Backend Engineer, Logistics", status: "applied", filedDaysAgo: 0, lastSignal: "Thanks for applying" },
];

/** How many rows the demo board starts with — ids continue after these. */
export const DEMO_APPLICATION_COUNT = APPLICATION_SEEDS.length;

/**
 * The demo board's applications, dated against one `today`.
 *
 * Callers pass the SAME clock read they render with (`useLocalToday()`), and
 * re-date the store if that read changes — the seeds are offsets, so fixtures
 * dated against one day and bucketed against another shift every deadline
 * phrase on /demo by one. Re-dating means MAPPING the rows that are there onto
 * the new dates, never installing a fresh store over them: see `redate` in
 * DemoDashboard, which is where the reasoning (and the session a rebuild used
 * to throw away) lives. Resolved during render rather than at module load: a
 * module-level resolution
 * freezes at process start, which on a long-lived dev server or a warm lambda
 * means the server renders yesterday's dates into HTML the browser then
 * hydrates with today's — a mismatch that repairs itself loudly, in the
 * console.
 */
export function demoApplications(today: string = todayISO()): DemoApplication[] {
  return APPLICATION_SEEDS.map((seed) => resolve(seed, today));
}

/** The not-yet-synced fixture mail, dated against the same `today`. */
export function demoUnsynced(today: string = todayISO()): DemoApplication[] {
  return UNSYNCED_SEEDS.map((seed) => resolve(seed, today));
}

export const DEMO_REVIEW_QUEUE: DemoReviewItem[] = [
  { subject: "Interview availability — technical round", from: "recruiting@northstar.dev", category: "interview", confidence: 0.991, method: "setfit", needsReview: false },
  { subject: "Next step: online assessment (90 min)", from: "talent@harboranalytics.com", category: "assessment", confidence: 0.968, method: "rules", needsReview: false },
  { subject: "Congratulations — offer details inside", from: "people@beaconhealth.io", category: "offer", confidence: 0.994, method: "rules", needsReview: false },
  { subject: "Following up on our conversation", from: "sam@cedarlabs.com", category: "follow_up", confidence: 0.884, method: "embeddings", needsReview: false },
  { subject: "Quick question about your background", from: "maya@summit.dev", category: "needs_review", confidence: 0.61, method: "setfit", needsReview: true },
  { subject: "Your weekly job digest", from: "alerts@jobboard.com", category: "other", confidence: 0.973, method: "rules", needsReview: false },
];
