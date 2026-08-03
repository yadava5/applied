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

export const DEMO_APPLICATIONS: DemoApplication[] = [
  { id: "a1", company: "Northstar Systems", position: "ML Engineer", status: "interviewing", appliedAt: "2026-06-28", lastSignal: "Interview availability — technical round" },
  { id: "a2", company: "Harbor Analytics", position: "Backend Engineer", status: "interviewing", appliedAt: "2026-07-02", lastSignal: "Next step: online assessment" },
  { id: "a3", company: "Cedar Labs", position: "Software Engineer, Platform", status: "applied", appliedAt: "2026-07-08", lastSignal: "Your application was received" },
  { id: "a4", company: "Summit Platform", position: "Full-Stack Engineer", status: "applied", appliedAt: "2026-07-10", lastSignal: "Application under review" },
  { id: "a5", company: "Quarry Data", position: "Data Engineer", status: "applied", appliedAt: "2026-07-11", lastSignal: "Thanks for applying" },
  { id: "a6", company: "Beacon Health", position: "ML Engineer, Risk", status: "offered", appliedAt: "2026-05-30", lastSignal: "Congratulations — offer details inside" },
  { id: "a7", company: "Fernworks", position: "Systems Engineer", status: "rejected", appliedAt: "2026-06-05", lastSignal: "Update on your application" },
  { id: "a8", company: "Atlas Freight", position: "Software Engineer II", status: "rejected", appliedAt: "2026-06-12", lastSignal: "Moving forward with other candidates" },
  { id: "a9", company: "Juniper Cloud", position: "Infrastructure Engineer", status: "interviewing", appliedAt: "2026-06-20", lastSignal: "Schedule your onsite loop" },
  { id: "a10", company: "Copperline", position: "Backend Engineer, Payments", status: "applied", appliedAt: "2026-07-14", lastSignal: "We received your application" },
];

export const DEMO_REVIEW_QUEUE: DemoReviewItem[] = [
  { subject: "Interview availability — technical round", from: "recruiting@northstar.dev", category: "interview", confidence: 0.991, method: "setfit", needsReview: false },
  { subject: "Next step: online assessment (90 min)", from: "talent@harboranalytics.com", category: "assessment", confidence: 0.968, method: "rules", needsReview: false },
  { subject: "Congratulations — offer details inside", from: "people@beaconhealth.io", category: "offer", confidence: 0.994, method: "rules", needsReview: false },
  { subject: "Following up on our conversation", from: "sam@cedarlabs.com", category: "follow_up", confidence: 0.884, method: "embeddings", needsReview: false },
  { subject: "Quick question about your background", from: "maya@summit.dev", category: "needs_review", confidence: 0.61, method: "setfit", needsReview: true },
  { subject: "Your weekly job digest", from: "alerts@jobboard.com", category: "other", confidence: 0.973, method: "rules", needsReview: false },
];
