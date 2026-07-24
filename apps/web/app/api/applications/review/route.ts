import { NextResponse } from "next/server";

import { getReviewQueue } from "@/lib/applications/server";

/**
 * Same-origin proxy for the needs-classification queue — the uncertain verdicts
 * (0.70–0.85 band / unknown employer) the sync flagged for a human decision.
 * The Supabase JWT is attached server-side; the queue is user-scoped.
 */
export async function GET() {
  const r = await getReviewQueue();
  return NextResponse.json(r.data ?? {}, { status: r.status });
}
