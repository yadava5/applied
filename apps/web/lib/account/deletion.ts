/**
 * The account-deletion ordering, as a pure function over injected ports.
 *
 * It lives here rather than inline in `app/api/account/delete/route.ts` for
 * the same reason `lib/applications/export.ts` does: in the route it could not
 * be executed by a test. The handler needs the Next runtime, a Supabase cookie
 * jar and a service-role key, so the code deciding whether a user's auth
 * account is destroyed before or after their rows were actually removed was
 * covered by types and review only — and it was wrong (#214). `fetch` does not
 * reject on 4xx/5xx, the old code discarded the response entirely, and
 * `deleteUser` ran unconditionally. A failed purge therefore left the rows in
 * Postgres under a `user_id` nobody could ever sign in as again: unretryable
 * by construction, because retrying needs a token and a token needs the auth
 * user that was just destroyed.
 *
 * Dependency-free on purpose (no React, no `@/` alias, no `next/server`, no
 * generated schema) so `tests/unit/` can load it directly under Node's type
 * stripping — the same rule as `export.ts`, `detail.ts` and `sync-plan.ts`.
 * The route wraps the returned `{ status, body }` in `NextResponse.json`.
 */

/** The deployment has no service-role key, so nothing can be deleted at all. */
export const DELETION_DISABLED_DETAIL =
  "Account deletion isn’t enabled on this deployment yet. Email the admin to have your data removed.";

/** The purge did not succeed. Said in full because it is the reassuring case. */
export const PURGE_FAILED_DETAIL =
  "Couldn’t remove your data, so nothing was deleted — your account and everything in it are untouched. Try again in a moment.";

/** Signed in, but no bearer token to purge with. Also a "nothing happened". */
export const NO_SESSION_DETAIL =
  "Your session expired before anything was deleted. Nothing was removed — sign in again and retry.";

/** The rows are gone but the auth user survived. The one retryable-and-safe tail. */
export const AUTH_DELETE_FAILED_DETAIL =
  "Your data was removed but the account itself couldn’t be closed. Try again — nothing will be lost.";

/** Just enough of a `Response` to decide on. `fetch`'s own shape, narrowed. */
export interface PurgeResponse {
  ok: boolean;
  status: number;
}

/**
 * The two privileged effects, injected.
 *
 * `null` is meaningful on both and means "this deployment/session cannot do
 * it", which is exactly the state that must not be papered over:
 *
 * - `deleteAuthUser: null` — no `SUPABASE_SERVICE_ROLE_KEY` (#218). The route
 *   answers 501 and never touches the backend.
 * - `purge: null` — no access token, so the backend cannot be asked to remove
 *   anything. Deleting the auth user here would orphan every row, so it is the
 *   same refusal as a failed purge.
 */
export interface AccountDeletionPorts {
  purge: (() => Promise<PurgeResponse>) | null;
  deleteAuthUser: (() => Promise<{ error: { message: string } | null }>) | null;
}

export interface AccountDeletionOutcome {
  status: number;
  body: { deleted: true } | { detail: string };
}

/**
 * Purge the user's rows first; destroy the auth user only if that succeeded.
 *
 * The ordering is the backend's documented contract
 * (`backend/jobtracker/cloud/account.py`): "a failure here surfaces before the
 * auth user is gone and the web flow can retry". This function is the half of
 * that sentence the web layer was not keeping.
 *
 * **A network rejection and a non-2xx are treated identically.** Both mean the
 * rows may still be there, and neither is distinguishable from the other in
 * consequence. `res.ok` covers 4xx and 5xx; the `catch` covers DNS, TLS, a
 * wrong `BACKEND_API_URL`, and a `purge` that throws before it ever fetches.
 *
 * On a *partial* purge we still abort and tell the user to retry, and that is
 * deliberate rather than a shrug: the backend's purge issues an unconditional
 * `DELETE … WHERE user_id = <caller>` per table inside one transaction, so a
 * failure rolls back and a repeat call is idempotent by construction — there
 * is no state a second attempt can corrupt, and rows the first attempt did
 * remove simply are not there to remove again. Leaving the auth user intact is
 * what keeps that retry reachable at all. Note this is a claim about the
 * backend's shape, not a tested property: no test in this repo drives
 * `DELETE /account` twice. If that ever stops being true, this is the comment
 * that has to change. One live interaction worth naming: since the purge now
 * also revokes the Gmail grant at Google (#215), a retry re-revokes an already
 * revoked token — Google answers 400, the backend's best-effort revocation
 * returns False, and the deletion proceeds regardless.
 */
export async function runAccountDeletion(
  ports: AccountDeletionPorts,
): Promise<AccountDeletionOutcome> {
  // Checked before anything else so an unconfigured deployment stays a pure
  // read: no backend call, no token spent, nothing half-done to explain.
  if (!ports.deleteAuthUser) {
    return { status: 501, body: { detail: DELETION_DISABLED_DETAIL } };
  }

  if (!ports.purge) {
    return { status: 401, body: { detail: NO_SESSION_DETAIL } };
  }

  const purged = await ports.purge().catch(() => null);
  if (!purged || !purged.ok) {
    return { status: 502, body: { detail: PURGE_FAILED_DETAIL } };
  }

  const { error } = await ports.deleteAuthUser();
  if (error) {
    return { status: 502, body: { detail: AUTH_DELETE_FAILED_DETAIL } };
  }

  return { status: 200, body: { deleted: true } };
}
