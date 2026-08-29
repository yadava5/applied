import { NextResponse } from "next/server";

import { createServerApiClient } from "@/lib/api/server";
import { withServerTiming } from "@/lib/api/serverTiming";

/**
 * Same-origin proxy for the counts-only pipeline summary.
 *
 * The dashboard's own render fetches this endpoint server-side and never needs
 * a proxy. This route exists for ONE call: the header's this-week correction
 * (#518). The server counts "this week" from a UTC Monday because at first
 * paint it does not know the reader's zone; once the browser has hydrated it
 * knows, and re-asks with `?week_start=<its own Monday>` so the header stops
 * disagreeing with the momentum caption beside it for the width of the
 * reader's UTC offset every Sunday night.
 *
 * The JWT is attached here, server-side, exactly as every other handler in
 * this directory does it — the browser learns neither the token nor
 * `BACKEND_API_URL`.
 *
 * `week_start` is FORWARDED, NOT VALIDATED HERE. The backend is the only place
 * that can check it, because the check is against the server's own clock
 * (`_reader_week_start` in `backend/jobtracker/cloud/applications.py`: a
 * Monday, `YYYY-MM-DD`, within seven days of the server's own). A second
 * partial copy of that rule in this file would be one more thing to drift; an
 * absent parameter is simply omitted, which is the un-corrected UTC answer.
 * A rejection comes back as the backend's 422 and the caller keeps the number
 * already on screen.
 */
export async function GET(request: Request) {
  const weekStart = new URL(request.url).searchParams.get("week_start");

  try {
    const api = await createServerApiClient();
    const res = await api.GET("/applications/summary", {
      params: { query: weekStart === null ? {} : { week_start: weekStart } },
    });

    if (res.error || !res.data) {
      return withServerTiming(
        res.response,
        NextResponse.json(
          { detail: res.error ?? "Backend rejected the request" },
          { status: res.response.status || 502 },
        ),
      );
    }
    return withServerTiming(res.response, NextResponse.json(res.data, { status: 200 }));
  } catch {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}
