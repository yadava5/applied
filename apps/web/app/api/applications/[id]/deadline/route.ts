import { NextResponse, type NextRequest } from "next/server";

import { setApplicationDeadline } from "@/lib/applications/server";

/**
 * Same-origin proxy for "this is due at X" — and for clearing it.
 *
 * `due_at: null` clears. Set and clear are deliberately the same call: they are
 * one decision, and splitting them is how a UI ends up offering the first
 * without the second.
 *
 * The body is validated here rather than forwarded blind, because a malformed
 * date reaching the backend would 422 with a message written for an API client
 * rather than for someone who mistyped a date.
 */
type Ctx = { params: Promise<{ id: string }> };

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
  }

  let body: { due_at?: unknown } = {};
  try {
    body = (await req.json()) as { due_at?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const raw = body.due_at;
  if (raw !== null && typeof raw !== "string") {
    return NextResponse.json(
      { detail: "due_at must be an ISO-8601 date string, or null to clear it" },
      { status: 422 },
    );
  }
  if (typeof raw === "string" && Number.isNaN(Date.parse(raw))) {
    return NextResponse.json(
      { detail: `Could not read "${raw}" as a date` },
      { status: 422 },
    );
  }

  const r = await setApplicationDeadline(n, raw ?? null);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
