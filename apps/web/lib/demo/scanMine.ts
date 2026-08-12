/**
 * The fixture mine behind `/demo/scan` — synthetic mail, real verdict shapes.
 *
 * WHY THIS EXISTS. The live-scan view needs a Supabase session AND a connected
 * Gmail account, so CI can reach neither it nor any control on it. `/demo`
 * already solves that shape twice (`/demo/settings` for the settings sections,
 * `/demo` for the board), and the rule those follow is the rule here: the
 * components are the real ones, only the transport is simulated.
 *
 * WHY IT IS A FAITHFUL STAND-IN. The fixtures are the exact `InboxVerdict`
 * shape `GET /gmail/inbox` returns, and `demoClassifyOutcome` reproduces the
 * response contract of `POST /applications/review/{id}/classify` — including
 * `needs_employer: true`, the 2xx that files nothing. What it cannot stand in
 * for is the backend actually storing the message; that is covered by
 * `backend/tests/test_scan_classify.py`, which drives the real endpoint.
 *
 * The first fixture is the owner's complaint verbatim: an assessment email the
 * classifier called `other` at 0%. On a real mine that row is not merely
 * mislabelled — it is unreachable. `pipeline.collect_review_items` drops
 * anything below the 0.70 review floor, so filing never stores it, and before
 * this change nothing in the product could correct it.
 */

import type { ClassifyRequestBody } from "@/lib/dashboard/review";
import type { InboxVerdict } from "@/lib/gmail/types";

const HOUR = 60 * 60 * 1000;

/** Mail hosts that name a person, not an employer — the resolver rejects them. */
const GENERIC_HOSTS = new Set(["gmail.com", "outlook.com", "yahoo.com", "icloud.com"]);

/** Lifecycle categories: the ones that must name an employer before they file. */
const FILING_CATEGORIES = new Set([
  "applied",
  "pending_application",
  "interview",
  "assessment",
  "offer",
  "rejection",
]);

/**
 * The fixture verdicts, dated against a clock the caller passes.
 *
 * Resolved per call rather than frozen at module load: a module-level date
 * freezes at process start, which on a warm server means the page shows
 * whatever day it booted on.
 */
export function demoScanMine(now: number = Date.now()): InboxVerdict[] {
  const at = (hoursAgo: number) => new Date(now - hoursAgo * HOUR).toISOString();
  return [
    {
      // THE COMPLAINT. Plainly an assessment; the classifier said "other" and
      // was not even confident about that.
      message_id: "demo-scan-1",
      subject: "Your HackerRank assessment for Software Engineer II",
      sender_email: "no-reply@hackerrank.harboranalytics.com",
      sender_name: "Harbor Analytics",
      category: "other",
      confidence: 0,
      method: "rules",
      needs_review: false,
      received_at: at(3),
      company: "harboranalytics",
    },
    {
      message_id: "demo-scan-2",
      subject: "Thanks for applying to Northwind Systems",
      sender_email: "careers@northwind.test",
      sender_name: "Northwind Talent",
      category: "applied",
      confidence: 0.94,
      method: "rules",
      needs_review: false,
      received_at: at(26),
      company: "northwind",
    },
    {
      // Sent from a personal address, so no employer can be read from it. The
      // real backend answers `needs_employer: true` here; so does the demo.
      message_id: "demo-scan-3",
      subject: "Next steps + take-home details",
      sender_email: "priya.recruiter@gmail.com",
      sender_name: "Priya",
      category: "needs_review",
      confidence: 0.58,
      method: "setfit",
      needs_review: true,
      received_at: at(31),
      company: "",
    },
    {
      message_id: "demo-scan-4",
      subject: "Update on your application — Beacon Health",
      sender_email: "people@beaconhealth.io",
      sender_name: "Beacon Health",
      category: "rejection",
      confidence: 0.97,
      method: "rules",
      needs_review: false,
      received_at: at(52),
      company: "beaconhealth",
    },
    {
      // Undated: Gmail listed it, its `Date` header would not parse. The store
      // refuses undated mail rather than inventing a receive time, so this row
      // says why it cannot be corrected instead of offering a control that
      // would fail.
      message_id: "demo-scan-5",
      subject: "Coding challenge invitation (no date header)",
      sender_email: "assessments@cedarlabs.test",
      sender_name: "Cedar Labs",
      category: "other",
      confidence: 0.41,
      method: "embeddings",
      needs_review: true,
      received_at: null,
      company: "cedarlabs",
    },
    {
      message_id: "demo-scan-6",
      subject: "12 new roles match your search",
      sender_email: "digest@jobboard.test",
      sender_name: "JobBoard",
      category: "other",
      confidence: 0.98,
      method: "rules",
      needs_review: false,
      received_at: at(70),
      company: "jobboard",
    },
  ];
}

/** Can an employer be read out of this sender, the way the backend reads one? */
function employerFrom(senderEmail: string): string | null {
  const host = senderEmail.split("@")[1]?.toLowerCase() ?? "";
  if (!host || GENERIC_HOSTS.has(host)) return null;
  const label = host.split(".")[0] ?? "";
  return label.length >= 2 ? label : null;
}

/**
 * The classify response the demo answers with — the real endpoint's contract,
 * not a simplification of it.
 *
 * A lifecycle category with no nameable employer and no `company` in the body
 * returns `needs_employer: true` and files nothing, exactly as
 * `classify_review_item` does; naming the company then resolves it. "Not job
 * related" resolves without filing anything, which is also what the backend
 * does and is why a null `application_id` never means failure.
 */
export function demoClassifyOutcome(
  messageId: string,
  body: ClassifyRequestBody,
): Record<string, unknown> {
  const files = FILING_CATEGORIES.has(body.category);
  // Read from the REQUEST, never from a copy of the mine held here. Every
  // storable scan row sends `message` (and a row that cannot build one shows no
  // control at all), so this is the same information the real backend resolves
  // the employer from — and it keeps this module free of any state the
  // transport would have to keep in step with.
  const employer =
    employerFrom(body.message?.sender_email ?? "") ??
    (body.company?.trim() ? body.company.trim() : null);

  if (files && !employer) {
    return {
      classified_as: body.category,
      application_id: null,
      needs_employer: true,
      message_id: messageId,
      detail:
        "Could not identify the employer for this email. Re-send the same " +
        "classification with a 'company' to file it.",
    };
  }

  return {
    classified_as: body.category,
    application_id: files ? 1 : null,
    needs_employer: false,
  };
}
