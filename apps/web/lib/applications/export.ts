/**
 * The export's paging loop, as a pure function over a page-fetcher.
 *
 * It lives here rather than inline in `app/api/applications/route.ts` for one
 * reason: in the route it could not be executed by a test. The handler needs
 * the Next runtime and a Supabase cookie jar, so the loop that decides whether
 * a user gets all of their data or a silently truncated file was covered by
 * types and review only. Settings offers to "export everything Applied holds
 * for you"; a truncated answer there is a data-loss-shaped defect in the one
 * feature whose whole job is handing the user their data back.
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

/** What a fetcher returns: the page, or a failure the export must not paper over. */
export type PageResult =
  | { ok: true; page: ApplicationsPage }
  | { ok: false; status: number; detail: string };

export type ExportResult =
  | { ok: true; applications: unknown[]; total: number; pagesRead: number }
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
