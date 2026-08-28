import { NextResponse, type NextRequest } from "next/server";

import { readClassifyBody } from "@/lib/applications/classify-request";
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
 * `confirm_new_company` is forwarded because it is the ONLY way to answer the
 * backend's near-miss question with "no, a different company" — dropped, that
 * button re-asks forever and an employer one edit from one already on the board
 * can never be filed. It was in fact dropped, on this hop and the next, from
 * the day the question shipped (#181/#167).
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

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  // The narrowing lives in `lib/applications/classify-request.ts` so a test can
  // execute it — in here it needed the Next runtime and was covered by types
  // and review only, which is exactly how a dropped field goes unnoticed.
  const parsed = readClassifyBody(raw);
  if (!parsed.ok) {
    return NextResponse.json({ detail: parsed.detail }, { status: parsed.status });
  }

  // Forwarded as ONE value, deliberately. Named positional arguments are how
  // `confidence` died in the inbox relay and how `applied_date` and `url` died
  // on create — and the newest field here, `message`, is what lets a live-scan
  // correction land at all (its rows are verdicts about mail the backend has
  // never stored, so without it every one of them is a 404). Passing the parse
  // result whole means a field cannot be lost HERE.
  //
  // It was written as "can only be lost in `readClassifyBody`", and that is
  // more than this line earns. Below it sit `classifyReviewItem`'s call to
  // `classifyBackendBody` and, past the wire, FastAPI's own re-spread of the
  // parsed body into arguments — five rebuilds in all, of which the unit tests
  // execute two. Deleting one argument from that last re-spread left every
  // frontend and backend unit test green while the field stopped arriving;
  // `backend/tests/test_gmail_oauth_cloud.py` now covers it over HTTP for the
  // two fields the review picker sends, and the rest of that seam is still
  // carried by types and review.
  const r = await classifyReviewItem(messageId, parsed);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
