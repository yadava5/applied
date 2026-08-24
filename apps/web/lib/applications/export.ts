/**
 * The export: what it asks the backend for, how it pages, and the file it
 * builds — all as pure functions, over a page-fetcher and over the rows.
 *
 * They live here rather than inline in `app/api/applications/route.ts` and
 * `components/settings/DataSection.tsx` for one reason: in either place they
 * could not be executed by a test. The route needs the Next runtime and a
 * Supabase cookie jar, and the section needs a browser, so the code deciding
 * whether a user gets all of their data or a quietly partial file was covered
 * by types and review only. A short answer in the one feature whose whole job
 * is handing the user their data back is a data-loss-shaped defect.
 *
 * Dependency-free on purpose (no React, no `@/` alias, no generated schema) so
 * `tests/unit/` can load it directly under Node's type stripping — the same
 * rule as `detail.ts`, `review.ts` and `sync-plan.ts`.
 */

/** The backend's own ceiling (`MAX_PAGE_SIZE`); asking for more is a 422. */
export const EXPORT_PAGE_SIZE = 500;

/** Bounds the loop so a bad `total` can never spin it forever. 50k rows. */
export const EXPORT_MAX_PAGES = 100;

/** One page as the backend answers it. */
export interface ApplicationsPage {
  applications: unknown[];
  total: number;
}

/** One page of the mail listing, as `GET /applications/mail` answers it. */
export interface MailPage {
  messages: unknown[];
  total: number;
}

/** What a fetcher returns: the page, or a failure the export must not paper over. */
export type PageResult =
  | { ok: true; page: ApplicationsPage }
  | { ok: false; status: number; detail: string };

/** The same contract for the mail listing. */
export type MailPageResult =
  | { ok: true; page: MailPage }
  | { ok: false; status: number; detail: string };

export type ExportResult =
  | { ok: true; applications: unknown[]; total: number; pagesRead: number }
  | { ok: false; status: number; detail: string };

/** Both application passes, merged. `live`/`removed` are the two backend totals. */
export type ExportPagesResult =
  | {
      ok: true;
      applications: unknown[];
      live: number;
      removed: number;
      total: number;
      pagesRead: number;
    }
  | { ok: false; status: number; detail: string };

export type MailResult =
  | { ok: true; messages: unknown[]; total: number; pagesRead: number }
  | { ok: false; status: number; detail: string };

/**
 * Read every page and return the whole list, or fail loudly.
 *
 * Three refusals are the point, and each one is a way a user could otherwise be
 * handed a short file that looks complete:
 *
 *  1. A mid-export page failure aborts. Returning what was collected so far
 *     would produce a plausible-looking export missing an arbitrary tail.
 *  2. A page that comes back empty while `total` still claims more stops the
 *     loop instead of spinning — no progress means the backend disagrees with
 *     its own count, and looping cannot fix that.
 *  3. `EXPORT_MAX_PAGES` bounds the whole thing, so a corrupt `total` cannot
 *     hang the request forever.
 */
export async function collectApplications(
  fetchPage: (page: number, pageSize: number) => Promise<PageResult>,
): Promise<ExportResult> {
  const first = await fetchPage(1, EXPORT_PAGE_SIZE);
  if (!first.ok) return first;

  const applications = [...first.page.applications];
  const total = first.page.total;
  let pagesRead = 1;

  for (let page = 2; applications.length < total && page <= EXPORT_MAX_PAGES; page += 1) {
    const next = await fetchPage(page, EXPORT_PAGE_SIZE);
    if (!next.ok) return next;
    pagesRead += 1;
    if (next.page.applications.length === 0) break;
    applications.push(...next.page.applications);
  }

  return { ok: true, applications, total, pagesRead };
}

/**
 * Both application passes: the live board, then the removed rows.
 *
 * `GET /applications` answers ONE of the two sets per call — `dismissed`
 * defaults to `false`, and the filter is exclusive
 * (`dismissed_at IS NULL` / `IS NOT NULL`), so a single unparameterised pass
 * cannot return a removed row no matter how it is paged. The export made only
 * that pass, which is why removing an application also removed it from the
 * user's copy of their own data — while `DELETE /account` deletes every
 * `Application` row regardless of `dismissed_at`. Export, then delete, and the
 * dismissed rows were gone with nothing to restore them from.
 *
 * A removed row is not a deleted one: it carries `dismissed_at` (and usually a
 * `dismissed_reason`), `POST /applications/{id}/restore` brings it back, and
 * the two sets are concatenated rather than tagged here — the field the
 * backend already sends is what tells them apart, in the file and in the API.
 *
 * A failure in EITHER pass fails the whole export, for the same reason
 * `collectApplications` aborts mid-loop: half an export with a 200 on it is
 * worse than a refusal, because it looks complete.
 */
