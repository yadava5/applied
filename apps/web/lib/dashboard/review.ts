/**
 * The review queue's ONE reading of a classify response.
 *
 * `POST /applications/review/{message_id}/classify` returning 2xx does NOT mean
 * an application was filed. When the backend cannot name the employer it now
 * says so explicitly — `needs_employer: true`, plus the `message_id` and a
 * `detail` — leaves the email in the queue (`classified_as = NEEDS_REVIEW`,
 * `is_reviewed = false`), and files nothing. The user's label is still kept as
 * a training example either way.
 *
 * The production incident this exists for: "Crusoe | Application Received" was
 * classified, the endpoint answered 200 with `application_id: null`, the row
 * left the queue and no application was ever created. A UI that treats HTTP 200
 * as "done" reproduces exactly that bug at the presentation layer even though
 * the backend is now honest, so the branch is decided here — once — and both
 * the component and its test read the same function.
 *
 * Deliberately dependency-free (no React, no `@/` alias, no generated schema)
 * so `tests/unit/` can load it directly under Node's type stripping. The one
 * import below is a TYPE, which stripping removes outright — it never becomes
 * a module specifier Node has to resolve.
 */

import type { ScanMessagePayload } from "../gmail/scan-correction";

/** What the user is told when the employer could not be read from the message. */
export const NEEDS_EMPLOYER_PROMPT =
  "We couldn't tell which company this email is from. Name it and we'll file it.";

/**
 * What the user is told when they already named a company and the backend still
 * could not use it — `pipeline.employer_from_text` rejects blank, stopword-only
 * and numeric strings, so a second `needs_employer: true` is a real outcome and
 * must not wedge the row.
 */
export const NEEDS_EMPLOYER_RETRY =
  "That didn't read as a company name. Try the employer as it's written in the message.";

/**
 * What the user is asked when the company they typed is one edit from one
 * already on their board — "Verkeda" against four "Verkada" rows, which is how
 * a rejection opened a fifth application instead of settling one of them.
 *
 * A question, never a correction applied for them: the same resemblance test
 * that catches a typo also catches two real employers (Stripe and Strive are
 * one edit apart), and joining those would move a live application to a
 * terminal stage the product cannot walk back.
 */
export function confirmCompanyPrompt(suggested: string): string {
  return `Did you mean ${suggested}? It's already on your board.`;
}

/** Fallback when the request itself failed and the backend named no reason. */
export const CLASSIFY_FAILED = "Couldn't classify this item.";

/**
 * Shortest company the backend will accept: `_valid_company_token` rejects
 * anything under two characters outright, so the round trip is pointless below
 * it. Everything else (stopwords, bare numbers) is the backend's call, not ours.
 */
export const MIN_COMPANY_LENGTH = 2;

/** Body of `POST /applications/review/{message_id}/classify`. */
export interface ClassifyRequestBody {
  category: string;
  /** Only consulted when the backend cannot resolve the employer itself. */
  company?: string;
  /**
   * Which existing application the message answers, when one employer holds
   * several — accepted and validated by `ReviewClassifyRequest` since the
   * entity-model change landed (see `reviewCandidates`).
   */
  application_id?: number;
  /**
   * The message's own metadata, for a row that may not be stored yet — the
   * live scan's case. Consulted by the backend ONLY when the message id is
   * unknown; a stored message is always corrected in place. Absent for the
   * filed ledger, whose rows are stored by definition.
   */
  message?: ScanMessagePayload;
  /**
   * "No — these really are two different employers." Sent only to answer a
   * `needs-confirmation` outcome, and only on a click that says so: a default
   * of `true` would be the silent acceptance this whole round trip exists to
   * stop.
   */
  confirm_new_company?: boolean;
}

/**
 * What actually happened, as opposed to what the status code implies.
 *
 * - `resolved` — the decision stuck and the item has left the queue. An
 *   application was filed when `applicationId` is non-null; "not job-related"
 *   resolves without filing one.
 * - `needs-employer` — nothing was filed, the item is still in the queue, and
 *   naming the company will file it.
 * - `needs-confirmation` — nothing was filed either, and the company that was
 *   named looks like `suggestedCompany`, which the board already holds. Two
 *   answers file it: re-send with the suggested spelling, or re-send with
 *   `confirm_new_company` to open a separate application.
 * - `failed` — the request was rejected; nothing changed.
 */
export type ClassifyOutcome =
  | { kind: "resolved"; applicationId: number | null }
  | { kind: "needs-employer"; messageId: string | null; detail: string | null }
  | {
      kind: "needs-confirmation";
      suggestedCompany: string;
      messageId: string | null;
      detail: string | null;
    }
  | { kind: "failed"; detail: string };

/** Build the request body; optional fields are sent only when they carry a value. */
export function classifyRequestBody(
  category: string,
  company?: string | null,
  applicationId?: number | null,
  message?: ScanMessagePayload | null,
  confirmNewCompany?: boolean | null,
): ClassifyRequestBody {
  const named = typeof company === "string" ? company.trim() : "";
  const body: ClassifyRequestBody = { category };
  if (named) body.company = named;
  if (confirmNewCompany === true) body.confirm_new_company = true;
  if (typeof applicationId === "number" && Number.isInteger(applicationId) && applicationId > 0) {
    body.application_id = applicationId;
  }
  // Sent on EVERY attempt for a scan row, including the re-send that answers
  // `needs_employer`. The first attempt does store the message (the backend
  // mints it before that early return, deliberately), so the re-send normally
  // finds it — but the half of the round trip that actually FILES must not
  // depend on that ordering, and the backend ignores the payload for a message
  // it already has.
  if (message) body.message = message;
  return body;
}

