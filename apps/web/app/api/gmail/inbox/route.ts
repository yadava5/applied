import { NextResponse, type NextRequest } from "next/server";

import { withServerTiming } from "@/lib/api/serverTiming";
import { fetchGmailInboxPage } from "@/lib/gmail/server";

/**
 * Same-origin proxy for one page of the classified inbox mine.
 *
 * The client workbench calls `/api/gmail/inbox?count=…&range=…&scope=…&
 * page_size=…&page_token=…` and loops until it reaches the chosen count. This
 * handler forwards the query to the FastAPI backend carrying the caller's
 * Supabase JWT (from cookies), so the token and `BACKEND_API_URL` never reach
 * the browser. Failure causes are surfaced with honest status codes the client
 * maps to its own reconnect / retry states.
 */
export async function GET(request: NextRequest) {
  const search = new URL(request.url).searchParams.toString();
  const result = await fetchGmailInboxPage(search);

  switch (result.kind) {
    case "ok":
      // Only the success branch carries timing. The failures below are either
      // decided before the fetch (`unauthenticated`) or re-labelled from a
      // status the helper kept nothing else from — there is no backend
      // response left to copy, and inventing one would misreport.
      return withServerTiming(result.response, NextResponse.json(result.page, { status: 200 }));
    case "not_connected":
      return NextResponse.json({ detail: "not_connected" }, { status: 409 });
    case "unauthenticated":
      return NextResponse.json({ detail: "unauthenticated" }, { status: 401 });
    case "auth":
      return NextResponse.json({ detail: "auth" }, { status: result.status });
    case "unavailable":
      return NextResponse.json({ detail: "unavailable" }, { status: 503 });
    default:
      return NextResponse.json(
        { detail: result.message },
        { status: result.status ?? 502 },
      );
  }
}
