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

/** The rows are gone, the profile photo is not, and the account is still open
 *  so the whole thing can be retried. Named as its own outcome because "your
 *  data was removed" would be a lie while a photograph of the user's face is
 *  still in a bucket. */
export const AVATAR_PURGE_FAILED_DETAIL =
  "Your applications were removed but your profile photo couldn’t be, so the account is still open. Try again in a moment.";

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
  /**
   * Remove the caller's stored profile photos (Supabase Storage — a store the
   * backend's `DELETE /account` knows nothing about, because it is not in
   * Postgres). Omit it and the step does not run; that is the shape every
   * caller written before profile photos existed still compiles as.
   *
   * `ok: false` means objects may still be there. It is treated as a stop,
   * not a shrug: deleting the auth user at that point would leave a photograph
   * of the user's face in a bucket with nothing left that could ever ask for it
   * back — the orphaning shape of #214 with a worse artifact. A bucket that
   * does not exist is not a failure; the caller resolves that (`isBucketMissing`).
   */
  purgeAvatars?: (() => Promise<{ ok: boolean }>) | null;
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

  // Between the rows and the auth user, and in that order for two reasons: the
  // rows are the thing the user asked to be rid of, and the objects are owned
  // by an auth user that is about to stop existing — after `deleteUser` there
  // is no session left to authorise a storage delete with.
  if (ports.purgeAvatars) {
    const { ok } = await ports.purgeAvatars();
    if (!ok) return { status: 502, body: { detail: AVATAR_PURGE_FAILED_DETAIL } };
  }

  const { error } = await ports.deleteAuthUser();
  if (error) {
    return { status: 502, body: { detail: AUTH_DELETE_FAILED_DETAIL } };
  }

  return { status: 200, body: { deleted: true } };
}
