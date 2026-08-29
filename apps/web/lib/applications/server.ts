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
import { classifyBackendBody, type ClassifyArgs } from "@/lib/applications/classify-request";
import { serverEnv } from "@/lib/env.server";
import { getAccessToken } from "@/lib/supabase/auth";

export interface ApiCallResult {
  ok: boolean;
  status: number;
  data: unknown;
  /**
   * The backend's own response, once the body has been read off it. Present
   * only when the call actually reached the backend — absent for the
   * unauthenticated short-circuit and for a network failure — so a proxy route
   * can pass it to `withServerTiming` and copy nothing when there is nothing to
   * copy (#269). Read HEADERS off this, never the body: it is already consumed.
   */
  response?: Response;
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
    return { ok: res.ok, status: res.status, data, response: res };
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
 * PUT /applications/{id}/role — the job title, typed by the person who applied.
 *
 * Issue #72: the Gmail path fetches `format=metadata` and the ATS subjects it
 * reads name the employer, so a role is never extracted and `position` is `""`
 * on every auto-filed row for good. This is the only way one is ever filled in,
 * and the backend marks it `position_source: "user"` so no later sync — nor a
 * future extraction improvement — writes over it.
 *
 * `null` clears both the title and that claim, which matters more here than it
 * does for a deadline: once the field is the user's, the sync may no longer
 * correct a typo in it, so there has to be a way to hand it back.
 */
export function setApplicationRole(id: number, role: string | null): Promise<ApiCallResult> {
  return call(`/applications/${id}/role`, { method: "PUT", body: { role } });
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
 * GET /applications — one bounded page of the board, for a surface that needs
 * to ask WHICH application a message is about (#560).
 *
 * The same call and the same page size the dashboard makes, deliberately: the
 * question can only offer rows the reader can also see on their board, and a
 * second page size here would make the two disagree about which employers hold
 * "several" applications.
 */
export function getBoardPage(pageSize: number): Promise<ApiCallResult> {
  return call(`/applications?page=1&page_size=${pageSize}`, { method: "GET" });
}

/**
 * POST /applications/review/{messageId}/classify — classify + persist + train.
 *
 * `company` is the second half of the `needs_employer` round trip: the backend
 * consults it ONLY when it cannot name the employer from the mail itself, so we
 * send it only when the user has actually supplied one. A 2xx here does not
 * imply a row was filed — the caller must read `needs_employer` off the body.
 *
 * `message` carries the mail's own metadata for a message that may not be
 * stored — every row in the live-scan view. Without it those corrections were
 * 404s, because the scan reads Gmail and persists nothing and the file step
 * drops anything below the 0.70 review floor.
 *
 * The body itself is built by `classifyBackendBody` rather than inline. This
 * function is unreachable from `tests/unit/` (it pulls in `env.server` and the
 * Supabase session), so an inline rebuild here is covered by nothing that runs
 * — which is how `confirm_new_company` was dropped and the near-miss
 * confirmation shipped unanswerable. Add a field THERE, where a test executes
 * it, never here.
 */
export function classifyReviewItem(
  messageId: string,
  args: ClassifyArgs,
): Promise<ApiCallResult> {
  return call(`/applications/review/${encodeURIComponent(messageId)}/classify`, {
    method: "POST",
    body: classifyBackendBody(args),
  });
}
