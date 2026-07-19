import { NextResponse } from "next/server";
import { createServerApiClient } from "@/lib/api/server";

/**
 * Server-side proxy for listing applications — used by the Settings "export
 * your data" action. Forwards to the backend with the caller's Supabase JWT
 * (from cookies) so the token and `BACKEND_API_URL` never reach the browser,
 * and returns the raw list JSON the client turns into a download.
 */
export async function GET() {
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET("/applications");
    if (error || !data) {
      return NextResponse.json(
        { detail: error ?? "Backend rejected the request" },
        { status: response.status || 502 },
      );
    }
    return NextResponse.json(data, { status: 200 });
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
  let payload: { company?: string; position?: string; status?: string; notes?: string };
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
    const { data, error, response } = await api.POST("/applications", {
      body: {
        company,
        position,
        status: payload.status ?? "applied",
        notes: payload.notes?.trim() || null,
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
