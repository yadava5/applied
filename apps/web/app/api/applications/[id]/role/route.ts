import { NextResponse, type NextRequest } from "next/server";

import { setApplicationRole } from "@/lib/applications/server";
import { MAX_ROLE_LENGTH, normalizeRoleDraft } from "@/lib/dashboard/role";

/**
 * Same-origin proxy for "the role is X" — and for taking it back.
 *
 * Issue #72. The Gmail path is metadata-only and the ATS acknowledgement
 * subjects it reads name the employer, never the job, so `position` is `""` on
 * every auto-filed row and no extraction work reaches it. A human typing it is
 * the only source there will ever be.
 *
 * `role: null`, or a string that is only whitespace, CLEARS. Set and clear are
 * deliberately the same call, as they are for the deadline — and more sharply
 * so here, because a saved title makes the field the user's and the sync may no
 * longer correct a typo in it. Without a clear, one stands forever.
 *
 * Normalising here rather than forwarding blind is what stops `"   "` from
 * being stored as a role that renders as present. That is precisely the
 * invented data #72 exists to prevent, and it would arrive looking like a real
 * answer. The backend applies the identical rule; this one keeps a UI mistake
 * from ever becoming a request.
 */
type Ctx = { params: Promise<{ id: string }> };

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ detail: "Invalid application id" }, { status: 400 });
  }

  let body: { role?: unknown } = {};
  try {
    body = (await req.json()) as { role?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const raw = body.role;
  if (raw !== null && raw !== undefined && typeof raw !== "string") {
    return NextResponse.json(
      { detail: "role must be a string, or null to clear it" },
      { status: 422 },
    );
  }

  const role = typeof raw === "string" ? normalizeRoleDraft(raw) : null;
  if (role !== null && role.length > MAX_ROLE_LENGTH) {
    return NextResponse.json(
      { detail: `A role is at most ${MAX_ROLE_LENGTH} characters.` },
      { status: 422 },
    );
  }

  const r = await setApplicationRole(n, role);
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
