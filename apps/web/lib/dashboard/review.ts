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

/**
 * How the dashboard names its review count — a TO-DO, not a category.
 *
 * The dashboard counts the WORK QUEUE (`needs_review` AND unlinked AND not yet
 * reviewed, deduped by `pipeline.review_dedup_key`). The Inbox's chip counts
 * every STORED message carrying that verdict, one row per message, whatever
 * its linkage or reviewed state. Both are right, and the inbox is always the
 * larger of the two — so the same words on both screens read as a bug in one
 * of them, which is what production showed: 8 on the dashboard, 9 in the inbox
 * (#445).
 *
 * The two labels must stay DIFFERENT words. `CATEGORY_META.needs_review`'s
 * `chipLabel` in `lib/gmail/types.ts` is the other half, and
 * `tests/unit/review-counts-are-labelled-apart.test.mjs` reds if a later
 * cleanup unifies them.
 */
export const REVIEW_QUEUE_LABEL = "to review";

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

/**
 * WHAT THE USER HAS SAID ABOUT WHICH APPLICATION THIS MESSAGE IS ABOUT.
 *
 * Three states, because the two that used to share `null` are different
 * answers: `null` is "not asked yet", `"none"` is "none of the ones you showed
 * me", and a number is the row they picked. Collapsing the first two is the
 * defect (#554) — the discarding option was pre-selected, so a user who read
 * the subject, chose a stage and clicked classify answered "none of my
 * applications at this employer" without ever choosing it.
 */
export type ReviewAssignment = number | "none" | null;

/** Has the user answered the picker at all? `"none"` IS an answer. */
export function pickerAnswered(assignment: ReviewAssignment): boolean {
  return assignment !== null;
}

/**
 * May this decision be sent?
 *
 * THE ONE PLACE THAT DECIDES, and it is deliberately not the submit button's
 * `disabled` attribute. Three other controls re-send the same decision — both
 * confirmation buttons and the needs-employer form — and none of them consults
 * that attribute, so a gate written only there is a gate with a side door: a
 * `needs_employer` round trip re-enables the category select, changing it
 * clears the pick, and the still-mounted prompt then files blind.
 */