export async function buildExportPages(
  fetchPage: (page: number, pageSize: number, dismissed: boolean) => Promise<PageResult>,
): Promise<ExportPagesResult> {
  const liveRows = await collectApplications((page, pageSize) => fetchPage(page, pageSize, false));
  if (!liveRows.ok) return liveRows;

  const removedRows = await collectApplications((page, pageSize) => fetchPage(page, pageSize, true));
  if (!removedRows.ok) return removedRows;

  return {
    ok: true,
    applications: [...liveRows.applications, ...removedRows.applications],
    live: liveRows.total,
    removed: removedRows.total,
    total: liveRows.total + removedRows.total,
    pagesRead: liveRows.pagesRead + removedRows.pagesRead,
  };
}

/**
 * Every stored message, paged by the same loop and its same three refusals.
 *
 * `GET /applications/mail` is metadata only by construction — `MailMessageResponse`
 * has no field for a body, and none is stored for it to carry — so this adds
 * the parsed mail the product is about without putting message content into a
 * file in the user's Downloads folder.
 *
 * The reason changed even though the guarantee did not. The sync now DOES
 * fetch bodies, to classify on; it discards them rather than storing them
 * (`backend/jobtracker/cloud/gmail_client.py`, and
 * `backend/tests/test_body_is_never_persisted.py` which fails if one is kept).
 * So an export still cannot leak a body — but because nothing retains one,
 * not because nothing reads one.
 */
export async function collectMail(
  fetchPage: (page: number, pageSize: number) => Promise<MailPageResult>,
): Promise<MailResult> {
  const run = await collectApplications(async (page, pageSize) => {
    const result = await fetchPage(page, pageSize);
    if (!result.ok) return result;
    return { ok: true as const, page: { applications: result.page.messages, total: result.page.total } };
  });
  if (!run.ok) return run;
  return { ok: true, messages: run.applications, total: run.total, pagesRead: run.pagesRead };
}

/** A row the backend has marked as removed. Only `dismissed_at` is read. */
function isRemoved(row: unknown): boolean {
  return (
    typeof row === "object" &&
    row !== null &&
    "dismissed_at" in row &&
    (row as { dismissed_at?: unknown }).dismissed_at != null
  );
}

/**
 * The downloaded file, envelope and all.
 *
 * It lives here — not in the section that triggers the download, and not in
 * the route — because BOTH the live export and the `/demo/settings` twin have
 * to produce the same file shape. Build it in the route and the twin's
 * download (the only one an e2e without a Supabase session can capture) would
 * certify a shape production never emits.
 *
 * The envelope exists because this file outlives its context: it lands in
 * Downloads and gets opened months later, by which time "what is this and when
 * was it taken" is not answerable from the rows. `counts` is DERIVED from the
 * arrays rather than passed in, so the summary and the contents cannot
 * disagree; `about.excluded` names what is not here, because a file called an
 * export of your data should say where it stops.
 */
export function buildExportFile(
  { applications, messages }: { applications: unknown[]; messages: unknown[] },
  now: Date = new Date(),
): Record<string, unknown> {
  const removed = applications.filter(isRemoved).length;
  return {
    source: "Applied",
    exported_at: now.toISOString(),
    counts: {
      applications: applications.length,
      applications_removed: removed,
      messages: messages.length,
    },
    about: {
      applications:
        "Every application on your account, removed ones included — a removed row carries a dismissed_at timestamp and can be restored.",
      messages:
        "Every message Applied has stored, as metadata: sender, subject, date, snippet and the classification it was given. Applied never stores message bodies, so none are here.",
      excluded:
        "Your Google account credentials, the search vectors and the mail sync cursor are not in this file.",
    },
    applications,
    messages,
  };
}

/**
 * The human-readable half of a backend error.
 *
 * `String(res.error)` was the old expression and it produced the literal
 * `"[object Object]"` for every real failure (#490): `res.error` is the PARSED
 * JSON body, so a 401 arrives as `{detail: "unauthenticated"}` — an object,
 * which stringifies uselessly — and the `??` fallback beside it never fired
 * because an object is not nullish. The one case the fallback string was
 * written for was the one case it could not reach.
 *
 * Lives here rather than in the route for the same reason the loops below do:
 * in `app/api/applications/route.ts` it needs the Next runtime and cannot be
 * executed by a test.
 */
export function errorDetail(error: unknown, fallback: string): string {
  if (typeof error === "string" && error.trim()) return error;
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return fallback;
}
