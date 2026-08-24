/**
 * Single source of truth for the beta-access notice — shared by the rich
 * `BetaCard` (settings / not-connected inbox) and the slim, dismissible
 * `BetaBanner` (site-wide pill) so the copy, the admin mailbox, and the
 * seat cap can never drift apart.
 *
 * THE TWO SURFACES NO LONGER DIVERGE, AND THE HISTORY IS WORTH KEEPING.
 * `SAMPLE_INBOX_HREF` / `BETA_SAMPLE_LABEL` used to be rendered by the BANNER
 * and not by the CARD (#495), on the argument that the card renders inside the
 * signed-in product while the banner — `position: fixed` root-layout chrome —
 * could only ever be seen by a stranger, because its `HIDE_ON` list excluded
 * `/dashboard`, `/inbox`, `/settings`, `/import`, `/demo` and every landing
 * route. That paragraph then set its own expiry date: "if the banner's
 * `HIDE_ON` ever stops covering a signed-in route, the link has to leave the
 * banner too — the reachability is the whole argument, not the component."
 *
 * THE CONDITION WAS ALREADY MET WHEN IT WAS WRITTEN. `HIDE_ON` is a list of
 * ROUTES, and a route is not a session. `/privacy` is on neither list, and it
 * is signed-in-reachable by design — the protected Inbox page links to it, so
 * does the Gmail card on `/settings`, and `app/(app)/layout.tsx` mounts the
 * full app shell around it for a user who is signed in. A mistyped URL does
 * the same through `not-found.tsx`, which no `HIDE_ON` entry can cover. So a
 * signed-in user could reach "Try the sample inbox" from inside the product,
 * which is exactly what the rule forbids.
 *
 * The banner now carries `IMPORT_HREF` / `BETA_IMPORT_LABEL` — the same pair
 * the card carries — and `SAMPLE_INBOX_HREF` / `BETA_SAMPLE_LABEL` are GONE
 * rather than kept for a future caller. A demo link that lives in the beta
 * module is a demo link one import away from every surface the beta module
 * already reaches, and this is the second time it has travelled. The landing
 * links the demo in four places of its own (`components/marketing/`), which
 * is where a stranger meets it and a user does not; nothing needs a shared
 * constant to do that.
 *
 * Every number here is honest: the 100-seat cap is Google's real OAuth
 * test-user limit for a restricted scope (`gmail.readonly`), which is why
 * direct Gmail linking is invite-only until the app clears verification.
 */

/** Where a beta-access request email is composed to (opens the user's mail client only). */
export const BETA_ADMIN_EMAIL = "aesh.03.23@gmail.com";

/** Google's OAuth test-user cap for a restricted scope — the real limit, not a marketing number. */
export const BETA_SEATS = 100;

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
export const BETA_IMPORT_LABEL = "Import your own mail";
