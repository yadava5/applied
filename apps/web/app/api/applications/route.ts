import { NextResponse } from "next/server";
import { createServerApiClient } from "@/lib/api/server";

/**
 * Server-side proxy for listing applications — used by the Settings "export
 * your data" action. Forwards to the backend with the caller's Supabase JWT
 * (from cookies) so the token and `BACKEND_API_URL` never reach the browser,
 * and returns the raw list JSON the client turns into a download.
 */
/** The backend's own ceiling (`MAX_PAGE_SIZE`); asking for more is a 422. */
const EXPORT_PAGE_SIZE = 500;
/** Bounds the loop so a bad `total` can never spin it forever. 50k rows. */
const EXPORT_MAX_PAGES = 100;

export async function GET() {
  try {
    const api = await createServerApiClient();

    // PAGINATED, because the export claims to be everything.
    //
    // This used to make one unparameterised call, which the backend answers with
    // its DEFAULT_PAGE_SIZE of 100. Settings offers to "export everything Applied
    // holds for you" and a user with 250 applications silently got 100 of them —
    // a data-loss-shaped defect in the one feature whose entire job is to hand
    // the user their data back. It never fired here because this account has 25.
    const first = await api.GET("/applications", {
      params: { query: { page: 1, page_size: EXPORT_PAGE_SIZE } },
    });
    if (first.error || !first.data) {
      return NextResponse.json(
        { detail: first.error ?? "Backend rejected the request" },
        { status: first.response.status || 502 },
      );
    }

    const applications = [...first.data.applications];
    const total = first.data.total;

    for (let page = 2; applications.length < total && page <= EXPORT_MAX_PAGES; page += 1) {
      const next = await api.GET("/applications", {
        params: { query: { page, page_size: EXPORT_PAGE_SIZE } },
      });
      // A mid-export failure must not hand back a short file that looks whole.
      if (next.error || !next.data) {
        return NextResponse.json(
          { detail: next.error ?? `Export failed while reading page ${page}` },
          { status: next.response.status || 502 },
        );
      }
      if (next.data.applications.length === 0) break; // defensive: no progress
      applications.push(...next.data.applications);
    }

    return NextResponse.json({ applications, total }, { status: 200 });
  } catch {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}

/**
 * Server-side proxy for creating applications. The browser posts here;
 * this handler forwards to the FastAPI backend with the Supabase access
 * token from cookies. Keeps `BACKEND_API_URL` and the JWT entirely
 * server-side — the client never learns either.
 */
export async function POST(request: Request) {
  let payload: {
    company?: string;
    position?: string;
    status?: string;
    notes?: string;
    applied_date?: string;
    url?: string;
  };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const company = payload.company?.trim();
  const position = payload.position?.trim();
  if (!company || !position) {
    return NextResponse.json({ detail: "company and position are required" }, { status: 422 });
  }

  try {
    const api = await createServerApiClient();
    // This handler REBUILDS the body rather than forwarding it, so any field it
    // does not name is silently dropped. That is how the inbox relay lost
    // `confidence` and persisted nothing for weeks — name every field the
    // backend accepts, or it does not arrive.
    const { data, error, response } = await api.POST("/applications", {
      body: {
        company,
        position,
        status: payload.status ?? "applied",
        notes: payload.notes?.trim() || null,
        applied_date: payload.applied_date?.trim() || null,
        url: payload.url?.trim() || null,
      },
    });
    if (error || !data) {
      return NextResponse.json(
        { detail: error ?? "Backend rejected the request" },
        { status: response.status || 502 },
      );
    }
    return NextResponse.json(data, { status: 201 });
  } catch {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}
