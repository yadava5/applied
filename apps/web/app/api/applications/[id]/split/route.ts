import { NextResponse, type NextRequest } from "next/server";

import { splitApplication } from "@/lib/applications/server";

/**
 * Same-origin proxy for "this row is really N applications — split it".
 *
 * The migration path for a row filed before an application was identified by
 * employer AND role. The backend reads only what is already stored — every
 * contributing message kept its subject and snippet — so this needs no Gmail
 * call and no rebuild. That matters: a rebuild is the only other route, it
 * reads as destructive, and its bounded scan may not even reach the mail in
 * question.
 *
 * A **409 is the ordinary answer**, not a failure: it means this row's mail
 * describes a single application and there is nothing to offer. Callers must
 * render that as "nothing to split", never as an error.
 */
type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
  }
  const r = await splitApplication(n);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
