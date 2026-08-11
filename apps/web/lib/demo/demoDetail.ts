/**
 * Fixture "mail behind the card" for the demo's detail sheet.
 *
 * Builds the exact `GET /api/applications/{id}` response shape
 * (`{ application, messages }`, snake_case — see `lib/dashboard/detail.ts`)
 * from a fixture row, so `ApplicationDetail` parses and renders it through the
 * same `readApplicationDetail` path a real response takes. Nothing here is
 * dressed up as real: senders live under the reserved `.example` TLD and no
 * Gmail deep links are invented — the sheet simply renders no link, exactly as
 * it does for a hand-filed row.
 */
import { longDate } from "@/lib/dashboard/dates";
import type { Application } from "@/lib/dashboard/summary";

/** `Beacon Health` → `beaconhealth`. */
function slug(company: string): string {
  return company.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/**
 * The filed date + n days — never in the future, and never before the mail it
 * follows. The clamp is load-bearing since the fixture dates went relative
 * (`demoData.ts`): the newest board rows are now days old, not weeks, so a
 * visitor dragging one to interviewing would otherwise open its detail sheet
 * onto a follow-up email "received" next week.
 */
function daysAfter(isoDate: string, days: number): string {
  const filed = Date.parse(`${isoDate.slice(0, 10)}T12:00:00Z`);
  const shifted = filed + days * 24 * 60 * 60 * 1000;
  return new Date(Math.max(filed, Math.min(shifted, Date.now()))).toISOString();
}

const LATEST_CATEGORY: Record<string, { category: string; confidence: number }> = {
  applied: { category: "applied", confidence: 0.97 },
  interviewing: { category: "interview", confidence: 0.99 },
  offered: { category: "offer", confidence: 0.99 },
  rejected: { category: "rejection", confidence: 0.98 },
};

/** The detail body for one fixture application. */
export function demoDetailBody(app: Application): Record<string, unknown> {
  const sender_email = `talent@${slug(app.company)}.example`;
  const filed = app.created_at;
  // A mail-extracted deadline exists because a message STATED it, so the row's
  // latest signal is that assessment mail — and its snippet spells the date
  // out, demonstrating the extraction rule: the claim is in the mail, read it.
  const assessment = app.due_at != null && app.due_source === "mail";
  const latest = assessment
    ? { category: "assessment", confidence: 0.97 }
    : (LATEST_CATEGORY[app.status] ?? LATEST_CATEGORY.applied);

  const messages: Record<string, unknown>[] = [];
  // Advanced or closed rows carry their latest signal ABOVE the original
  // confirmation (the backend orders received_at descending).
  if (app.status !== "applied") {
    messages.push({
      message_id: `demo-${app.id}-2`,
      subject: app.notes ?? "Update on your application",
      sender_name: `${app.company} Talent`,
      sender_email,
      received_at: daysAfter(filed, 9),
      snippet: assessment
        ? `Complete your ${app.position} assessment by ${longDate(app.due_at)}.`
        : `Regarding your application for ${app.position}.`,
      category: latest.category,
      confidence: latest.confidence,
      gmail_link: null,
    });
  }
  messages.push({
    message_id: `demo-${app.id}-1`,
    subject:
      app.status === "applied"
        ? (app.notes ?? "Your application was received")
        : "Your application was received",
    sender_name: `${app.company} Talent`,
    sender_email,
    received_at: filed,
    snippet: `Thanks for applying to the ${app.position} role.`,
    category: "applied",
    confidence: 0.99,
    gmail_link: null,
  });

  return { application: { ...app }, messages };
}
