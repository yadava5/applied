/**
 * Reading the classify proxy's request body.
 *
 * Extracted from `app/api/applications/review/[messageId]/classify/route.ts`
 * so it can actually be executed by a test. The handler REBUILDS the body
 * rather than forwarding it, which means every field it does not name is
 * silently lost — that is how `confidence` died in the inbox relay and how
 * `applied_date` and `url` died on create. The same shape of loss here is not
 * a no-op: dropping `application_id` makes the backend fall back to the
 * employer's first row, which is precisely the arbitrary-sibling filing the
 * identity work exists to stop. So the parse is worth pinning on its own.
 *
 * Dependency-free so `tests/unit/` can load it under Node's type stripping.
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
  };

  const category = typeof body.category === "string" ? body.category.trim() : "";
  if (!category) return { ok: false, status: 422, detail: "category is required" };

  const company = typeof body.company === "string" ? body.company.trim() : "";
  const applicationId =
    typeof body.application_id === "number" && Number.isInteger(body.application_id)
      ? body.application_id
      : undefined;
  const message = readClassifyMessage(body.message);

  return {
    ok: true,
    category,
    ...(company ? { company } : {}),
    ...(applicationId !== undefined ? { applicationId } : {}),
    ...(message !== undefined ? { message } : {}),
  };
}
