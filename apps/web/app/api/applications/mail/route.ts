import { NextResponse, type NextRequest } from "next/server";

import { withServerTiming } from "@/lib/api/serverTiming";
import { getMail } from "@/lib/applications/server";

/**
 * Same-origin proxy for the full mail listing — every message the sync stored,
 * whatever the classifier decided and whether or not it has been reviewed.
 *
 * The Supabase JWT is attached server-side; the listing is user-scoped. Only
 * `page`, `page_size`, `category` and `q` are forwarded (see `getMail`), and
 * the backend validates them, so a bad value comes back as its own 422 rather
 * than being silently dropped here.
 *
 * This is the read `/applications/review` never was: that queue hides a verdict
 * as soon as it is reviewed or filed, which left corrected-once messages
 * unreachable from every screen in the product even though the correction
 * endpoint would still accept them.
 */
export async function GET(request: NextRequest) {
  const r = await getMail(new URL(request.url).searchParams);
  return withServerTiming(r.response, NextResponse.json(r.data ?? {}, { status: r.status }));
}
