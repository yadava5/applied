/**
 * The backend's own failure sentence, carried across the proxy boundary.
 *
 * WHY THIS EXISTS (#848). `POST /gmail/sync` answers a failed cursor stamp
 * with a sentence that names what survived the failure — "3 filed and 1 queued
 * of 4 scanned before it failed; sync again to finish" (#643). Every non-OK
 * response used to be classified in `server.ts` from `status` and `headers`
 * ALONE:
 *
 *     if (!res.ok) return classifyBadResponse(res.status, res.headers);
 *     return { kind: "ok", result: (await res.json()) as GmailSyncOutcome };
 *
 * `res.json()` sits on the OK path, so the body was never read on the path
 * that had something to say. The sentence was reachable by direct API
 * consumers and by tests, and by nothing a user would ever see.
 *
 * WHAT THE READER GETS WHEN THE BACKEND SAYS NOTHING. `message` keeps the
 * proxy's status-derived line ("Backend responded 500") — a 502 from the edge,
 * a timeout, an HTML error page and a killed function all arrive with no JSON
 * at all, and the reader is still owed something they can quote. So this
 * module answers `null` for every unusable body and the caller keeps what it
 * had, rather than replacing a true generic with an empty string.
 *
 * THE DISCIPLINE BELOW IS `errorDetail`'s (`lib/applications/export.ts`), and
 * for the same reason: the export proxy shipped `"[object Object]"` to users
 * for weeks because `String(res.error ?? fallback)` renders an object
 * uselessly and `??` never fires on one. A non-string `detail` is not a
 * message; a blank one is not a message either.
 */

/** A body worth quoting to the reader, or `null` — never a blank or an object. */
export function backendSyncDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  // Arrays reach here as objects: a pydantic validation error is a LIST of
  // `{loc, msg}`, and `("detail" in [])` is false, so it falls out below.
  if (!("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail !== "string") return null;
  const trimmed = detail.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * The proxy's failure, with the backend's sentence in place of the generic one.
 *
 * ONLY THE `backend` KIND. `auth`, `unavailable` and `rate_limited` are
 * rendered from their kind — the reader is shown "sign in again", "not enabled
 * on this deploy" and a countdown respectively, and none of them has a
 * `message` field for a sentence to land in. Overriding those would put a
 * backend string somewhere nothing reads it, which is how #848 happened in the
 * first place.
 *
 * Generic over the failure so this module imports no types from
 * `server.ts` — that module pulls `env.server` and `supabase/auth`, and a type
 * import is erased but the temptation to add a value one is not.
 */
export function withBackendSyncDetail<F extends { kind: string; message?: string }>(
  failure: F,
  body: unknown,
): F {
  if (failure.kind !== "backend") return failure;
  const detail = backendSyncDetail(body);
  return detail === null ? failure : { ...failure, message: detail };
}
