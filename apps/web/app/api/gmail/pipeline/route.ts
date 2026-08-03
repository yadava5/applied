import { NextResponse, type NextRequest } from "next/server";

import { analyzeGmailPipeline } from "@/lib/gmail/server";

/**
 * Same-origin proxy for the pipeline analysis (category summary + follow-ups).
 *
 * Once the client has paged the whole mine, it posts the accumulated verdict
 * metadata here; this handler forwards it to the backend with the caller's
 * Supabase JWT so the analysis runs server-side over the full set (which no
 * single page can compute). No Gmail call, no bodies — just aggregation.
 */
export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const items =
    body && typeof body === "object" && Array.isArray((body as { items?: unknown }).items)
      ? (body as { items: unknown[] }).items
      : [];

  const result = await analyzeGmailPipeline(items);

  switch (result.kind) {
    case "ok":
      return NextResponse.json(result.analysis, { status: 200 });
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
