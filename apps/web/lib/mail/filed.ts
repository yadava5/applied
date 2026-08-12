/**
 * The filed-mail view's ONE reading of `GET /applications/mail`.
 *
 * The page hands the endpoint's body straight to `readFiledMailPage`, so the
 * defensive parsing — every field optional on the wire, booleans honoured only
 * when literal — lives here once, next to the URL builder the chips and the
 * pager share. Deliberately dependency-free (no React, no `@/` alias, no
 * generated schema) so `tests/unit/` can load it directly under Node's type
 * stripping — the same rule as `review.ts` and `dates.ts`.
 */

/** One stored message, as the listing serves it. Metadata only — no bodies. */
export interface FiledMessage {
  message_id: string;
  thread_id: string | null;
  subject: string | null;
  sender_name: string | null;
  sender_email: string | null;
  received_at: string | null;
  snippet: string | null;
  /** Lowercase wire vocabulary (`applied`, `needs_review`, …) — the same form
   *  the classify endpoint accepts back, so a correction round-trips with no
   *  case mapping. */
  category: string | null;
  confidence: number | null;
  method: string | null;
  user_corrected: boolean;
  is_reviewed: boolean;
  application_id: number | null;
  company: string | null;
  gmail_link: string | null;
}

export interface FiledMailPage {
  messages: FiledMessage[];
  /** Total matching rows under the ACTIVE category + search. */
  total: number;
  page: number;
  pageSize: number;
  /** Per-category totals under the active search ONLY — the chips keep their
   *  own counts while one of them is selected. */
  categoryCounts: Record<string, number>;
}

/** One server page. 32 stored messages is the real account today; 50 keeps
 *  the common case a single page without shipping an unbounded list. */
export const FILED_PAGE_SIZE = 50;

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Read the listing body into the page the view renders, or `null` when the
 *  shape is not the endpoint's — the caller shows the honest failure state
 *  instead of an empty inbox that reads as "you have no mail". */
export function readFiledMailPage(body: unknown): FiledMailPage | null {
  const data = asRecord(body);
  if (!Array.isArray(data.messages)) return null;

  const counts: Record<string, number> = {};
  for (const [key, value] of Object.entries(asRecord(data.category_counts))) {
    const n = num(value);
    if (n !== null) counts[key] = n;
  }

  const messages: FiledMessage[] = [];
  for (const raw of data.messages) {
    const m = asRecord(raw);
    const id = str(m.message_id);
    if (!id) continue; // a message we cannot correct or key is not renderable
    messages.push({
      message_id: id,
      thread_id: str(m.thread_id),
      subject: str(m.subject),
      sender_name: str(m.sender_name),
      sender_email: str(m.sender_email),
      received_at: str(m.received_at),
      snippet: str(m.snippet),
      category: str(m.category),
      confidence: num(m.confidence),
      method: str(m.method),
      user_corrected: m.user_corrected === true,
      is_reviewed: m.is_reviewed === true,
      application_id: num(m.application_id),
      company: str(m.company),
      gmail_link: str(m.gmail_link),
    });
  }

  return {
    messages,
    total: num(data.total) ?? messages.length,
    page: num(data.page) ?? 1,
    pageSize: num(data.page_size) ?? FILED_PAGE_SIZE,
    categoryCounts: counts,
  };
}

/** How many pages the pager offers — never less than one. */
export function filedPageCount(total: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}

/** The filed view's canonical URL for a filter state. Defaults are omitted so
 *  `/inbox` stays the clean address of the resting view. */
export function filedMailHref(params: {
  category?: string | null;
  q?: string | null;
  page?: number;
}): string {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  const q = params.q?.trim();
  if (q) search.set("q", q);
  if (params.page !== undefined && params.page > 1) search.set("page", String(params.page));
  const qs = search.toString();
  return qs ? `/inbox?${qs}` : "/inbox";
}
