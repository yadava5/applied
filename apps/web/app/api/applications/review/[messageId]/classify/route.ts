import { NextResponse, type NextRequest } from "next/server";

import { classifyReviewItem } from "@/lib/applications/server";

/**
 * Same-origin proxy for classifying a review-queue item into a category. A
 * lifecycle category with a nameable employer becomes a sticky, user-owned
 * application; every choice records a training example. User-scoped on the
 * backend.
 *
 * The optional `company` is forwarded so the client can answer a
 * `needs_employer: true` response with the name the pipeline couldn't extract.
 * `application_id` is forwarded for the same reason: it is the user's answer to
 * "which of these is it about?" when an employer holds several applications.
 * Dropping it here is not a no-op — the backend falls back to picking the
 * employer's first row, which is exactly the arbitrary-sibling filing that
 * `_pick_application` was written to stop. This handler REBUILDS the body
 * rather than forwarding it, so every field it does not name is silently lost;
 * that is how `confidence` died in the inbox relay and how `applied_date` and
 * `url` died on create.
 * The backend's body is passed through UNRESHAPED — `needs_employer`,
 * `message_id` and `detail` are what tell the caller whether anything was
 * actually filed, and narrowing them away here would recreate the bug the flag
 * exists to close.
 */
type Ctx = { params: Promise<{ messageId: string }> };

export async function POST(req: NextRequest, ctx: Ctx) {
  const { messageId } = await ctx.params;
  if (!messageId) {
    return NextResponse.json({ detail: "Invalid message id" }, { status: 400 });
  }

  let body: { category?: unknown; company?: unknown; application_id?: unknown } = {};
  try {
    body = (await req.json()) as {
      category?: unknown;
      company?: unknown;
      application_id?: unknown;
    };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  const category = typeof body.category === "string" ? body.category.trim() : "";
  if (!category) return NextResponse.json({ detail: "category is required" }, { status: 422 });
  const company = typeof body.company === "string" ? body.company.trim() : "";
  const applicationId =
    typeof body.application_id === "number" && Number.isInteger(body.application_id)
      ? body.application_id
      : undefined;

  const r = await classifyReviewItem(
    messageId,
    category,
    company || undefined,
    applicationId,
  );
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