export function canSubmitReview(
  category: string,
  showPicker: boolean,
  assignment: ReviewAssignment,
): boolean {
  if (!category) return false;
  return !showPicker || pickerAnswered(assignment);
}

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
  /**
   * "None of the applications you showed me." Sent only when the user chose
   * that option against a rendered picker.
   *
   * It exists because an ABSENT `application_id` cannot carry it. Absent means
   * "nobody asked" — a single-candidate row, a message already filed against a
   * row of this employer's, a correction that opens nothing ("applied", "not
   * job related"), the live scan (which cannot see the board), and every sync —
   * and the backend answers that by tie-breaking onto the employer's oldest
   * row. That is the right answer to silence and the
   * wrong answer to a person saying "not one of those": for a rejection the
   * tie-break moves a live application to a terminal status, which
   * `advance_application_status` never walks back.
   *
   * The field crosses FIVE rebuilds, not the three that are obvious from here:
   * this function, the proxy's `readClassifyBody`, its `classifyBackendBody`,
   * and then FastAPI's own re-spread of the parsed body into arguments. The
   * last one is the least visible and was the one that could be cut with every
   * test still green.
   *
   * So the two are separated on the wire. With this flag the backend skips
   * resolution entirely and opens a new application, which is what the user
   * literally said: a lifecycle message about an application the board does not
   * hold IS an application the board is missing. A spurious row is one dismiss
   * click; a wrongly-terminal row is permanent.
   */
  none_of_these?: boolean;
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
  assignment?: ReviewAssignment,
  message?: ScanMessagePayload | null,
  confirmNewCompany?: boolean | null,
): ClassifyRequestBody {
  const named = typeof company === "string" ? company.trim() : "";
  const body: ClassifyRequestBody = { category };
  if (named) body.company = named;
  if (confirmNewCompany === true) body.confirm_new_company = true;
  // THE ANSWER TRAVELS AS ONE VALUE, so a caller cannot send the id and forget
  // the flag, or send the flag and forget to clear the id. `"none"` and a row
  // id are two answers to one question and they are built from one argument.
  if (assignment === "none") {
    body.none_of_these = true;
  } else if (
    typeof assignment === "number" &&
    Number.isInteger(assignment) &&
    assignment > 0
  ) {
    body.application_id = assignment;
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

/**
 * Categories that ANSWER an existing application rather than opening one.
 *
 * A rejection, an interview invitation, an assessment or an offer is a stage in
 * an application that already exists, so at an employer holding several it is
 * ambiguous until someone says which. "applied" opens a row and "not job
 * related" opens nothing, so neither has a which-one to ask about.
 *
 * A SET WHOSE MEMBERS ARE NOT ASSERTED INDIVIDUALLY IS A SET WITH ONE MEMBER
 * (#554): dropping "offer" or "assessment" here was green until there was one
 * test per member, plus the two controls that must ask NOTHING — without which
 * "always ask" satisfies the whole loop.
 */
/**
 * The categories a correction may send, and the word the reader picks for
 * each. It lives here rather than in `ReclassifyControl` because it now
 * answers two questions, and they must not be allowed to disagree: which
 * options the select offers, and — since #511 — which PRIOR verdicts an undo
 * is allowed to send back.
 *
 * The list starts at a placeholder in the control on purpose; a preselected
 * value is how absent-minded clicks become verdicts.
 *
 * The labels are the CATEGORY's vocabulary, not the stage's.
 * `EmailCategory.INTERVIEW` is "interview" (models.py:131);
 * `ApplicationStatus.INTERVIEWING` is "interviewing" (:109). Two vocabularies
 * on purpose — one names what a MESSAGE is, the other names where a CARD sits
 * — and this list asks the first question, so it answers in the first
 * vocabulary. #425.
 */
export const CORRECTION_CHOICES: readonly { value: string; label: string }[] = [
  { value: "applied", label: "applied" },
  { value: "interview", label: "interview" },
  { value: "assessment", label: "assessment" },
  { value: "offer", label: "offer" },
  { value: "rejection", label: "rejection" },
  { value: "other", label: "not job related" },
];

const CORRECTABLE = new Map(CORRECTION_CHOICES.map((c) => [c.value, c.label]));

/** The reader's word for a category; the raw value for anything the backend
 *  grew that this list has not caught up with. */
export function categoryLabel(value: string): string {
  return CORRECTABLE.get(value) ?? value.replaceAll("_", " ");
}

/**
 * The verdict an undo may send back, or `null` when there is none.
 *
 * A correction is reversed by re-sending the message's PREVIOUS category
 * through the same endpoint, so an undo is only real when that category is one
 * this control could have sent in the first place. `needs_review` is the case
 * that matters: it is a genuine stored verdict, it is not on the list above,
 * and offering an Undo that would 422 is exactly the decorative affordance
 * `notifyUndo` forbids. Those corrections are acknowledged and not undoable,
 * which is the truth.
 */
export function undoableVerdict(previous: string | null | undefined): string | null {
  const value = typeof previous === "string" ? previous.trim() : "";
  return CORRECTABLE.has(value) ? value : null;
}

/**
 * What the correction surfaces say once the row has left the list.
 *
 * The action keeps its name through the flow: the ledger's control is
 * "reclassify", so its outcome is "Reclassified"; the queue's button is
 * "classify", so its outcome is "Classified".
 *
 * THEY TAKE THE READER'S WORD, NOT THE ENUM, and the caller resolves it from
 * the list IT rendered. That is not indirection for its own sake: the queue
 * still labels `interview` as "interviewing" — the stage's vocabulary, which
 * #425 corrected on the ledger's control and never reached here — so a toast
 * that resolved the label itself would name a word the reader did not choose.
 * Echoing the control is the rule that matters; unifying the two lists is a
 * copy change to a rendered option and belongs in its own commit.
 */
export function reclassifiedMessage(label: string): string {
  return `Reclassified as ${label}`;
}

export function classifiedMessage(label: string): string {
  return `Classified as ${label}`;
}

/** A failed undo. Names the verdict the message is actually left at, so the
 *  reader is never guessing which of the two it now holds. */
export function undoClassifyFailedMessage(label: string): string {
  return `Couldn't change it back — it is still ${label}.`;
}

export const LIFECYCLE_ANSWERS: ReadonlySet<string> = new Set([
  "interview",
  "assessment",
  "offer",
  "rejection",
]);

/** Everything either surface knows when it sends a classify decision. */
export interface ClassifyDecision {
  category: string;
  /** Only consulted once the backend has asked for the employer by name. */
  company?: string | null;
  /** The employer's rows this message could be about (see `reviewCandidates`). */
  candidates: readonly CandidateApplication[];
  /**
   * The row this message is ALREADY filed against, or null when it is not
   * filed against one. The review queue is unlinked by construction and passes
   * null; the filed ledger passes what the row carries.
   */
  linkedApplicationId?: number | null;
  /** What the user answered — `null` is "not asked / not answered yet". */
  assignment: ReviewAssignment;
  message?: ScanMessagePayload | null;
  confirmNewCompany?: boolean | null;
}

/**
 * Must this decision ask WHICH APPLICATION it is about?
 *
 * THE ONE PLACE THAT DECIDES, for every surface that sends a correction —
 * `ReviewQueue` and `ReclassifyControl` both read it, and both render the
 * question through the one `ApplicationPicker`. Two renderers of one question
 * is a defect this estate has already paid for twice; two PREDICATES behind one
 * question is the same defect one level down, because the surface that asks and
 * the surface that files then disagree about when the answer was required.
 *
 * Three ways the answer is no, and each is a different reason:
 *
 * - THE MESSAGE IS ALREADY FILED AGAINST A ROW. Its link outranks every
 *   tie-break inside `_resolve_application_for_email` (#546 / #548), so the
 *   backend cannot get this one wrong and there is nothing to ask. Asking
 *   anyway would offer "none of these — track it as a new application" over a
 *   message that is already tracked, which is a new way to scatter a record.
 * - FEWER THAN TWO CANDIDATES. One option is not a question. Nobody is asked,
 *   the request carries no answer, and the backend's tie-break has one row to
 *   break between — which is the right row.
 * - THE CATEGORY OPENS A ROW OR OPENS NOTHING. See `LIFECYCLE_ANSWERS`.
 *
 * A THRESHOLD NEEDS A CASE SITTING ON IT (#554). `>= 2` is the smallest
 * ambiguous board there is; narrowing it to `>= 3` reintroduces the defect for
 * exactly that case and is invisible to fixtures that only ever hold one row
 * and four.
 */
export function asksWhichApplication(decision: {
  category: string;
  candidates: readonly CandidateApplication[];
  linkedApplicationId?: number | null;
}): boolean {
  if (typeof decision.linkedApplicationId === "number") return false;
  return decision.candidates.length >= 2 && LIFECYCLE_ANSWERS.has(decision.category);
}

/**
 * The body a CORRECTION SURFACE sends — the picker's answer included.
 *
 * Both surfaces build their request here, so the hop that carries the user's
 * answer onto the wire is executed by `tests/unit/` on the queue's path and the
 * ledger's path alike. `ReclassifyControl` shipped for months with a literal
 * `null` in this position: it never asked, so it never had an answer to send,
 * and an unlinked message at an employer holding several rows was filed onto
 * the oldest by a tie-break nobody had been consulted about (#560).
 *
 * The assignment is DROPPED when the question was not asked, and that is not
 * belt-and-braces. A stale pick from a stage the user then changed away from
 * would otherwise ride along as an answer to a question no longer on screen.
 */
export function classifyDecisionBody(decision: ClassifyDecision): ClassifyRequestBody {
  return classifyRequestBody(
    decision.category,
    decision.company,
    asksWhichApplication(decision) ? decision.assignment : null,
    decision.message,
    decision.confirmNewCompany,
  );
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
 * Lowercase, collapse to `[a-z0-9]` words, single-space joined.
 *
 * The mirror of `pipeline.normalize_company_name`, which is the ONLY spelling
 * of "the same company" the backend mints tokens under. A fifth spelling here
 * (`lower(company)` was the fourth, and it filed a second "Together AI" row on
 * every sync) is how the two sides start disagreeing.
 */
function normalizeCompanyName(value: string): string {
  return (value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Does a board row's company NAME identify the employer this TOKEN names?
 *
 * THE WEB MIRROR OF `pipeline.matches_company_token`, and it has to be one.
 * The two sides are minted differently and cannot simply be compared: a row
 * stores the human DISPLAY name ("Northwind Traders", "Together AI"), while
 * the token is either the sender's domain brand or the normalized FIRST WORD
 * of a display name ("northwind", "together"). So the rule is: normalize both,
 * then accept a full match OR a match on the leading word.
 *
 * WHAT A SECOND, LOOSER RULE COSTS — measured, not argued. Before this existed
 * the client asked `haystack.includes(row.company)`, so a board row named
 * "Northwind Traders" was not a candidate for mail whose employer token is
 * "northwind". The backend's `_company_rows` matched it on the leading word,
 * `_pick_application`'s rule 4 tie-broke onto the oldest of them, and a live
 * application moved stage with the ledger showing no question at all:
 *
 *     board  [(1 "Northwind Traders" applied), (2 "Northwind Traders" applied)]
 *     mail   no-reply@greenhouse.io, "Northwind Hiring Team"
 *     ledger candidates 0 -> asks nothing
 *     POST   {"category":"interview"}  ->  application_id 1, moved unasked
 *
 * A board name LONGER than the name the mail uses is the normal case, not an
 * edge one, so that gap covered most real ATS mail. The picker may only offer
 * rows the backend would ACCEPT as an answer (`_chosen_application` validates
 * the choice against the same `_company_rows`), which is exactly what sharing
 * this rule buys.
 *
 * Held to the Python original by `tests/fixtures/employer-token-match.json`,
 * a table both sides execute.
 */
export function matchesEmployerToken(companyName: string, token: string): boolean {
  const left = normalizeCompanyName(companyName);
  const right = normalizeCompanyName(token);
  if (!left || !right) return false;
  if (left === right) return true;
  return left.split(" ")[0] === right.split(" ")[0];
}

/**
 * Which of the user's applications could this review item belong to?
 *
 * One company can now hold several applications (four Amazon roles in one
 * evening is the proven case), so a rejection from `amazon.jobs` is ambiguous
 * until the user says which role it answers. An application is a candidate
 * when EITHER its company name appears in the message's sender or subject, OR
 * it matches the employer token the backend resolved for that message. Both
 * arms are load-bearing:
 *
 *   - the token arm is what makes this fire on the mail the picker exists for.
 *     That mail is an ATS relay — `no-reply@greenhouse.io`, "Update on your
 *     application" — and it is also what makes a board row whose name is
 *     LONGER than the mail's ("Northwind Traders" against "northwind") a
 *     candidate at all. See `matchesEmployerToken` for the measured cost of
 *     not having it.
 *   - the haystack arm still carries every surface that has no token: the
 *     needs-review queue passes none (`ReviewItem` has `suggested_employer`,
 *     which is a question the backend is ASKING, not an answer it reached), so
 *     its behaviour and its e2e gate are untouched by this.
 *
 * Deliberately strict otherwise — a false "which of these?" question is worse
 * than no question — so a two-character name must be the WHOLE of one exact
 * signal (the sender's domain label, or the token) rather than something found
 * inside a haystack, or "GE" would match half an inbox.
 *
 * `employer_token` is FILING grade used at DISPLAY grade, which is the safe
 * direction: the backend derives it from the sender's own domain, the subject
 * and (for relays) the display name — never from the body or the snippet. It
 * is never guessed here.
 *
 * The picker renders only when TWO OR MORE candidates match (one match is not
 * a question), and the chosen id rides the classify request as
 * `application_id` — validated by the backend against the same employer.
 */
export function reviewCandidates(
  item: {
    sender_email?: string | null;
    sender_name?: string | null;
    subject?: string | null;
    /**
     * The employer token the BACKEND resolved for this message, where the
     * surface has one. Never a guess made here, and never `company` — that is
     * the linked application's display name and is null on precisely the rows
     * this question is asked about.
     */
    employer_token?: string | null;
  },
  applications: readonly CandidateApplication[],
): CandidateApplication[] {
  const haystack = [item.sender_email, item.sender_name, item.subject]
    .filter((part): part is string => typeof part === "string")
    .join(" ")
    .toLowerCase();
  const token = typeof item.employer_token === "string" ? item.employer_token.trim() : "";
  if (!haystack && !token) return [];

  const senderDomainLabel = (() => {
    const email = typeof item.sender_email === "string" ? item.sender_email : "";
    const at = email.lastIndexOf("@");
    if (at === -1) return "";
    return email.slice(at + 1).toLowerCase().split(".")[0] ?? "";
  })();

  return applications.filter((app) => {
    const name = app.company.trim().toLowerCase();
    if (name.length < 2) return false;
    if (token && matchesEmployerToken(app.company, token)) return true;
    // A two-letter name is too short to be evidence inside a haystack, so it
    // has to be the WHOLE of one exact signal.
    if (name.length === 2) return senderDomainLabel === name;
    return haystack.includes(name);
  });
}

/**
 * The hold reasons `GET /applications/review` can report, as it spells them.
 *
 * Mirrors `pipeline.HOLD_REASONS`. Strings rather than an enum on both sides so
 * a reason this build has never heard of arrives as a string it can decline to
 * render, instead of a parse error — see `holdReasonSentence`.
 */
export const HOLD_REASONS = [
  "no_proposal",
  "below_gate",
  "ats_floor",
  "no_employer",
  "confirm_employer",
  "not_fileable",
  "which_application",
  "gated_other",
] as const;

export type HoldReason = (typeof HOLD_REASONS)[number];

/**
 * Why this message is waiting, in the queue's own voice — or `null` when it
 * cannot be said.
 *
 * THE WHOLE POINT IS THAT THERE IS NO FALLBACK SENTENCE (#507). This line used
 * to be derived from `confidence` alone:
 *
 *     item.confidence >= AUTO_FILE_GATE
 *       ? "cleared the gate · held for a missing employer name"
 *       : `below the ${AUTO_FILE_GATE} gate · your call decides it`
 *
 * which told every confident held row that its employer could not be named,
 * whatever had actually stopped it. That guess was right on the rows it was
 * reported about — and only by coincidence, because those three really did
 * fail employer resolution (#512). A label that is correct by luck is not
 * correct, it is untested, and the next `unplaceable` row would have inherited
 * a sentence about a problem it does not have.
 *
 * So an unknown or absent reason renders NOTHING. Silence is worse copy and
 * better information: the row still shows its confidence and its controls, and
 * the user is not told something untrue about their own mail.
 */
export function holdReasonSentence(
  reason: string | null | undefined,
  gate: number,
  suggestedEmployer?: string | null,
): string | null {
  switch (reason) {
    // The only "missing employer" there has ever been. The user's next move is
    // to type the company, which is the control sitting directly below.
    case "no_employer":
      return "cleared the gate · we couldn't name the employer";
    // The filing path could not name the employer, but the message body does,
    // and the user is looking straight at that body. Saying "we couldn't name
    // it" over a line that names it is the exact complaint behind #512. So we
    // put the name we read in front of them and ask them to confirm it, which
    // is both honest about what happened and one click from filing.
    //
    // The name is only ever the backend's — never re-read here. If it did not
    // travel, the reason still says something true without inventing one.
    case "confirm_employer":
      return suggestedEmployer
        ? `cleared the gate · is this ${suggestedEmployer}?`
        : "cleared the gate · confirm the employer to file it";
    // Confident, but this kind of update is never filed on its own. Neither
    // the employer nor the score is the obstacle, and reporting one of those
    // sent people hunting for a problem that was not there.
    case "not_fileable":
      return "cleared the gate · not a change we file on its own";
    // Employer known, role unknown, and that employer holds several
    // applications — so the question is WHICH, and the row's own picker is
    // where it gets answered. Naming the wrong question here is what sent
    // people looking for a company field that was never the problem.
    case "which_application":
      return "cleared the gate · which of your applications is this?";
    case "below_gate":
      return `below the ${gate} gate · your call decides it`;
    // The classifier offered no category at all, which is a different state
    // from a weak one and deserves to read differently.
    case "no_proposal":
      return "no category proposed · your call decides it";
    // Kept only because a known ATS relayed it (#166). Saying so explains why
    // a low-confidence row is in front of the user at all.
    case "ats_floor":
      return "under the floor · kept because an ATS sent it";
    // Deliberately not smoothed into a neighbour. A confident row held for no
    // reason this build can name is a BUG, and it should read like one rather
    // than borrow a plausible sentence from a case it does not belong to.
    case "gated_other":
      return "cleared the gate · held, and we can't say why";
    default:
      return null;
  }
}

// --- Grouping the ASKING, never the answering --------------------------------

/**
 * The queue-row slice grouping reads.
 *
 * Structural, for the same reason as `CandidateApplication` above: this module
 * is loaded directly by `tests/unit/` under Node's type stripping and must stay
 * free of React and of the generated schema. `ReviewItem` in
 * `components/dashboard/ReviewQueue.tsx` satisfies it structurally; importing
 * that type back from the `.tsx` would put a component on this module's import
 * graph for nothing.
 */
export interface GroupableReviewItem {
  message_id: string;
  subject?: string | null;
  sender_name?: string | null;
  sender_email?: string | null;
  received_at?: string | null;
  /** Derived identity — what tells two applications at one employer apart. */
  role?: string | null;
  /**
   * The classifier's own guess, read ONLY to decide whether a group opens
   * collapsed. Never compared, never counted, never rendered — see
   * `groupReviewItems`. ORDERING AND GATING ONLY.
   */
  suggested_category?: string | null;
  employer_token?: string | null;
}

/** One queue row with the candidate pool it resolved to — computed ONCE. */
export interface ReviewUnitMember<T extends GroupableReviewItem> {
  item: T;
  candidates: CandidateApplication[];
}

/** One line of the queue: either a lone row, or several rows about one employer. */
export interface ReviewUnit<T extends GroupableReviewItem> {
  /**
   * The GROUP key — normalised company and normalised role joined on NUL — or
   * `null` where the row is ungrouped and stands alone.
   *
   * NUL is the separator because `normalizeCompanyName` emits `[a-z0-9 ]` only,
   * so it cannot appear on the left of the join and a company whose name ends
   * where a role begins cannot collide with a different split of the same
   * characters. It is also what lets the render fall back to `message_id` for
   * an ungrouped row without either namespace reaching the other.
   */
  key: string | null;
  /** The board's DISPLAY spelling of the employer, for the header. */
  company: string | null;
  /** The role as the mail carried it, unnormalised. `null` on most live rows. */
  role: string | null;
  members: ReviewUnitMember<T>[];
  /** The NEWEST member's receipt time, so an aging group visibly ages. */
  receivedAt: string | null;
  /**
   * Whether every member carries the same `suggested_category`.
   *
   * The one permitted gate. See `groupReviewItems` for why it may only open the
   * group WIDER and never narrower.
   */
  uniformCategory: boolean;
}

/** NUL — see `ReviewUnit.key`. */
const GROUP_KEY_SEP = "\u0000";

/**
 * A role reduced to what makes two of them the same question.
 *
 * Case and internal whitespace only. NOT `normalizeCompanyName`: a role is
 * punctuated on purpose ("Backend Engineer, Alarms" against "Backend Engineer -
 * Access Control" are two requisitions at one employer, and the demo queue
 * carries exactly that pair), and folding punctuation out of it would merge
 * what #454 split.
 *
 * RENDER LAYER ONLY, AND THE LICENCE STOPS AT THAT BOUNDARY. This is a
 * deliberate MERGE widening — it decides that two spellings are one heading —
 * and it is safe here for one reason: the worst case is a confusing header, and
 * the reader still answers every row individually. Never reuse it for a key
 * that FILES, LINKS or DEDUPES anything. There the same widening silently
 * destroys a record, which is the asymmetry (#454) that put this whole feature
 * at the presentation layer instead of in the pipeline. A filing-grade role key
 * is a different function with a different bar.
 */
function normalizeRoleName(value: string | null | undefined): string | null {
  const folded = typeof value === "string" ? value.trim().toLowerCase().replace(/\s+/g, " ") : "";
  return folded ? folded : null;
}

/** Milliseconds, or `null` for absent/unparseable — the queue renders dateless rows. */
function receivedMillis(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/** Newest first, dateless last. A total order, so the render is deterministic. */
function newestFirst(a: number | null, b: number | null): number {
  if (a === b) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return b - a;
}

/**
 * The queue's rows, collapsed into the things it is asking ABOUT (#517).
 *
 * WHAT THIS MAY AND MAY NOT DO. In the review band every field the classifier
 * produced — stage, category, confidence — IS the doubted object; `NEEDS_REVIEW`
 * is the typed null. Classifier output may ORDER and GROUP the asking, and may
 * never ANSWER it. So this changes no data, removes no row and merges no
 * decision: every member keeps its own select, its own picker and its own
 * classify button, and the answer count is invariant. Grouping collapses the
 * READING, and there is deliberately no group-level answer control of any kind —
 * a bulk "these are all the assessment" affordance would let a misread rejection
 * be swept in as an AUTHORITATIVE USER ANSWER, which outranks machine evidence
 * permanently.
 *
 * The alternative was closed by measurement rather than by taste, and it is
 * cheap to rebuild, so it is written down here: not queueing (or silently
 * attaching) a held row whose suggested stage would not move its card was built
 * and measured over 40 day-batches of the independent corpus, and 69 of the 137
 * rows it touched were ground-truth REJECTIONS. A rejection whose verdict
 * sentence falls past the stored snippet reads as a polite preamble and scores
 * the card's own stage, so "would not move anything" is true of exactly the
 * message that would move everything. Agreement with the card is the SIGNATURE
 * of the misread, not noise around it. Do not reintroduce a stage predicate
 * here in any form.
 *
 * THE KEY. For each row, ask `reviewCandidates` — the picker's own function,
 * called ONCE and handed back on the member so a group can never offer options
 * the picker would not — which applications the mail could name. If every
 * candidate is the same employer by `normalizeCompanyName`, the row's key is
 * that name plus its `role`; anything else (no candidate, or candidates at two
 * different employers) is ungrouped and renders alone.
 *
 * `role` IS A MANDATORY SECOND COMPONENT. One employer legitimately holds
 * several applications — that is #454's whole case, and `ReviewItem.role`'s own
 * comment calls the field "the only field that tells them apart". Three held
 * acknowledgements for three different requisitions at one employer are three
 * questions, and company alone folds them under one header. It is derived
 * identity rather than classifier output, so it is lawful in the band. Stated
 * honestly: the live queue carries no roles at all today (measured, 0 of 8), so
 * this component is insurance rather than an observed fix.
 *
 * The rule this function is bound by is recorded as DEC-009 — "fields of a band
 * verdict are not decision inputs; render-layer use only" — because the
 * rejected alternative is attractive, cheap to rebuild, and invisible from this
 * code.
 *
 * `suggested_category` IS READ HERE AND NOWHERE ELSE, for one gate: a group
 * whose members DISAGREE about it opens EXPANDED. That spends band data to
 * demand more scrutiny, never less, which is the only direction the law above
 * permits. It is never rendered — printing "assessment x3" above the select the
 * reader is about to answer is the machine's guess at the strongest anchoring
 * position on the page, in the band where #554 measured what a
 * preselection-shaped default costs (19 applications destroyed, 0 once the
 * answer had to be the user's). ALL-ABSENT COUNTS AS AGREEMENT: disagreement
 * needs two distinct known values, and a backend that sends no category at all
 * has not disagreed about anything.
 *
 * ORDER. Units newest-member-first, members newest-first, dateless last — so an
 * aging pile sinks as a pile and the header can honestly show one date.
 */
export function groupReviewItems<T extends GroupableReviewItem>(
  items: readonly T[],
  applications: readonly CandidateApplication[],
): ReviewUnit<T>[] {
  const units: ReviewUnit<T>[] = [];
  const byKey = new Map<string, ReviewUnit<T>>();

  for (const item of items) {
    const candidates = reviewCandidates(item, applications);
    const member: ReviewUnitMember<T> = { item, candidates };

    // "All share one company NAME" — NOT "exactly one candidate". An employer
    // holding four cards is one employer, and that is the shape the picker
    // exists for; two candidates at two DIFFERENT employers is a row this
    // cannot place and must not group.
    const names = new Set(candidates.map((c) => normalizeCompanyName(c.company)));
    const normalized = names.size === 1 ? ([...names][0] as string) : "";

    if (!normalized) {
      units.push({
        key: null,
        company: null,
        role: null,
        members: [member],
        receivedAt: item.received_at ?? null,
        uniformCategory: true,
      });
      continue;
    }

    const key = `${normalized}${GROUP_KEY_SEP}${normalizeRoleName(item.role) ?? ""}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.members.push(member);
      continue;
    }
    // The board's own spelling, from the first member to reach this key. The
    // candidates all normalise alike by construction, so any of them names the
    // same employer; this one is the one the reader met first.
    const unit: ReviewUnit<T> = {
      key,
      company: candidates[0]!.company,
      role: item.role ?? null,
      members: [member],
      receivedAt: null,
      uniformCategory: true,
    };
    byKey.set(key, unit);
    units.push(unit);
  }

  for (const unit of units) {
    unit.members.sort((a, b) =>
      newestFirst(receivedMillis(a.item.received_at), receivedMillis(b.item.received_at)),
    );
    unit.receivedAt = unit.members[0]!.item.received_at ?? null;
    const categories = new Set(unit.members.map((m) => m.item.suggested_category ?? null));
    unit.uniformCategory = categories.size <= 1;
  }
  units.sort((a, b) => newestFirst(receivedMillis(a.receivedAt), receivedMillis(b.receivedAt)));
  return units;
}

/**
 * The header line for a group, composed from RAW FACTS only.
 *
 * "N held messages · <Company> · <Role> · <date>", and never "about one
 * application": the key proves same employer NAME and same derived role, which
 * is not the same claim as one application — an employer holds several (#454).
 * Nothing the classifier produced appears here — see `groupReviewItems`.
 *
 * THE ROLE IS PART OF THE LINE BECAUSE IT IS PART OF THE KEY. Without it, two
 * groups at one employer differing only by requisition rendered byte-identical
 * headers: the key told them apart and the copy did not, so the reader met "2
 * held messages · <Company>" twice with no way to tell which pile was which.
 * That is the "asking about one employer several times" complaint reappearing
 * one level up, and a header must name every component the grouping used.
 * Omitted when the unit has no role, which is the live queue's whole
 * population today — a trailing separator with nothing after it is noise.
 *
 * Both names arrive already neutralised by the caller (`safeText`): an employer
 * name and a role are mail-derived, and this string becomes a button's
 * accessible name.
 */
export function reviewGroupHeading(
  count: number,
  company: string,
  role: string | null,
  date: string | null,
): string {
  return [`${count} held messages`, company, role, date]
    .filter((part): part is string => Boolean(part))
    .join(" · ");
}
