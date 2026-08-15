/**
 * The one synthetic email the landing candidates share — plain data, no
 * directive, so both sides of the client boundary can read it: `VerdictEmail`
 * (client — classifies it live, twice) and variant C's hero row (server —
 * derives its stage chip from the same live call).
 *
 * The text was tuned against the real `rules.json` until the two calls split
 * the way the production mailbox measurably did (#320): the first ~200
 * characters — Gmail's snippet budget — classify as `applied` (a polite
 * confirmation), the whole body as `rejection`. Nothing downstream hardcodes
 * either verdict; if the rules change, every surface reading this changes
 * with them.
 */
export const VERDICT_EMAIL = {
  company: "Larkspur Systems",
  role: "Staff Software Engineer",
  senderName: "Larkspur Systems Recruiting",
  senderEmail: "no-reply@larkspur.dev",
  subject: "Your application to Larkspur Systems",
  body: "Hi Ayush, thank you for the time and care you put into your application for the Staff Software Engineer role at Larkspur Systems, and for walking us through your work. We know how much effort a search takes, and we genuinely appreciate your interest in the team. After careful review, we have decided to move forward with other candidates whose experience more closely matches the role. We'd be glad to see you apply again as new positions open.",
} as const;

/** Gmail's snippet budget — the honest reason the preview verdict is wrong. */
export const PREVIEW_CHARS = 200;
