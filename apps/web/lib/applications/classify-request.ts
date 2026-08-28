/**
 * BOTH rebuilds of the classify body, in the one module a test can execute.
 *
 * A correction crosses three hops on its way to FastAPI, and each one rebuilds
 * the body rather than forwarding it, so every field a hop does not name is
 * silently lost:
 *
 *   1. `lib/dashboard/review.ts` `classifyRequestBody` — browser → proxy
 *   2. `readClassifyBody` here                          — proxy reads it
 *   3. `classifyBackendBody` here                       — proxy → FastAPI
 *
 * That loss has now happened four times: `confidence` in the inbox relay,
 * `applied_date` and `url` on create, and `confirm_new_company` across hops 2
 * and 3 — which shipped `needs_company_confirmation` (PR #181, issue #167) as a
 * question the user could be asked but could never answer.
 *
 * Hop 3 used to live inside `lib/applications/server.ts`, which reaches for
 * `env.server` and the Supabase session and so cannot be loaded by
 * `tests/unit/`. It was covered by types and review only — and `tsc` is green
 * either way, because a hand-written narrowing that omits a field is
 * well-typed. Moving it here is the point: the module stays dependency-free so
 * `tests/unit/` can load it under Node's type stripping, and a dropped field
 * now means a deleted line where the tests are.
 *
 * None of these losses is cosmetic. Dropping `application_id` makes the backend
 * fall back to the employer's first row, the arbitrary-sibling filing the
 * identity work exists to stop; dropping `confirm_new_company` makes a
 * genuinely-distinct employer unfilable.
 */

/**
 * The metadata that lets the backend STORE a message it has never seen — the
 * live scan's rows are verdicts about un-stored mail. Mirrors
 * `ScannedMessageIn`; `sender_email` and `received_at` are the two the backend
 * cannot do without (the employer is resolved from the sender, and
 * `Email.received_at` is NOT NULL and is never fabricated).
 */
export interface ClassifyMessage {
  sender_email: string;
  received_at: string;
  subject?: string;
  sender_name?: string;
  category?: string;
  confidence?: number;
  method?: string;
}

/** Everything the backend call takes, as one value. */
export interface ClassifyArgs {
  category: string;
  company?: string;
  applicationId?: number;
  message?: ClassifyMessage;
  /**
   * "No — these really are two different employers", the human's answer to the
   * backend's `needs_company_confirmation`. Absent unless the user clicked it:
   * a default of `true` is the silent acceptance the round trip exists to stop.
   */
  confirmNewCompany?: boolean;
  /**
   * "None of the applications you showed me." The user's answer to the review
   * queue's picker, and the reason it cannot simply be an absent
   * `applicationId`: absent means "nobody asked", which the backend answers by
   * tie-breaking onto the employer's oldest row.
   */
  noneOfThese?: boolean;
}

/**
 * The parse result. The accepted branch carries the arguments as ONE object,
 * and `classifyReviewItem` takes that object whole — so forwarding is a single
 * value the handler cannot partially drop. Positional arguments are how
 * `confidence`, `applied_date` and `url` were each lost on this kind of hop;
 * with a bag, losing a field means deleting it here, where the tests are.
 */
export type ClassifyRequest =
  | ({ ok: true } & ClassifyArgs)
  | { ok: false; status: number; detail: string };

/** Copy an optional string field only when it actually carries text. */
function optionalText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * Narrow the optional scan-message payload.
 *
 * Returns `undefined` for anything that is not a usable store request rather
 * than forwarding a half-payload: a message with no sender or no receive time
 * is one the backend would refuse anyway, and forwarding it turns an honest
 * client-side "this row can't be corrected" into a 422 the reader has to
 * interpret. Unknown keys are dropped — this handler rebuilds the body, which
 * is precisely why every field it wants has to be named here.
 */
