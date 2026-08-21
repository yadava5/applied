import { NextResponse, type NextRequest } from "next/server";

import { withServerTiming } from "@/lib/api/serverTiming";
import {
  deleteApplication,
  getApplicationDetail,
  updateApplicationStatus,
} from "@/lib/applications/server";

/**
 * Same-origin proxy for a single application: read its detail (click-through
 * mail), apply a user status correction (PATCH — sticky + trains), or delete it.
 * The Supabase JWT is attached server-side; every call is scoped to the
 * verified user on the backend (404 for anyone else's row).
 */
type Ctx = { params: Promise<{ id: string }> };

function badId() {
  return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
}

async function resolveId(params: Ctx["params"]): Promise<number | null> {
  const { id } = await params;
  const n = Number(id);
  // `isSafeInteger`, not `isInteger`. `Number("1e10")` and
  // `Number("99999999999999999999")` are both integral as far as `isInteger`
  // is concerned, so the old guard passed them through and the request
  // travelled to the backend carrying a value past `MAX_SAFE_INTEGER` and past
  // a Postgres bigint. Measured against the running proxy: `/1e10` and
  // `/99999999999999999999` both cleared the guard and reached auth (401),
  // while `/0`, `/-1`, `/1.5` and `/abc` were correctly refused with 400.
  // Nothing was scoped wrongly — the backend still 404s across users — but an
  // id this route cannot represent should not become the backend's problem.
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

export async function GET(_req: NextRequest, ctx: Ctx) {
  const id = await resolveId(ctx.params);
  if (id === null) return badId();
  const r = await getApplicationDetail(id);
  // The read #203 measured at 850 ms for 568 bytes — the one this instrument
  // was built for. `badId()` above returns before any of this, and correctly
  // carries no timing: nothing was measured.
  return withServerTiming(r.response, NextResponse.json(r.data ?? {}, { status: r.status }));
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const id = await resolveId(ctx.params);
  if (id === null) return badId();

  let body: { status?: unknown } = {};
  try {
    body = (await req.json()) as { status?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  const status = typeof body.status === "string" ? body.status.trim() : "";
  if (!status) return NextResponse.json({ detail: "status is required" }, { status: 422 });

  const r = await updateApplicationStatus(id, status);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}

export async function DELETE(_req: NextRequest, ctx: Ctx) {
  const id = await resolveId(ctx.params);
  if (id === null) return badId();
  const r = await deleteApplication(id);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
