/**
 * Single source of truth for the beta-access notice — shared by the rich
 * `BetaCard` (settings / not-connected inbox) and the slim, dismissible
 * `BetaBanner` (site-wide pill) so the copy, the admin mailbox, and the
 * seat cap can never drift apart.
 *
 * THE TWO SURFACES DELIBERATELY DIVERGE ON ONE LINK, AND THAT IS NOT DRIFT.
 * `SAMPLE_INBOX_HREF` / `BETA_SAMPLE_LABEL` are rendered by the BANNER and NOT
 * by the CARD (#495). The rule is "nothing within the app is the demo": the
 * card renders inside the signed-in product — `app/(app)/(protected)/inbox`
 * and `GmailConnectionCard` on `/settings` — where a link to invented mail is
 * the demo advertising itself to someone already using the real thing. The
 * banner is `position: fixed` root-layout chrome whose `HIDE_ON` list already
 * excludes `/dashboard`, `/inbox`, `/settings`, `/import`, `/demo` and every
 * landing route, so the only places it can render are the signed-out edges
 * (`/login`, `/signup`, `/privacy`, `/forgot-password`, `/reset-password`) —
 * a stranger, not a user, and exactly the audience the demo is FOR.
 *
 * So: do not "fix" this by deleting the constants to match the card, and do
 * not re-add the link to the card to match the banner. If the banner's
 * `HIDE_ON` ever stops covering a signed-in route, the link has to leave the
 * banner too — the reachability is the whole argument, not the component.
 *
 * Every number here is honest: the 100-seat cap is Google's real OAuth
 * test-user limit for a restricted scope (`gmail.readonly`), which is why
 * direct Gmail linking is invite-only until the app clears verification.
 */

/** Where a beta-access request email is composed to (opens the user's mail client only). */
export const BETA_ADMIN_EMAIL = "aesh.03.23@gmail.com";

/** Google's OAuth test-user cap for a restricted scope — the real limit, not a marketing number. */
export const BETA_SEATS = 100;

/** The public, zero-connection classification demo. */
export const SAMPLE_INBOX_HREF = "/demo/inbox";

/** The public, no-OAuth "classify your own mail on-device" path. */
export const IMPORT_HREF = "/import";

const BETA_MAILTO_SUBJECT = "Applied beta access request";

/**
 * A short, honest prefill. It only *composes* a message in the visitor's own
 * mail client — nothing is sent on their behalf. We ask for the Google
 * account up front because beta testers must be added by email address on the
 * OAuth consent screen.
 */
const BETA_MAILTO_BODY = [
  "Hi Ayush,",
  "",
  "I'd like to be added to the Applied Gmail beta (the 100 test-user group).",
  "The Google account I'd connect read-only is:",
  "",
  "A little about how I'd use it:",
  "",
  "Thanks!",
].join("\n");

export const BETA_MAILTO =
  `mailto:${BETA_ADMIN_EMAIL}` +
  `?subject=${encodeURIComponent(BETA_MAILTO_SUBJECT)}` +
  `&body=${encodeURIComponent(BETA_MAILTO_BODY)}`;

/** Shared button/link labels so the card and the banner popover read identically. */
export const BETA_CTA_LABEL = "Email admin for beta access";
export const BETA_SAMPLE_LABEL = "Try the sample inbox";
export const BETA_IMPORT_LABEL = "Import your own mail";
