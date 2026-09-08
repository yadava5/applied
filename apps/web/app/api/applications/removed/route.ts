import { NextResponse, type NextRequest } from "next/server";

import { createServerApiClient } from "@/lib/api/server";
import { errorDetail } from "@/lib/applications/export";
import { clampPage, removedPageQuery } from "@/lib/applications/removed";

/**
 * Same-origin proxy for the list an undo surface reads: one page of the rows
 * that are OFF the board — the user's own removals and whatever a rebuild
 * purged — with the honest full count beside it.
 *
 * The endpoint has existed since removal stopped being a delete; the surface
 * that reads it did not, which is #921. `GET /applications` already answers
 * this question (`dismissed=true`) and `POST /applications/{id}/restore`
 * already reverses it, so nothing new happens on the wire here: this route is
 * the missing half-inch of plumbing between a browser and two endpoints it
 * could not reach, and it exists for the same reason every other proxy in this
 * folder does — the Supabase JWT and `BACKEND_API_URL` stay server-side.
 *
 * NOT the export route (`../route.ts`), which walks BOTH sets to build a
 * download and is explicitly documented as fanning out into a backend call per
 * page. One page, one call, one round trip: a reader who has just removed the
 * wrong row is waiting on this.
 *
 * The `removed` segment is static, so it wins over the sibling `[id]` dynamic
 * route the same way `mail`, `review` and `summary` already do; the id route
 * never sees this path and never has to parse the word as a number.
 *
 * `total` is the backend's full count under the same predicate, not the size
 * of this page — which is what lets the panel say "1–10 of 47" without a
 * second request, and what makes its pager honest on an account with many
 * removals.
 */
export async function GET(request: NextRequest) {
  // Clamped rather than validated: a bad `page` here is stale client state or
  // a hand-typed URL, and the backend answers `ge=1` violations with a 422
  // that a recovery surface would render as "your removed rows are gone".
  const page = clampPage(request.nextUrl.searchParams.get("page"));

  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET("/applications", {
      params: { query: removedPageQuery(page) },
    });
    if (error || !data) {
      return NextResponse.json(
        { detail: errorDetail(error, "Couldn't read your removed rows") },
        { status: response.status || 502 },
      );
    }
    return NextResponse.json(
      { applications: data.applications, total: data.total, page },
      { status: 200 },
    );
  } catch {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}
