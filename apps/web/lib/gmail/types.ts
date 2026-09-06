/**
 * Client-safe Gmail pipeline types + filter vocabulary.
 *
 * Kept free of any `next/headers` / server-only import so BOTH the server
 * proxy routes (`app/api/gmail/*`) and the client workbench
 * (`components/gmail/InboxWorkbench`) can share one source of truth for the
 * shape of a classified verdict, a fetched page, and the pipeline analysis —
 * and for the filter options the UI offers.
 */

/**
 * One classifier verdict for one message, and enough of the message to judge
 * that verdict by.
 *
 * A hand-maintained mirror of the backend `InboxVerdict` (see
 * `backend/jobtracker/cloud/gmail_oauth.py`) — NOT generated, so a field added
 * there has to be added here too or the scan view silently drops it, which is
 * how `snippet`/`gmail_link` were missing from this view for as long as it
 * existed. `lib/api/schema.d.ts` is the generated contract; keep the two in
 * step. Never a full body: `snippet` is Gmail's own preview, the same text the
 * verdict was reached from, bounded to 500 chars by the backend.
 */
export interface InboxVerdict {
  message_id: string;
  subject: string;
  sender_email: string;
  sender_name: string | null;
  category: string;
  /**
   * The CLASSIFIER's certainty about the category it chose. Stays put when a
   * reader overrules the verdict, and must: it is relayed to `/gmail/sync` by
   * `toPipelineItems` (where `PipelineItem.confidence` is required and gates
   * persistence) and to the classify endpoint by `scanMessagePayload`, which
   * mints the row as a faithful copy of what the machine said BEFORE applying
   * the correction on top.
   *
   * It is therefore not a claim about the displayed verdict once that verdict
   * is the reader's, and must not be RENDERED beside one — see
   * `verdictShowsConfidence`.
   */
  confidence: number;
  method: string;
  needs_review: boolean;
  /** ISO-8601 receipt time (Date header), or null if unparseable. */
  received_at: string | null;
  /** Normalized company token this message groups under. */
  company: string;
  /**
   * Gmail's preview of the message, or null when it has none. Optional because
   * a verdict rehydrated from an older session snapshot predates the field —
   * null and absent both mean "show nothing", never an empty preview line.
   */
  snippet?: string | null;
  /** Deep link to the message in Gmail, or null when one can't be built. */
  gmail_link?: string | null;
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
  /**
   * Messages Gmail listed for this page but would not hand over.
   *
   * THIS FIELD WAS MISSING FROM THIS INTERFACE, and its absence is the whole
   * mechanism of a defect. The backend has always computed it
   * (`MessagePage.unreadable` = `len(ids) - len(out)`) and always put it on
   * the wire; it is in the generated types at `lib/api/schema.d.ts`. This
   * hand-written mirror dropped it, so `page.unreadable` did not type-check
   * and no caller could ever have read it — a field cannot be forgotten in the
   * UI if the type still offers it, but it cannot be found either if the type
   * denies it exists.
   *
   * On 2026-09-04 a live scan lost 146 of 200 messages to a Gmail rate limit
   * and reported "54 scanned" as an ordinary success.
   *
   * Optional because a snapshot written before this field existed hydrates
   * without it, and `0` is the honest reading of "this page never told us".
   */
  unreadable?: number;
  /**
   * Of `unreadable`, the share Gmail refused with no reason the backend
   * recognises (#744).
   *
   * A SUBSET, carried separately because the two mean opposite things. A
   * deleted message is ordinary; a refusal we cannot read may be a quota
   * wearing an envelope shape that changed under us, and the cursor advances
   * past those ids permanently either way. Non-zero on a healthy mailbox means
   * the backend's `_RATE_LIMIT_REASONS` needs extending.
   *
   * Optional for the same reason as `unreadable`: an older snapshot hydrates
   * without it, and `0` is the honest reading of "this page never told us".
   */
  unrecognised?: number;
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
export const PAGE_SIZE = 99;

/*
 * WAS 500 UNTIL 2026-09-04, WHICH BECAME ARITHMETICALLY IMPOSSIBLE.
 *
 * Gmail charges 20 quota units per `messages.get` (raised from 5 on
 * 2026-05-01) against a ceiling of 6,000 units per minute per user (cut from
 * 15,000 the same day). Both numbers were read from this project's own Cloud
 * Console, not assumed.
 *
 *   one page of 500  =  20 x 500 + 5  =  10,005 units
 *   the whole minute's budget         =   6,000 units
 *
 * So a single 500-message page could not succeed on a full bucket, ever, no
 * matter how the server retried — and the failure it produced was a 403 that
 * reached the user as "We couldn't finish reading your mail."
 *
 *   one page of  99  =  20 x  99 + 5  =   1,985 units
 *
 * NINETY-NINE, NOT A HUNDRED, and the missing one is worth 48%. Throughput is
 * `N * floor(6000 / (20N + 5))`. The `+5` for the page's single
 * `messages.list` call puts the round number on the wrong side of a boundary:
 *
 *   N = 100 -> 2,005/page -> floor(6000/2005) = 2 pages -> 200 messages/min
 *   N =  99 -> 1,985/page -> floor(6000/1985) = 3 pages -> 297 messages/min
 *
 * For a 2,000-message scan that is ten minutes against 6.7 — and 6.7 is the
 * physical floor (`2000 * 20 / 6000`), so 99 reaches 99.0% of what Gmail will
 * ever allow — 297 of the 300 messages a minute affords. 150 is worse than either at 150/min. The best value the server's
 * clamp permits is 149 (298/min); 99 gives up 0.4% of that for 50% finer
 * progress and a deferral that re-costs a third of a minute instead of half.
 *
 * Smaller pages also make a deferral cheap: the retry re-costs one page, not
 * five, against the very budget that just refused.
 *
 * The server holds the same number: `gmail_fetch_page_size` defaults to 99 and
 * the handler clamps anything larger to 250. They are EQUAL on purpose, not
 * one under the other — an earlier version of this comment said the client
 * "picks lower than the ceiling it is allowed", which stopped being true the
 * moment both moved to 99.
 *
 * Equality is what the pin test asserts
 * (`backend/tests/test_the_page_size_fits_gmails_minute.py`), because the
 * client is the party that LOOPS: the server only clamps, so its careful
 * default never applies to an interactive scan unless the client asks for it.
 */

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

/**
 * How each category reads on a row, and its dot.
 *
 * `chipLabel` overrides `label` on the COUNT chips only, and exactly one
 * category needs it. On a single message the badge states the classifier's
 * verdict — "needs review" is what happened to that message. The chip states
 * how many STORED messages hold that verdict, which is a different question
 * from the dashboard's work-queue count and must not wear the same words: 8 on
 * the dashboard against 9 here reads as a bug when both say "needs review"
 * (#445, and `REVIEW_QUEUE_LABEL` in `lib/dashboard/review.ts` is the other
 * half of the pair).
 */
export const CATEGORY_META: Record<
  string,
  { label: string; chipLabel?: string; dot: string }
> = {
  offer: { label: "offer", dot: "bg-live" },
  interview: { label: "interview", dot: "bg-live" },
  assessment: { label: "assessment", dot: "bg-live" },
  applied: { label: "applied", dot: "bg-viz-embeddings" },
  pending_application: { label: "pending", dot: "bg-viz-embeddings" },
  follow_up: { label: "follow up", dot: "bg-viz-rules" },
  rejection: { label: "rejection", dot: "bg-reject" },
  needs_review: { label: "needs review", chipLabel: "held for review", dot: "bg-review" },
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
    const meta: (typeof CATEGORY_META)[string] =
      CATEGORY_META[c] ?? { label: c.replaceAll("_", " "), dot: "bg-dim" };
    // A chip counts a SET, a badge names one message — `chipLabel` is where the
    // two part company (needs_review, #445). Everything else reads the same.
    return { value: c, label: meta.chipLabel ?? meta.label, dot: meta.dot, count: counts[c] ?? 0 };
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
