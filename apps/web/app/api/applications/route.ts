import { NextResponse } from "next/server";
import { createServerApiClient } from "@/lib/api/server";
import { buildExportPages, collectMail } from "@/lib/applications/export";
import { APPLICATION_STATUSES, isApplicationStatus } from "@/lib/dashboard/status";

/**
 * Server-side proxy behind the Settings "export your data" action. Forwards to
 * the backend with the caller's Supabase JWT (from cookies) so the token and
 * `BACKEND_API_URL` never reach the browser, and returns the JSON the client
 * turns into a download.
 *
 * PAGINATED, because the export claims to be everything. This used to make one
 * unparameterised call, which the backend answers with its DEFAULT_PAGE_SIZE of
 * 100 — so a user with 250 applications silently got 100 of them, a
 * data-loss-shaped defect in the one feature whose entire job is handing the
 * user their data back. It never fired here because this account has 25.
 *
 * TWO application passes and a mail pass (#217). `GET /applications` filters
 * `dismissed_at` exclusively and defaults to the live board, so the removed —
 * restorable, and deleted by `DELETE /account` along with everything else —
 * rows were absent from the export entirely. `GET /applications/mail` is the
 * parsed content of the user's own mail, metadata only: the cloud sync never
 * fetches a body, so there is no message text to leak into a downloaded file.
 *
 * What is deliberately NOT here: `user_credentials` (the Google OAuth
 * material — writing that into the browser's Downloads folder would be a worse
 * defect than the one this fixes), `email_embeddings` and `sync_state` (a
 * vector table and a Gmail history cursor, not user-legible), and
 * `training_data` (derived classifier state). `contacts` and `interviews` have
 * no cloud read endpoint at all — nothing in `main_cloud`'s schema exposes
 * them, and the cloud pipeline never writes them.
 *
 * The loops live in `lib/applications/export.ts` as pure functions over a
 * page-fetcher, so they can be executed by a test. Inline here they needed the
 * Next runtime and a Supabase cookie jar, which is why the original shipped
 * covered by types and review only.
 *
 * The one read-path proxy that does NOT pass the backend's `Server-Timing`
 * through (#269): it fans out into a backend call per page, and one header
 * cannot describe N round trips — whichever page's numbers were copied, the
 * name `app;dur` would claim to be the cost of this request and not be.
 */
export async function GET() {
  try {
    const api = await createServerApiClient();

    const rows = await buildExportPages(async (page, pageSize, dismissed) => {
      const res = await api.GET("/applications", {
        params: { query: { page, page_size: pageSize, dismissed } },
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

    if (!rows.ok) {
      return NextResponse.json({ detail: rows.detail }, { status: rows.status });
    }

    const mail = await collectMail(async (page, pageSize) => {
      const res = await api.GET("/applications/mail", {
        params: { query: { page, page_size: pageSize } },
      });
      if (res.error || !res.data) {
        return {
          ok: false as const,
          status: res.response.status || 502,
          detail: String(res.error ?? `Export failed while reading mail page ${page}`),
        };
      }
      return {
        ok: true as const,
        page: { messages: res.data.messages, total: res.data.total },
      };
    });

    if (!mail.ok) {
      return NextResponse.json({ detail: mail.detail }, { status: mail.status });
    }

    // `total` is now a sum across two disjoint queries, so it is reported WITH
    // its two halves rather than alone: a bare count that no longer means "the
    // backend says there are this many" is a field a reader will misread, and
    // both numbers were already computed. The downloaded file derives its own
    // counts from the rows (`buildExportFile`) and does not read these.
    return NextResponse.json(
      {
        applications: rows.applications,
        messages: mail.messages,
        total: rows.total,
        live: rows.live,
        removed: rows.removed,
        mail_total: mail.total,
      },
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
/**
 * Read one optional text field off a parsed JSON body.
 *
 * `payload` is typed for the caller's convenience, but its values arrive from
 * the wire: the annotation is a claim about the happy path, not a guarantee.
 * `payload.notes?.trim()` therefore throws on `{"notes": 1}`, and every such
 * read in this handler sat inside the try whose catch reports 502 "Backend
 * unreachable" — so a local TypeError was shown to the user as a healthy
 * backend being down.
 */
function optionalText(value: unknown): string | null {
  return typeof value === "string" ? value.trim() || null : null;
}

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

  // `typeof === "string"` rather than `payload.company?.trim()`.
  //
  // The declared type is a lie the wire can tell: `payload` is whatever JSON
  // arrived, so `{"company": 1}` gives a number, `.trim` is undefined, and the
  // call threw. These two reads sit OUTSIDE the try above, so the throw
  // escaped the handler entirely and Next answered 500. Measured against the
  // running route: `{"company":1,"position":1}` and
  // `{"company":true,"position":"Eng"}` both returned 500, where every other
  // body-taking route in this app answers 422 for a bad body.
  //
  // The sibling fields are worse rather than better: `notes` and `url` throw
  // the same TypeError from INSIDE the try, and the catch-all reports it as
  // 502 "Backend unreachable" — a local type error blamed on a healthy
  // backend. Reading the fields defensively is what fixes both shapes.
  const company = typeof payload.company === "string" ? payload.company.trim() : "";
  const position = typeof payload.position === "string" ? payload.position.trim() : "";
  if (!company || !position) {
    return NextResponse.json({ detail: "company and position are required" }, { status: 422 });
  }

  // `status` is an ENUM on the wire (`ApplicationStatus`), not a free string.
  // This proxy used to forward whatever the browser sent, so an unknown value
  // travelled all the way to the backend and came back as a raw pydantic 422
  // that the form showed verbatim. Rejecting it here says the same thing in
  // this app's words, and — now that the schema is generated — the compiler
  // is what forces the check to exist at all.
  const status = (typeof payload.status === "string" ? payload.status.trim() : "") || "applied";
  if (!isApplicationStatus(status)) {
    return NextResponse.json(
      { detail: `status must be one of: ${APPLICATION_STATUSES.join(", ")}` },
      { status: 422 },
    );
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
        status,
        // Same reason as `company`/`position` above: these are wire values,
        // not the declared type. `{"notes": 1}` used to throw here, inside the
        // try, and come back to the user as 502 "Backend unreachable".
        notes: optionalText(payload.notes),
        applied_date: optionalText(payload.applied_date),
        url: optionalText(payload.url),
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
