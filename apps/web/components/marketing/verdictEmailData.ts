/**
 * The two synthetic emails the landing candidates share — plain data, no
 * directive, so both sides of the client boundary can read them. Every
 * verdict shown for either is computed live by the rules layer; nothing
 * downstream hardcodes an outcome, so if `rules.json` changes, every surface
 * reading these changes with it.
 *
 * VERDICT_EMAIL — the descent's exhibit (`VerdictEmail`, `VerdictTally`,
 * variant C's hero row): the interview invitation that hides itself. The
 * text was tuned against the real `rules.json` (post-#356, which is what
 * made interview invitations detectable at all) until the two calls split
 * the way production truncation measurably bites: the first ~200 characters
 * — Gmail's snippet budget — are a routine acknowledgment and classify as
 * `applied`; the whole body classifies as `interview`, because the sentence
 * that invites you starts at character 201. The exhibit is deliberately a
 * WIN: what the preview loses here is not a filing error, it is the
 * opportunity itself — the exact loss the hero names. The subject has to
 * stay neutral for the same honest reason: both runs see it, so an
 * "Interview" subject would hand the preview the verdict too.
 *
 * OFFER_EMAIL — the window act's payoff (`ReceiptStrip`, MarketingBoard's
 * beat 1): the offer the hero headline is about. The act's moving row is a
 * win on purpose — its one dramatic moment used to move a row to `rejected`,
 * which demonstrated the product by turning the visitor down. The body
 * classifies as `offer` live.
 */
export const VERDICT_EMAIL = {
  company: "Northstar Systems",
  role: "ML Engineer",
  senderName: "Northstar Systems Talent",
  senderEmail: "talent@northstarsystems.dev",
  subject: "Your application to Northstar Systems",
  body: "Hi Ayush, thank you for applying to the ML Engineer position at Northstar Systems, and for the detail you shared about your work. We have been reviewing applications carefully over the past two weeks, and we would like to invite you for an interview with the team. The technical round runs about an hour, and we can work around your schedule — could you share your availability for next week? We look forward to speaking with you.",
} as const;

export const OFFER_EMAIL = {
  company: "Larkspur Systems",
  role: "Staff Software Engineer",
  senderName: "Larkspur Systems Recruiting",
  senderEmail: "no-reply@larkspur.dev",
  subject: "Your offer from Larkspur Systems",
  body: "Hi Ayush, thank you for your patience while the team wrapped up this week. We are delighted to extend an offer for the Staff Software Engineer role at Larkspur Systems — your offer letter is attached, with compensation and start date inside. We would love to have you on the team, and we are happy to walk through any of it with you.",
} as const;

/** Gmail's snippet budget — the honest reason the preview verdict is wrong. */
export const PREVIEW_CHARS = 200;
