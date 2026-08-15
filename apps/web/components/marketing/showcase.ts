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
 */
const SEEDS: ShowcaseSeed[] = [
  // applied — recent, still warm; the top row landed today.
  { company: "Waypoint Robotics", position: "Software Engineer, Controls", status: "applied", filedDaysAgo: 0, lastSignal: "Thanks for applying" },
  { company: "Copperline", position: "Backend Engineer, Payments", status: "applied", filedDaysAgo: 2, lastSignal: "We received your application" },
  { company: "Juniper Cloud", position: "Infrastructure Engineer", status: "applied", filedDaysAgo: 5, lastSignal: "Application under review" },
  // assessment — one, with the deadline its mail stated (fills the pulse's
  // deadlines cell honestly).
  { company: "Kestrel Dynamics", position: "Software Engineer, Simulation", status: "assessment", filedDaysAgo: 3, dueInDays: 2, lastSignal: "Next step: online assessment (90 min)" },
  // interviewing — the middle of a healthy funnel.
  { company: "Harbor Analytics", position: "Backend Engineer", status: "interviewing", filedDaysAgo: 9, lastSignal: "Recruiter screen scheduled" },
  { company: "Northstar Systems", position: "ML Engineer", status: "interviewing", filedDaysAgo: 12, lastSignal: "Interview availability — technical round" },
  { company: "Cedar Labs", position: "Software Engineer, Platform", status: "interviewing", filedDaysAgo: 16, lastSignal: "Onsite loop confirmed for Thursday" },
  // offered — the row the headline promises.
  { company: "Meridian Grid", position: "Software Engineer, Energy", status: "offered", filedDaysAgo: 24, lastSignal: "Congratulations — offer details inside" },
  // closed — verdicts are verdicts; a board with no rejections is a brochure.
  // Larkspur is the row variant C's hero shows and its travelling email
  // decides — same company, same role, same outcome.
  { company: VERDICT_EMAIL.company, position: VERDICT_EMAIL.role, status: "rejected", filedDaysAgo: 19, lastSignal: "Moving forward with other candidates" },
  { company: "Atlas Freight", position: "Software Engineer II", status: "rejected", filedDaysAgo: 31, lastSignal: "Moving forward with other candidates" },
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
