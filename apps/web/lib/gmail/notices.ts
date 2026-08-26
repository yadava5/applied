/**
 * What the app says after a Gmail connect round trip, keyed by the `?gmail=`
 * flag the backend callback returns with.
 *
 * ONE DEFINITION, TWO PAGES. These used to live inside the Settings route,
 * which was correct while Settings was the only place a Gmail callback could
 * land. Since #510 a consent chained off a first sign-in returns to
 * `/dashboard` instead, and a second copy of this map would be two copies of
 * the sentence a user reads at the most consequential moment in the product —
 * free to drift, with nothing to notice when they did. This repo has the scar
 * from exactly that shape (a demo twin that stopped matching the page it stood
 * in for), so the map moved rather than being duplicated.
 *
 * The flags themselves are the backend's coarse, non-sensitive outcome tokens.
 * No token, address or mailbox content ever rides in that parameter.
 */
export type NoticeTone = "ok" | "warn" | "error";

export interface GmailNotice {
  tone: NoticeTone;
  text: string;
}

export const GMAIL_NOTICES: Record<string, GmailNotice> = {
  connected: {
    tone: "ok",
    text: "Gmail connected. Applied can now read and classify your job-search mail.",
  },
  disconnected: {
    tone: "ok",
    text: "Gmail disconnected and access revoked at Google.",
  },
  error: {
    tone: "error",
    text: "Something went wrong reaching the mail backend. Please try again.",
  },
  auth: {
    tone: "error",
    text: "Your session couldn't be verified for the mail backend. Sign in again and retry.",
  },
  unavailable: {
    tone: "warn",
    text: "Gmail connection isn't enabled on this deployment yet — see the note below.",
  },
  // The beta cap (backend 409). This is the only notice that asks the reader to
  // do something outside the product, and it has to: Google caps how many
  // people this app may ever connect and that number cannot be raised on
  // request, so "try again later" would be false. The address is the whole
  // point of the message — a refusal with no way to appeal it is a dead end,
  // and importing an export needs no Google account at all.
  capacity: {
    tone: "warn",
    text: "The Gmail beta is full, so this account can't connect a mailbox yet. Email aesh.03.23@gmail.com to ask for a place. Importing a mailbox export still works.",
  },
};

export const NOTICE_TONE_CLASS: Record<NoticeTone, string> = {
  ok: "border-live/40 text-strong",
  warn: "border-line-strong text-muted",
  error: "border-reject/50 text-strong",
};

/**
 * The notice for a flag, or null when there is nothing to say.
 *
 * An UNRECOGNISED flag answers null rather than a generic sentence. The
 * parameter is on a URL and anyone can type one; inventing an outcome for a
 * value the backend never emits would put words in the product's mouth about
 * something that did not happen.
 */
export function gmailNoticeFor(
  flag: string | undefined | null,
): GmailNotice | null {
  if (typeof flag !== "string") return null;
  return GMAIL_NOTICES[flag] ?? null;
}
