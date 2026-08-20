import type { ReviewItem } from "@/components/dashboard/ReviewQueue";
import { classifyWithRules } from "@/lib/demo/rulesLayer";

/**
 * The held exhibit's one synthetic mail — Cedar Labs' vague "taking a little
 * longer", the note a human shrugs at and a classifier must not guess about.
 *
 * The DATA is fabricated (the owner's explicit allowance for fixtures);
 * every VERDICT on it is computed live by the shipped rules layer at render.
 * Nothing here hardcodes an outcome: the body was tuned against rules.json
 * (2026-08-19, in the motion lab this exhibit was chosen from) to land under
 * the auto-file gate, and if the rules ever change, the card re-verdicts
 * itself and the exhibit follows the engine.
 *
 * Pure and date-free — `cedarReviewItem` takes the caller's day — so both
 * sides of the client boundary read it identically.
 */
export const HELD_MAIL = {
  company: "Cedar Labs",
  subject: "Quick follow-up from Cedar Labs",
  sender: "team@cedarlabs.io",
  body: "Hi Ayush, a quick note from our side — the review is taking a little longer than planned this cycle. Nothing is needed from you right now, and we appreciate your patience.",
} as const;

/** Cedar's live verdict — the confidence the queue row draws against the
 *  auto-file gate is the engine's own number, derived rather than typed. */
export function heldVerdict() {
  return classifyWithRules(HELD_MAIL.subject, HELD_MAIL.body, HELD_MAIL.sender);
}

/** Cedar's held mail as a review-queue item, dated against the caller's day.
 *  `confidence` is the live rules verdict on what the queue actually sees —
 *  the same number `/applications/review` reports for a real held mail —
 *  so the row's own amber/green split stays honest. */
export function cedarReviewItem(today: string): ReviewItem {
  return {
    message_id: "landing-held-cedar",
    subject: HELD_MAIL.subject,
    sender_name: HELD_MAIL.company,
    sender_email: HELD_MAIL.sender,
    received_at: `${today}T12:00:00.000Z`,
    snippet: HELD_MAIL.body.slice(0, 140),
    confidence: heldVerdict().confidence,
    gmail_link: null,
  };
}
