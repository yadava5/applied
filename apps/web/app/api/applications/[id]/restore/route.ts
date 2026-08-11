import { NextResponse, type NextRequest } from "next/server";

import { restoreApplication } from "@/lib/applications/server";

/**
 * Same-origin proxy for "undo a removal": puts back a row that was dismissed,
 * either by the user or by a re-sync. Scoped to the verified user on the
 * backend, so one account can never restore another's row.
 *
 * This exists so that no removal in the product has to be final. A dismissal
 * keeps the row and its emails on disk precisely so this can reverse it, which
 * is what lets the UI offer undo instead of stopping the user with a dialog.
 */
type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
  }
  const r = await restoreApplication(n);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
