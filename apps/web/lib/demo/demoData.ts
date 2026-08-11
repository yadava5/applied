/**
 * Fixture data for the auth-free /demo experience. Entirely synthetic —
 * companies and roles reuse the vocabulary of the backend's mock
 * training generator. No inbox is read; nothing here touches Supabase
 * or the API.
 */

export type DemoStatus = "applied" | "interviewing" | "offered" | "rejected";

export interface DemoApplication {
  id: string;
  company: string;
  position: string;
  status: DemoStatus;
  appliedAt: string;
  lastSignal: string; // the most recent classified email, one line
}

export interface DemoReviewItem {
  subject: string;
  from: string;
  category: string;
  confidence: number;
  method: "rules" | "embeddings" | "setfit";
  needsReview: boolean;
}

/**
 * Shaped like a REAL early-search board, not a brochure: the applied column is
 * heavy (10 of 14), offered is empty, and one employer holds several
 * applications in different stages — the owner's own board has four Amazon
 * requisitions, so the fixtures must exercise the same truths the live board
 * does: company+role as the card identity, the "N more at …" affordance,
 * cross-column same-company cards, an applied column past the collapse
 * threshold, and an honestly empty column.
 */
export const DEMO_APPLICATIONS: DemoApplication[] = [
  // Northstar Systems ×3 — one advanced, two still applied. Three cards, three
  // distinct roles, two different columns: an application is not a company.
  { id: "a1", company: "Northstar Systems", position: "ML Engineer", status: "interviewing", appliedAt: "2026-06-28", lastSignal: "Interview availability — technical round" },
  { id: "a2", company: "Northstar Systems", position: "ML Engineer, Platform", status: "applied", appliedAt: "2026-07-09", lastSignal: "Your application was received" },
  { id: "a3", company: "Northstar Systems", position: "Research Engineer, Applied ML", status: "applied", appliedAt: "2026-07-09", lastSignal: "Thanks for applying" },
  // Cedar Labs ×2 — one open, one already closed.
  { id: "a4", company: "Cedar Labs", position: "Software Engineer, Platform", status: "applied", appliedAt: "2026-07-08", lastSignal: "Your application was received" },
  { id: "a5", company: "Cedar Labs", position: "Site Reliability Engineer", status: "rejected", appliedAt: "2026-06-14", lastSignal: "Moving forward with other candidates" },
  // Single-application employers — the common case, which stays untaxed.
  { id: "a6", company: "Harbor Analytics", position: "Backend Engineer", status: "applied", appliedAt: "2026-07-02", lastSignal: "Application under review" },
  { id: "a7", company: "Summit Platform", position: "Full-Stack Engineer", status: "applied", appliedAt: "2026-07-10", lastSignal: "Application under review" },
  { id: "a8", company: "Quarry Data", position: "Data Engineer", status: "applied", appliedAt: "2026-07-11", lastSignal: "Thanks for applying" },
  { id: "a9", company: "Beacon Health", position: "ML Engineer, Risk", status: "applied", appliedAt: "2026-07-12", lastSignal: "We received your application" },
  { id: "a10", company: "Fernworks", position: "Systems Engineer", status: "rejected", appliedAt: "2026-06-05", lastSignal: "Update on your application" },
  { id: "a11", company: "Atlas Freight", position: "Software Engineer II", status: "rejected", appliedAt: "2026-06-12", lastSignal: "Moving forward with other candidates" },
  { id: "a12", company: "Juniper Cloud", position: "Infrastructure Engineer", status: "applied", appliedAt: "2026-07-13", lastSignal: "We received your application" },
  { id: "a13", company: "Copperline", position: "Backend Engineer, Payments", status: "applied", appliedAt: "2026-07-14", lastSignal: "We received your application" },
  { id: "a14", company: "Waypoint Robotics", position: "Software Engineer, Controls", status: "applied", appliedAt: "2026-07-15", lastSignal: "Thanks for applying" },
];

export const DEMO_REVIEW_QUEUE: DemoReviewItem[] = [
  { subject: "Interview availability — technical round", from: "recruiting@northstar.dev", category: "interview", confidence: 0.991, method: "setfit", needsReview: false },
  { subject: "Next step: online assessment (90 min)", from: "talent@harboranalytics.com", category: "assessment", confidence: 0.968, method: "rules", needsReview: false },
  { subject: "Congratulations — offer details inside", from: "people@beaconhealth.io", category: "offer", confidence: 0.994, method: "rules", needsReview: false },
  { subject: "Following up on our conversation", from: "sam@cedarlabs.com", category: "follow_up", confidence: 0.884, method: "embeddings", needsReview: false },
  { subject: "Quick question about your background", from: "maya@summit.dev", category: "needs_review", confidence: 0.61, method: "setfit", needsReview: true },
  { subject: "Your weekly job digest", from: "alerts@jobboard.com", category: "other", confidence: 0.973, method: "rules", needsReview: false },
];