/** True once the user has typed enough for a re-submit to be worth making. */
export function canNameCompany(company: string): boolean {
  return company.trim().length >= MIN_COMPANY_LENGTH;
}

function asRecord(body: unknown): Record<string, unknown> {
  return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
}

/**
 * Read a classify response into the branch the UI must take.
 *
 * `needs_employer` is honoured only when it is literally `true`: an older
 * backend that omits the flag is read as `resolved`, which is the behaviour it
 * actually has. We never infer "nothing was filed" from a null `application_id`
 * — "not job-related" legitimately files nothing and still leaves the queue.
 *
 * The confirmation is read FIRST because the backend sends both flags on that
 * response. The pair is deliberate on its side (a client that has never heard
 * of the confirmation still keeps the row in the queue and prompts, instead of
 * dropping an item that filed nothing); reading them in the other order here
 * would throw away the suggestion and show the generic prompt.
 */
export function readClassifyOutcome(ok: boolean, body: unknown): ClassifyOutcome {
  const data = asRecord(body);
  const detail = typeof data.detail === "string" ? data.detail : null;

  if (!ok) return { kind: "failed", detail: detail ?? CLASSIFY_FAILED };

  // A confirmation with no name to offer is not a question anyone can answer,
  // so it falls through to the employer prompt rather than rendering "Did you
  // mean ?".
  const suggested = typeof data.suggested_company === "string" ? data.suggested_company.trim() : "";
  if (data.needs_company_confirmation === true && suggested) {
    return {
      kind: "needs-confirmation",
      suggestedCompany: suggested,
      messageId: typeof data.message_id === "string" ? data.message_id : null,
      detail,
    };
  }

  if (data.needs_employer === true) {
    return {
      kind: "needs-employer",
      messageId: typeof data.message_id === "string" ? data.message_id : null,
      detail,
    };
  }

  return {
    kind: "resolved",
    applicationId: typeof data.application_id === "number" ? data.application_id : null,
  };
}

/**
 * Whether the row must stay in the queue — anything but a resolved decision.
 *
 * A type predicate so the caller cannot act on "the row leaves" without having
 * narrowed to the outcome that says so.
 */
export function rowStaysInQueue(
  outcome: ClassifyOutcome,
): outcome is Extract<
  ClassifyOutcome,
  { kind: "needs-employer" | "needs-confirmation" | "failed" }
> {
  return outcome.kind !== "resolved";
}

/**
 * The prompt for a `needs-employer` outcome, given whatever company the user had
 * already supplied on that attempt. A second miss must read differently — the
 * backend rejected the name they typed, and repeating the first-time wording
 * would look like the click did nothing.
 */
export function employerPromptFor(attemptedCompany: string): string {
  return attemptedCompany.trim() ? NEEDS_EMPLOYER_RETRY : NEEDS_EMPLOYER_PROMPT;
}

// --- Assign-to-application candidates ----------------------------------------

/**
 * The board slice the picker needs — structural, so this module stays free of
 * the generated API schema (same rule as `filedAt` in `dates.ts`).
 */
export interface CandidateApplication {
  id: number;
  company: string;
  position: string;
  status: string;
}

/**
 * Which of the user's applications could this review item belong to?
 *
 * One company can now hold several applications (four Amazon roles in one
 * evening is the proven case), so a rejection from `amazon.jobs` is ambiguous
 * until the user says which role it answers. This is the conservative,
 * client-side half of that surface: an application is a candidate when its
 * company name appears in the message's sender or subject. Deliberately
 * strict — a false "which of these?" question is worse than no question —
 * and two-character names must match the sender's domain label exactly, or
 * "GE" would match half an inbox.
 *
 * The picker renders only when TWO OR MORE candidates match (one match is not
 * a question), and the chosen id rides the classify request as
 * `application_id` — accepted and validated by the backend since the
 * entity-model change landed. The truly robust version of this matching still
 * belongs server-side, where the message's resolved employer token exists;
 * this client-side pass is the conservative floor.
 */
export function reviewCandidates(
  item: { sender_email?: string | null; sender_name?: string | null; subject?: string | null },
  applications: readonly CandidateApplication[],
): CandidateApplication[] {
  const haystack = [item.sender_email, item.sender_name, item.subject]
    .filter((part): part is string => typeof part === "string")
    .join(" ")
    .toLowerCase();
  if (!haystack) return [];

  const senderDomainLabel = (() => {
    const email = typeof item.sender_email === "string" ? item.sender_email : "";
    const at = email.lastIndexOf("@");
    if (at === -1) return "";
    return email.slice(at + 1).toLowerCase().split(".")[0] ?? "";
  })();

  return applications.filter((app) => {
    const name = app.company.trim().toLowerCase();
    if (name.length < 2) return false;
    if (name.length === 2) return senderDomainLabel === name;
    return haystack.includes(name);
  });
}
