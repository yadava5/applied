/**
 * Server-only helpers for the application correction + review surface.
 *
 * These talk to the FastAPI backend's cloud `/applications` endpoints carrying
 * the caller's Supabase JWT — the token and `BACKEND_API_URL` never reach the
 * browser. They mirror `lib/gmail/server.ts`: plain `fetch` (not the typed
 * openapi-fetch client), and every call returns a normalized result instead of
 * throwing so the proxy route handlers can map it to an honest status.
 *
 * The original reason for the untyped `fetch` — "these endpoints aren't in the
 * committed seed schema" — is gone: `lib/api/schema.d.ts` is now generated from
 * `main_cloud` and covers all 20 paths. These helpers still hand back `unknown`
 * and the readers (`lib/dashboard/detail.ts`, `review.ts`) still parse it
 * defensively, which is what caught nothing when `split_candidates[].role` was
 * read as `position`. Moving them onto the typed client is a follow-up.
 *
 * Everything here is user-scoped on the backend (the JWT's `sub`), and each
 * write both updates the row AND records a training example — the correction
 * loop the user drives from the board.
 */
import { serverEnv } from "@/lib/env";
import { getAccessToken } from "@/lib/supabase/auth";

export interface ApiCallResult {
  ok: boolean;
  status: number;
  data: unknown;
}

const UNAUTHENTICATED: ApiCallResult = { ok: false, status: 401, data: { detail: "unauthenticated" } };

async function call(
  path: string,
  init: { method: string; body?: unknown },
): Promise<ApiCallResult> {
  const token = await getAccessToken();
  if (!token) return UNAUTHENTICATED;

  try {
    const { BACKEND_API_URL } = serverEnv();
    const res = await fetch(`${BACKEND_API_URL}${path}`, {
      method: init.method,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return {
      ok: false,
      status: 502,
      data: { detail: err instanceof Error ? err.message : "Backend unreachable" },
    };
  }
}

/** PATCH /applications/{id} — apply a user's status correction (sticky + trains). */
export function updateApplicationStatus(id: number, status: string): Promise<ApiCallResult> {
  return call(`/applications/${id}`, { method: "PATCH", body: { status } });
}

/** POST /applications/{id}/dismiss — "not an application"; removes + trains "other". */
export function dismissApplication(id: number): Promise<ApiCallResult> {
  return call(`/applications/${id}/dismiss`, { method: "POST", body: {} });
}

/**
 * POST /applications/{id}/restore — undo a dismissal.
 *
 * The counterpart to `dismissApplication`, and the reason a dismissal is safe
 * to offer without a confirmation dialog: the row and its emails stay on disk,
 * so this puts them back. A rebuild's own removals are dismissals too, which is
 * what makes the removals it reports auditable rather than final.
 */
export function restoreApplication(id: number): Promise<ApiCallResult> {
  return call(`/applications/${id}/restore`, { method: "POST", body: {} });
}

/**
 * PUT /applications/{id}/deadline — set or clear when something is due.
 *
 * A date written through here is the USER's and is marked as such, so later
 * syncs never overwrite it. A deadline read out of mail is refreshed when newer
 * mail supersedes it; a deadline a person typed is a decision.
 *
 * `null` clears both the date and its origin — a source with no date would be a
 * claim about nothing.
 */
export function setApplicationDeadline(
  id: number,
  dueAt: string | null,
): Promise<ApiCallResult> {
  return call(`/applications/${id}/deadline`, {
    method: "PUT",
    body: { due_at: dueAt },
  });
}

/**
 * POST /applications/{id}/split — turn a merged row into the applications its
 * own stored mail describes.
 *
 * Reads nothing from Gmail: the identity (requisition id, role title) is in the
 * subject and snippet already persisted for every contributing message. The row
 * is retained for its earliest cluster, so its id — and every contact,
 * interview and correction hanging off it — stays with the application that has
 * been on the board longest.
 *
 * A 409 means "this row's mail describes one application". That is the common
 * case and not a failure.
 */
export function splitApplication(id: number): Promise<ApiCallResult> {
  return call(`/applications/${id}/split`, { method: "POST", body: {} });
}

/**
 * DELETE /applications/{id} — hard-delete the row and its linked emails.
 *
 * There is no undo for this one, which is why it is the only row action behind
 * a confirmation. Prefer `dismissApplication` for anything reversible.
 */
export function deleteApplication(id: number): Promise<ApiCallResult> {
  return call(`/applications/${id}`, { method: "DELETE" });
}

/** GET /applications/{id} — the row plus the underlying (metadata-only) mail. */
export function getApplicationDetail(id: number): Promise<ApiCallResult> {
  return call(`/applications/${id}`, { method: "GET" });
}

/** GET /applications/review — the needs-classification queue. */
export function getReviewQueue(): Promise<ApiCallResult> {
  return call(`/applications/review`, { method: "GET" });
}

/** The query parameters `/applications/mail` accepts. Nothing else is forwarded. */
const MAIL_QUERY_PARAMS = ["page", "page_size", "category", "q"] as const;

/**
 * GET /applications/mail — every stored message, whatever the verdict.
 *
 * The counterpart to `getReviewQueue`, and the reason it exists: the review
 * queue filters to `needs_review AND unlinked AND not-yet-reviewed`, so a
 * verdict becomes unreachable the moment it is touched. This lists the user's
 * mail regardless of review state or linkage, which is what makes a wrong
 * verdict correctable more than once. Metadata only — bodies never leave the
 * backend.
 *
 * Values are forwarded as strings and validated by FastAPI, which already
 * answers a precise 422 naming the offending parameter. A second parser here
 * would be a second thing to drift. The keys ARE allowlisted: only the four
 * the endpoint declares travel, so this proxy cannot be used to reach
 * parameters the backend adds later without a deliberate change here.
 */
export function getMail(search: URLSearchParams): Promise<ApiCallResult> {
  const forwarded = new URLSearchParams();
  for (const key of MAIL_QUERY_PARAMS) {
    const value = search.get(key)?.trim();
    if (value) forwarded.set(key, value);
  }
  const query = forwarded.toString();
  return call(`/applications/mail${query ? `?${query}` : ""}`, { method: "GET" });
}

/**
 * POST /applications/review/{messageId}/classify — classify + persist + train.
 *
 * `company` is the second half of the `needs_employer` round trip: the backend
 * consults it ONLY when it cannot name the employer from the mail itself, so we
 * send it only when the user has actually supplied one. A 2xx here does not
 * imply a row was filed — the caller must read `needs_employer` off the body.
 */
export function classifyReviewItem(
  messageId: string,
  category: string,
  company?: string,
  applicationId?: number,
): Promise<ApiCallResult> {
  const named = company?.trim();
  return call(`/applications/review/${encodeURIComponent(messageId)}/classify`, {
    method: "POST",
    body: {
      category,
      ...(named ? { company: named } : {}),
      // The user's own answer to "which application is this about?". Omitted
      // rather than sent as null when absent, so the backend's "no choice was
      // made" path stays distinguishable from "the choice was empty".
      ...(applicationId !== undefined ? { application_id: applicationId } : {}),
    },
  });
}
