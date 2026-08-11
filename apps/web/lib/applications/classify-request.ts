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

export type ClassifyRequest =
  | { ok: true; category: string; company?: string; applicationId?: number }
  | { ok: false; status: number; detail: string };

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
  };

  const category = typeof body.category === "string" ? body.category.trim() : "";
  if (!category) return { ok: false, status: 422, detail: "category is required" };

  const company = typeof body.company === "string" ? body.company.trim() : "";
  const applicationId =
    typeof body.application_id === "number" && Number.isInteger(body.application_id)
      ? body.application_id
      : undefined;

  return {
    ok: true,
    category,
    ...(company ? { company } : {}),
    ...(applicationId !== undefined ? { applicationId } : {}),
  };
}
