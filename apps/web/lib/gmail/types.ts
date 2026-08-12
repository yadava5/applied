/**
 * Client-safe Gmail pipeline types + filter vocabulary.
 *
 * Kept free of any `next/headers` / server-only import so BOTH the server
 * proxy routes (`app/api/gmail/*`) and the client workbench
 * (`components/gmail/InboxWorkbench`) can share one source of truth for the
 * shape of a classified verdict, a fetched page, and the pipeline analysis —
 * and for the filter options the UI offers.
 */

/** One classifier verdict for one message. Never carries body content. */
export interface InboxVerdict {
  message_id: string;
  subject: string;
  sender_email: string;
  sender_name: string | null;
  category: string;
  confidence: number;
  method: string;
  needs_review: boolean;
  /** ISO-8601 receipt time (Date header), or null if unparseable. */
  received_at: string | null;
  /** Normalized company token this message groups under. */
  company: string;
  /**
   * The reader corrected this verdict in the scan view. CLIENT-SIDE ONLY — the
   * mine never sets it (it reports what the classifier said, and the classifier
   * has no opinion about who overruled it). It rides in the session snapshot so
   * a correction still reads as the user's after a remount, the same standing
   * fact the filed ledger shows as "corrected by you".
   */
  user_corrected?: boolean;
}

export type CategorySummary = Record<string, number>;

/** One server-side page of the inbox mine. */
export interface InboxPage {
  connected: boolean;
  scanned: number;
  verdicts: InboxVerdict[];
  next_page_token: string | null;
  category_summary: CategorySummary;
  query: string;
  scope: string;
  range_months: number | null;
  note: string;
}

/** An `applied` message with no later response — a nudge to follow up. */
export interface FollowUp {
  message_id: string;
  company: string;
  subject: string;
  days_since: number;
  applied_at: string | null;
}

/** Whole-set pipeline analysis across every fetched page. */
export interface PipelineAnalysis {
  total: number;
  job_related: number;
  category_summary: CategorySummary;
  follow_ups: FollowUp[];
}

// --- Filter vocabulary ------------------------------------------------------

/** How many messages the user can mine in one go. */
export const COUNT_OPTIONS = [100, 200, 500, 1000, 2000] as const;
export type FetchCount = (typeof COUNT_OPTIONS)[number];

/** Age window. `"all"` omits the `newer_than` bound. */
export const RANGE_OPTIONS = [
  { value: "3", label: "3 mo" },
  { value: "6", label: "6 mo" },
  { value: "9", label: "9 mo" },
  { value: "12", label: "12 mo" },
  { value: "all", label: "All time" },
] as const;
export type RangeValue = (typeof RANGE_OPTIONS)[number]["value"];

/** Where to search. `anywhere` includes archived / all-mail. */
export type ScopeValue = "inbox" | "anywhere";

export interface InboxFilters {
  count: FetchCount;
  range: RangeValue;
  scope: ScopeValue;
}

export const DEFAULT_FILTERS: InboxFilters = {
  count: 200,
  range: "6",
  scope: "inbox",
};

/** Per-page fetch ceiling — mirrors the backend `gmail_fetch_page_size`. */
export const PAGE_SIZE = 500;

// --- Category presentation --------------------------------------------------

/** Canonical categories in pipeline order (job lifecycle first, noise last). */
export const CATEGORY_ORDER = [
  "applied",
  "pending_application",
  "interview",
  "assessment",
  "offer",
  "rejection",
  "follow_up",
  "needs_review",
  "other",
] as const;

/** Categories that count as real job-search signal (everything but noise). */
export const JOB_RELATED_CATEGORIES: readonly string[] = [
  "applied",
  "pending_application",
  "interview",
  "assessment",
  "offer",
  "rejection",
  "follow_up",
];

export const CATEGORY_META: Record<string, { label: string; dot: string }> = {
  offer: { label: "offer", dot: "bg-live" },
  interview: { label: "interview", dot: "bg-live" },
  assessment: { label: "assessment", dot: "bg-live" },
  applied: { label: "applied", dot: "bg-viz-embeddings" },
  pending_application: { label: "pending", dot: "bg-viz-embeddings" },
  follow_up: { label: "follow up", dot: "bg-viz-rules" },
  rejection: { label: "rejection", dot: "bg-reject" },
  needs_review: { label: "needs review", dot: "bg-review" },
  other: { label: "other", dot: "bg-dim" },
};

/** One filter chip: a category, how it reads, and how many hold it. */
export interface CategoryChip {
  value: string;
  label: string;
  dot: string;
  count: number;
}

/**
 * The category chips for a set of counts — ONE vocabulary for both mail views.
 *
 * The filed ledger and the live scan each built this themselves and had drifted:
 * the scan dropped any category `CATEGORY_ORDER` doesn't list (a new backend
 * category would have been invisible rather than merely unstyled) and counted
 * "all" from the row array instead of the counts it was showing, so the two
 * numbers disagreed whenever the whole-set analysis covered more than the
 * rendered page.
 *
 * Canonical order first, then anything else the counts name, sorted — a
 * category this file has never heard of is still offered, never silently
 * dropped. Zero-count categories are omitted: a chip reading "assessment 0" is
 * a filter that returns nothing, which is worse than no chip. That omission is
 * exactly why a corrected verdict has to reach these counts (see
 * `applyVerdictCorrection`) rather than only the row it changed.
 */
export function categoryChips(counts: Record<string, number>): CategoryChip[] {
  const known = CATEGORY_ORDER.filter((c) => (counts[c] ?? 0) > 0);
  const extra = Object.keys(counts)
    .filter((c) => !(CATEGORY_ORDER as readonly string[]).includes(c) && (counts[c] ?? 0) > 0)
    .sort();
  return [...known, ...extra].map((c) => {
    const meta = CATEGORY_META[c] ?? { label: c.replaceAll("_", " "), dot: "bg-dim" };
    return { value: c, label: meta.label, dot: meta.dot, count: counts[c] ?? 0 };
  });
}

/** The "all" chip's number: the sum of the same counts the chips are drawn from. */
export function chipTotal(counts: Record<string, number>): number {
  return Object.values(counts).reduce((sum, n) => sum + (n > 0 ? n : 0), 0);
}

/**
 * Build the query string for one `GET /api/gmail/inbox` page request. Pure —
 * given the same inputs it always yields the same params, so paging is
 * deterministic. `range="all"` is omitted so the backend reads it as all-time.
 */
export function buildInboxParams(args: {
  filters: InboxFilters;
  pageSize: number;
  pageToken?: string | null;
}): string {
  const { filters, pageSize, pageToken } = args;
  const params = new URLSearchParams();
  params.set("count", String(filters.count));
  params.set("scope", filters.scope);
  if (filters.range !== "all") params.set("range", filters.range);
  params.set("page_size", String(pageSize));
  if (pageToken) params.set("page_token", pageToken);
  return params.toString();
}