function readClassifyMessage(raw: unknown): ClassifyMessage | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const m = raw as Record<string, unknown>;

  const senderEmail = optionalText(m.sender_email);
  const receivedAt = optionalText(m.received_at);
  if (!senderEmail || !receivedAt) return undefined;

  const confidence =
    typeof m.confidence === "number" && Number.isFinite(m.confidence) ? m.confidence : undefined;

  return {
    sender_email: senderEmail,
    received_at: receivedAt,
    ...(optionalText(m.subject) ? { subject: optionalText(m.subject)! } : {}),
    ...(optionalText(m.sender_name) ? { sender_name: optionalText(m.sender_name)! } : {}),
    ...(optionalText(m.category) ? { category: optionalText(m.category)! } : {}),
    ...(confidence !== undefined ? { confidence } : {}),
    ...(optionalText(m.method) ? { method: optionalText(m.method)! } : {}),
  };
}

/**
 * Validate and narrow a classify body.
 *
 * `application_id` is accepted only as a real integer. A float, a numeric
 * string, `null` or `NaN` are all treated as absent rather than coerced —
 * coercing would send the backend an id the user never chose.
 */
export function readClassifyBody(raw: unknown): ClassifyRequest {
  const body = (typeof raw === "object" && raw !== null ? raw : {}) as {
    category?: unknown;
    company?: unknown;
    application_id?: unknown;
    message?: unknown;
    confirm_new_company?: unknown;
    none_of_these?: unknown;
  };

  const category = typeof body.category === "string" ? body.category.trim() : "";
  if (!category) return { ok: false, status: 422, detail: "category is required" };

  const company = typeof body.company === "string" ? body.company.trim() : "";
  const applicationId =
    typeof body.application_id === "number" && Number.isInteger(body.application_id)
      ? body.application_id
      : undefined;
  const message = readClassifyMessage(body.message);
  // Literally `true` and nothing else. A truthy string or a 1 is not a person
  // clicking "no, a different company", and this flag is the one input that
  // makes the backend skip the typo check — coercing into it would restore the
  // silent acceptance by the back door.
  const confirmNewCompany = body.confirm_new_company === true;
  // Literally `true`, for the same reason and with more at stake: this flag is
  // what makes the backend OPEN A ROW instead of resolving one. A truthy string
  // arriving from anywhere would mint applications nobody asked for.
  const noneOfThese = body.none_of_these === true;

  return {
    ok: true,
    category,
    ...(company ? { company } : {}),
    ...(applicationId !== undefined ? { applicationId } : {}),
    ...(message !== undefined ? { message } : {}),
    ...(confirmNewCompany ? { confirmNewCompany } : {}),
    ...(noneOfThese ? { noneOfThese } : {}),
  };
}

/**
 * The body the BACKEND is sent, built from a parsed request.
 *
 * Lives here rather than in `lib/applications/server.ts` for the reason this
 * whole module exists: `server.ts` reaches for `env.server` and the Supabase
 * session, so `tests/unit/` cannot load it, and the second rebuild of this body
 * was therefore covered by types and review only. That is exactly how
 * `confirm_new_company` was lost — the client built it (`classifyRequestBody`),
 * a test asserted the client built it, and then TWO successive rebuilds on the
 * way to FastAPI silently dropped it because neither named the field.
 *
 * The consequence was not a cosmetic one. `confirm_new_company` is the only
 * answer to the near-miss question that opens a SEPARATE application; without
 * it reaching the backend, "no — a different company" re-asks the same question
 * forever, and an employer one edit from one already on the board can never be
 * filed from the review queue at all. That is a worse outcome than the
 * duplicate row the check was written to prevent.
 *
 * Every field is omitted rather than sent null/false when absent, so the
 * backend's defaults stay distinguishable from a caller that answered "no".
 */
export function classifyBackendBody(args: ClassifyArgs): Record<string, unknown> {
  const named = args.company?.trim();
  return {
    category: args.category,
    ...(named ? { company: named } : {}),
    ...(args.applicationId !== undefined ? { application_id: args.applicationId } : {}),
    ...(args.message ? { message: args.message } : {}),
    ...(args.confirmNewCompany === true ? { confirm_new_company: true } : {}),
    ...(args.noneOfThese === true ? { none_of_these: true } : {}),
  };
}
