"use client";

// The bar is imported from the surface that owns it — ImportMail is a client
// module, so this file carries the directive too (a server component would
// receive a client REFERENCE for the constant; see footage.ts for the scar).
import { RULES_ACCEPT } from "@/components/import/ImportMail";
import type { ReviewItem } from "@/components/dashboard/ReviewQueue";
import { classifyWithRules } from "@/lib/demo/rulesLayer";

/**
 * The lab's recurring cast — one set of synthetic employers threaded through
 * every plate, so a viewer who watches two takes starts assembling a story:
 * Northstar's interview email is the 02 family's lit exhibit and its row is
 * the one 01 dives into; Cedar's vague "taking a little longer" is the mail
 * 08 holds AND the held arrival 03's sync delivers; Atlas Freight — the
 * showcase board's one closed row — gets the mail that closed it, waiting in
 * 08b's tray for the human stamp it actually took.
 *
 * The DATA is fabricated (the owner's explicit allowance); every VERDICT on
 * it is computed live by the shipped rules layer at render — nothing below
 * hardcodes an outcome, and the bodies were tuned against rules.json
 * (2026-08-19) so the trio lands two-over-one-under. If the rules change,
 * the cards re-verdict themselves and the exhibits follow the engine.
 */

export interface CastMail {
  subject: string;
  sender: string;
  body: string;
}

export const TRIO: readonly CastMail[] = [
  {
    subject: "Update on your application to Meridian Grid",
    sender: "recruiting@meridiangrid.dev",
    body: "Hi Ayush, thank you for taking the time to interview with us. After careful consideration, we have decided to move forward with other candidates for this role. We were impressed by your background and encourage you to apply again in the future.",
  },
  {
    subject: "Next step: online assessment for Kestrel Dynamics",
    sender: "no-reply@hire.lever.co",
    body: "Hi Ayush, as the next step in your application we would like you to complete an online coding assessment. The HackerRank test takes about 90 minutes and must be completed within 5 days. Good luck!",
  },
  {
    subject: "Quick follow-up from Cedar Labs",
    sender: "team@cedarlabs.io",
    body: "Hi Ayush, a quick note from our side — the review is taking a little longer than planned this cycle. Nothing is needed from you right now, and we appreciate your patience.",
  },
] as const;

export interface CastVerdict {
  mail: CastMail;
  /** The engine's category token — display via `categoryWord`. */
  category: string;
  /** Under the accept bar: the product's answer is the typed null — held. */
  held: boolean;
}

export function trioVerdicts(): CastVerdict[] {
  return TRIO.map((mail) => {
    const v = classifyWithRules(mail.subject, mail.body, mail.sender);
    return { mail, category: v.category, held: v.confidence < RULES_ACCEPT };
  });
}

/** Cedar's held mail as a review-queue item, dated against the caller's day.
 *  `confidence` is the live rules verdict on what the queue actually sees —
 *  a stand-in for the number `/applications/review` reports, derived rather
 *  than typed so the row's own amber/green split stays honest. */
export function cedarReviewItem(today: string): ReviewItem {
  const cedar = TRIO[2]!;
  const v = classifyWithRules(cedar.subject, cedar.body, cedar.sender);
  return {
    message_id: "lab-held-cedar",
    subject: cedar.subject,
    sender_name: "Cedar Labs",
    sender_email: cedar.sender,
    received_at: `${today}T12:00:00.000Z`,
    snippet: cedar.body.slice(0, 140),
    confidence: v.confidence,
    gmail_link: null,
  };
}

/**
 * The mail that closed Atlas Freight, still in the tray: obvious to a human,
 * genuinely ambiguous to a machine reading Gmail's snippet — the snippet
 * ends exactly where the verdict begins, which is the production-measured
 * reason every real rejection arrives through the human gate rather than
 * being auto-filed. The confidence is computed live on the snippet the row
 * shows, never typed.
 */
export function atlasReviewItem(today: string): ReviewItem {
  const subject = "Your application to Atlas Freight";
  const sender = "talent@atlasfreight.com";
  const snippet =
    "Hi Ayush, thank you for your patience while our team completed this round of reviews. We appreciate the time you invested in the conversations over the past few weeks. After careful consideration, we have decided to move";
  const v = classifyWithRules(subject, snippet, sender);
  return {
    message_id: "lab-held-atlas",
    subject,
    sender_name: "Atlas Freight Talent",
    sender_email: sender,
    received_at: `${today}T09:14:00.000Z`,
    snippet,
    confidence: v.confidence,
    gmail_link: null,
  };
}
