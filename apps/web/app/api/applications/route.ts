import { NextResponse } from "next/server";
import { createServerApiClient } from "@/lib/api/server";
import { collectApplications } from "@/lib/applications/export";

/**
 * Server-side proxy for listing applications — used by the Settings "export
 * your data" action. Forwards to the backend with the caller's Supabase JWT
 * (from cookies) so the token and `BACKEND_API_URL` never reach the browser,
 * and returns the raw list JSON the client turns into a download.
 *
 * PAGINATED, because the export claims to be everything. This used to make one
 * unparameterised call, which the backend answers with its DEFAULT_PAGE_SIZE of
 * 100 — so a user with 250 applications silently got 100 of them, a
 * data-loss-shaped defect in the one feature whose entire job is handing the
 * user their data back. It never fired here because this account has 25.
 *
 * The loop itself lives in `lib/applications/export.ts` as a pure function over
 * a page-fetcher, so it can be executed by a test. Inline here it needed the
 * Next runtime and a Supabase cookie jar, which is why it shipped covered by
 * types and review only.
 */
export async function GET() {
  try {
    const api = await createServerApiClient();

    const result = await collectApplications(async (page, pageSize) => {
      const res = await api.GET("/applications", {
        params: { query: { page, page_size: pageSize } },
      });
      if (res.error || !res.data) {
        return {
          ok: false as const,
          status: res.response.status || 502,
          detail: String(res.error ?? `Export failed while reading page ${page}`),
        };
      }
      return {
        ok: true as const,
        page: { applications: res.data.applications, total: res.data.total },
      };
    });

    if (!result.ok) {
      return NextResponse.json({ detail: result.detail }, { status: result.status });
    }
    return NextResponse.json(
      { applications: result.applications, total: result.total },
      { status: 200 },
    );
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
