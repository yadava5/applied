/**
 * The marketing board's fixture: a board that has visibly MOVED.
 *
 * The /demo seed is deliberately shaped like a real early search — applied
 * heavy, offered empty — because /demo is coverage infrastructure and has to
 * exercise the ugly cases. Mounted under a headline that promises "Applied
 * reads the verdict and moves the board for you", that same shape DISPROVES
 * the promise: ten rows in `applied` and two zeroed stages read as a board
 * nothing has moved. So the landing candidates get this projection instead:
 * the good day, still a shape the product actually produces — every stage
 * occupied, one offer, an assessment with a live deadline, a row filed today,
 * and two closed rows (one of them Larkspur, the rejection variant C's
 * travelling email classifies live).
 *
 * Same construction rules as `lib/demo/demoData.ts`, same date arithmetic
 * (`daysBefore`, `dueDayISO`), same API `Application` shape — resolved during
 * render against the caller's clock read, never at module load, for the
 * hydration reason documented there. Only the distribution differs, and the
 * embed's caption states the provenance either way.
 */
import { todayISO } from "@/lib/dashboard/age";
import { dueDayISO } from "@/lib/dashboard/deadline";
import type { Application } from "@/lib/dashboard/summary";
import { daysBefore } from "@/lib/demo/demoData";
import { VERDICT_EMAIL } from "./verdictEmailData";

/** The one signal line Larkspur's rejection files under — stated once, so the
 *  resting seed and the window act's live move can never phrase it apart. */
export const VERDICT_SIGNAL = "Moving forward with other candidates";

interface ShowcaseSeed {
  company: string;
  position: string;
  status: Application["status"];
  /** Whole days before "today" this application was filed. */
  filedDaysAgo: number;
  /** The most recent classified signal — reads as the card's note. */
  lastSignal: string;
  /** Whole days after "today" the row's assessment is due. */
  dueInDays?: number;
}

/**
 * Render order inside a stage group is seed order, so within each stage the
 * freshest signal leads. Stage groups themselves render in flow order
 * (applied → assessment → interviewing → offered → closed), which is why the
 * applied run is kept SHORT: three rows, so the fold of a ~700px stage
 * reaches the interviews and the offer instead of stacking identical
 * dropdowns — the exact defect this fixture replaces.
 *
 * The FILED DAYS are clustered on purpose. The first cut dribbled the ten
 * rows across ten distinct days — one filing per day, so the momentum
 * strip's `count / peak` saturated at 100% for every non-empty bin and drew
 * a full-height picket fence (the owner's verdict was "terrible"; the
 * diagnosis was the input, not the chart). The measured production account
 * files in BURSTS — 65 rows on ~7 distinct days of 28 — which is what gives
 * `peak` something to divide by and lets empty days read as baseline. This
 * projection keeps that shape at fixture scale: a heavy evening (3), a pair
 * of two-filing days, singles, and empty runs between — peak 3, so the
 * strip carries three real heights without inflating the approved row list.
 */
const SEEDS: ShowcaseSeed[] = [
  // applied — recent, still warm; the top row landed today.
  { company: "Waypoint Robotics", position: "Software Engineer, Controls", status: "applied", filedDaysAgo: 0, lastSignal: "Thanks for applying" },
  { company: "Copperline", position: "Backend Engineer, Payments", status: "applied", filedDaysAgo: 2, lastSignal: "We received your application" },
  { company: "Juniper Cloud", position: "Infrastructure Engineer", status: "applied", filedDaysAgo: 2, lastSignal: "Application under review" },
  // assessment — one, with the deadline its mail stated (fills the pulse's
  // deadlines cell honestly). Filed in the same two-days-ago burst.
  { company: "Kestrel Dynamics", position: "Software Engineer, Simulation", status: "assessment", filedDaysAgo: 2, dueInDays: 2, lastSignal: "Next step: online assessment (90 min)" },
  // interviewing — the middle of a healthy funnel; one heavy evening's burst.
  { company: "Harbor Analytics", position: "Backend Engineer", status: "interviewing", filedDaysAgo: 11, lastSignal: "Recruiter screen scheduled" },
  { company: "Northstar Systems", position: "ML Engineer", status: "interviewing", filedDaysAgo: 11, lastSignal: "Interview availability — technical round" },
  { company: "Cedar Labs", position: "Software Engineer, Platform", status: "interviewing", filedDaysAgo: 12, lastSignal: "Onsite loop confirmed for Thursday" },
  // offered — the row the headline promises.
  { company: "Meridian Grid", position: "Software Engineer, Energy", status: "offered", filedDaysAgo: 12, lastSignal: "Congratulations — offer details inside" },
  // closed — verdicts are verdicts; a board with no rejections is a brochure.
  // Larkspur is the row the merged landing's window act moves live and the
  // descent's travelling email decides — same company, same role, same
  // outcome (see showcasePendingVerdict below).
  { company: VERDICT_EMAIL.company, position: VERDICT_EMAIL.role, status: "rejected", filedDaysAgo: 19, lastSignal: VERDICT_SIGNAL },
  { company: "Atlas Freight", position: "Software Engineer II", status: "rejected", filedDaysAgo: 26, lastSignal: "Moving forward with other candidates" },
];

/** The showcase rows, projected onto the API shape (`asApplications.ts` idiom). */
export function showcaseApplications(today: string = todayISO()): Application[] {
  return SEEDS.map((seed, index) => ({
    id: index + 1,
    user_id: "demo",
    company: seed.company,
    position: seed.position,
    status: seed.status,
    notes: seed.lastSignal,
    created_at: `${daysBefore(today, seed.filedDaysAgo)}T12:00:00.000Z`,
    source: "gmail",
    due_at: seed.dueInDays !== undefined ? (dueDayISO(daysBefore(today, -seed.dueInDays)) ?? null) : null,
    due_source: seed.dueInDays !== undefined ? "mail" : null,
  }));
}

/**
 * The same board ONE VERDICT EARLIER — the merged landing's opening state.
 *
 * Larkspur starts where the classifier found it: still in `applied`, nineteen
 * days quiet (the age tag and the pulse's amber "1 of N quiet" foreshadow the
 * outcome), its note the receipt every application starts with. The window
 * act then performs the move the resting seed merely states — `rejected`,
 * {@link VERDICT_SIGNAL} — so the board is seen DOING the thing the headline
 * promises rather than having already done it. Every other row is identical
 * to {@link showcaseApplications}, which the other candidates still mount.
 */
export function showcasePendingVerdict(today: string = todayISO()): Application[] {
  return showcaseApplications(today).map((app) =>
    app.company === VERDICT_EMAIL.company
      ? { ...app, status: "applied" as const, notes: "We received your application" }
      : app,
  );
}
