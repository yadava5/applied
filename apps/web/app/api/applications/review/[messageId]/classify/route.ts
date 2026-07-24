import { NextResponse, type NextRequest } from "next/server";

import { classifyReviewItem } from "@/lib/applications/server";

/**
 * Same-origin proxy for classifying a review-queue item into a category. A
 * lifecycle category with a nameable employer becomes a sticky, user-owned
 * application; every choice records a training example. User-scoped on the
 * backend.
 */
type Ctx = { params: Promise<{ messageId: string }> };

export async function POST(req: NextRequest, ctx: Ctx) {
  const { messageId } = await ctx.params;
  if (!messageId) {
    return NextResponse.json({ detail: "Invalid message id" }, { status: 400 });
  }

  let body: { category?: unknown } = {};
  try {
    body = (await req.json()) as { category?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  const category = typeof body.category === "string" ? body.category.trim() : "";
  if (!category) return NextResponse.json({ detail: "category is required" }, { status: 422 });

  const r = await classifyReviewItem(messageId, category);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
