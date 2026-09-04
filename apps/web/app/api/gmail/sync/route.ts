import { NextResponse, type NextRequest } from "next/server";

import { syncGmailPipeline } from "@/lib/gmail/server";

/**
 * Same-origin proxy that persists the classified pipeline into Application
 * rows. The client posts either `{ items }` (the mined verdict set) or `{}`
 * (let the backend fetch a bounded recent page). This handler forwards to the
 * backend `/gmail/sync` with the cookie JWT, so the token stays server-side and
 * every row is scoped to the verified user. The upsert is idempotent on the
 * backend — re-posting never duplicates.
 */
export async function POST(request: NextRequest) {
  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const result = await syncGmailPipeline(body);

  switch (result.kind) {
    case "ok":
      return NextResponse.json(result.result, { status: 200 });
    case "not_connected":
      return NextResponse.json({ detail: "not_connected" }, { status: 409 });
    case "unauthenticated":
      return NextResponse.json({ detail: "unauthenticated" }, { status: 401 });
    case "auth":
      return NextResponse.json({ detail: "auth" }, { status: result.status });
    case "rate_limited":
      // Passed through with the wait intact, NOT flattened into a 5xx. The
      // client loop reads this to pause and resume from the page cursor it
      // already holds, so a deferred read costs a wait rather than the whole
      // scan.
      return NextResponse.json(
        { detail: "rate_limited" },
        {
          status: 429,
          headers: { "Retry-After": String(result.retryAfterSeconds) },
        },
      );
    case "unavailable":
      return NextResponse.json({ detail: "unavailable" }, { status: 503 });
    default:
      return NextResponse.json(
        { detail: result.message },
        { status: result.status ?? 502 },
      );
  }
}
