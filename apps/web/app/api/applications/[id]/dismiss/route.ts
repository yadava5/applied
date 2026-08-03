import { NextResponse, type NextRequest } from "next/server";

import { dismissApplication } from "@/lib/applications/server";

/**
 * Same-origin proxy for "not an application / dismiss": removes the row and
 * records it as an `other` training example (teaching the classifier it was
 * misfiled). Scoped to the verified user on the backend.
 */
type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
  }
  const r = await dismissApplication(n);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
