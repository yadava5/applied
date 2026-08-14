/**
 * Unit tests for `lib/account/deletion.ts` — the ordering behind Settings →
 * "Delete account", i.e. `app/api/account/delete/route.ts`.
 *
 * These exist because the defect shipped and nothing could have seen it. The
 * backend half of account deletion is genuinely well covered:
 * `backend/tests/test_account_deletion_covers_every_table.py` derives the
 * required table set from `SQLModel.metadata` and the FK ordering from the
 * schema, so a new tenant table fails on the commit that adds it. None of it
 * touches the Next route, and the route is where the data-loss lived: the
 * purge's response was discarded (`await fetch(...).catch(() => undefined)` —
 * and `fetch` does not reject on 4xx/5xx) while `deleteUser` ran
 * unconditionally. A failed purge therefore destroyed the auth user and
 * orphaned every row under a `user_id` nobody could ever sign in as again.
 * That is unretryable by construction: retrying needs a token, and a token
 * needs the auth user that was just destroyed. The green suite is exactly why
 * it shipped — the half that was tested was the half that was right.
 *
 * Each test below is annotated with the mutation that turns it red, because a
 * test that passes against the buggy route is worth nothing and this repo has
 * shipped several. Reverting one line does NOT redden all of them; they catch
 * four different ways to get this wrong.
 *
 * Run:  pnpm test:unit    (Node ≥ 22.6 — the import below is type-stripped)
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  AUTH_DELETE_FAILED_DETAIL,
  DELETION_DISABLED_DETAIL,
  NO_SESSION_DETAIL,
  PURGE_FAILED_DETAIL,
  runAccountDeletion,
} from "../../lib/account/deletion.ts";

/**
 * A recording pair of ports. `purge` answers however the test says; the auth
 * deletion records that it was reached at all, which is the whole assertion.
 */
function ports({ purge, deleteError = null } = {}) {
  const calls = { purge: 0, deleteAuthUser: 0 };
  return {
    calls,
    purge:
      purge === null
        ? null
        : async () => {
            calls.purge += 1;
            return purge();
          },
    deleteAuthUser: async () => {
      calls.deleteAuthUser += 1;
      return { error: deleteError };
    },
  };
}

test("a purge that answers 500 must not destroy the auth user", async () => {
  // THE case. `fetch` resolves for a 500 — it does not reject — so a
  // `.catch()`-only implementation cannot pass this, which is the entire
  // reason the file exists.
  //
  // Red when: the route swallows the purge result and calls `deleteUser`
  // unconditionally (the original bug shape).
  const p = ports({ purge: async () => ({ ok: false, status: 500 }) });
  const out = await runAccountDeletion(p);

  assert.equal(p.calls.purge, 1);
  assert.equal(p.calls.deleteAuthUser, 0, "the auth user must survive a failed purge");
  assert.equal(out.status, 502);
  assert.equal(out.body.detail, PURGE_FAILED_DETAIL);
  // The user has to be told their data is still there, or the honest thing
  // that happened reads as the dishonest one.
  assert.match(out.body.detail, /nothing was deleted/i);
});

test("an expired token's 401 from the purge is treated the same as any other refusal", async () => {
  // 4xx and 5xx are indistinguishable in consequence: the rows may still be
  // there. A route that only guarded `status >= 500` would pass the test above
  // and fail this one.
  //
  // Red when: the guard reads `status >= 500`, or reads nothing at all.
  const p = ports({ purge: async () => ({ ok: false, status: 401 }) });
  const out = await runAccountDeletion(p);

  assert.equal(p.calls.deleteAuthUser, 0);
  assert.equal(out.status, 502);
});

test("a purge that rejects (network, DNS, wrong BACKEND_API_URL) must not destroy the auth user", async () => {
  // Red when: the rejection is swallowed and execution falls through to
  // `deleteUser` (the original `.catch(() => undefined)`).
  const p = ports({
    purge: async () => {
      throw new TypeError("fetch failed");
    },
  });
  const out = await runAccountDeletion(p);

  assert.equal(p.calls.purge, 1);
  assert.equal(p.calls.deleteAuthUser, 0, "a network failure is not a successful purge");
  assert.equal(out.status, 502);
  assert.equal(out.body.detail, PURGE_FAILED_DETAIL);
});

test("a purge that succeeds does destroy the auth user, and answers 200", async () => {
  // The positive control. Without it the whole file is satisfiable by a route
  // that never deletes anything — which is a different way to be broken, and
  // the one production is in today.
  //
  // Red when: the abort is too broad (e.g. aborting on any response), or the
  // `deleteUser` call is dropped entirely.
  const p = ports({ purge: async () => ({ ok: true, status: 200 }) });
  const out = await runAccountDeletion(p);

  assert.equal(p.calls.purge, 1);
  assert.equal(p.calls.deleteAuthUser, 1);
  assert.equal(out.status, 200);
  assert.deepEqual(out.body, { deleted: true });
});

test("the purge runs BEFORE the auth user is destroyed, not alongside it", async () => {
  // Ordering, asserted as ordering rather than inferred from two counters.
  // Firing both concurrently would satisfy every count above while
  // reintroducing the race the backend's contract exists to prevent.
  //
  // Red when: the two effects are started together (`Promise.all`) or the auth
  // deletion is moved first.
  const order = [];
  const out = await runAccountDeletion({
    purge: async () => {
      order.push("purge");
      return { ok: true, status: 200 };
    },
    deleteAuthUser: async () => {
      order.push("deleteAuthUser");
      return { error: null };
    },
  });

  assert.deepEqual(order, ["purge", "deleteAuthUser"]);
  assert.equal(out.status, 200);
});

test("a deployment with no service-role key answers 501 and attempts nothing", async () => {
  // #218: the honest backstop. It must also be a *pure* refusal — no backend
  // call, so a deployment that cannot finish the job never starts it and
  // leaves nothing half-done to explain.
  //
  // Red when: the null-gate is removed or moved after the purge, so an
  // unconfigured deployment still purges the user's rows and then cannot
  // delete the account — the worst outcome of the four.
  const p = ports({ purge: async () => ({ ok: true, status: 200 }) });
  const out = await runAccountDeletion({ purge: p.purge, deleteAuthUser: null });

  assert.equal(p.calls.purge, 0, "an unconfigured deployment must not purge anything");
  assert.equal(out.status, 501);
  assert.equal(out.body.detail, DELETION_DISABLED_DETAIL);
});

test("no access token means no purge is possible, so nothing is deleted", async () => {
  // The session can be present enough for `getUser()` and still carry no
  // bearer token. Deleting the auth user here would orphan every row exactly
  // as a failed purge does, so it is the same refusal.
  //
  // Red when: a missing token is treated as "skip the purge and carry on",
  // which is what the original route did.
  const p = ports();
  const out = await runAccountDeletion({ purge: null, deleteAuthUser: p.deleteAuthUser });

  assert.equal(p.calls.deleteAuthUser, 0);
  assert.equal(out.status, 401);
  assert.equal(out.body.detail, NO_SESSION_DETAIL);
});

test("a purge that worked followed by a failed auth deletion is reported as retryable", async () => {
  // The one tail where the rows really are gone. Retrying is safe — the
  // backend's purge is an unconditional DELETE per table — so the user is told
  // to retry rather than left believing their account is closed when it is
  // still signed-in-able.
  //
  // Red when: the `error` from `deleteUser` is ignored and the route answers
  // 200, telling the user an account that still exists was deleted.
  const p = ports({
    purge: async () => ({ ok: true, status: 200 }),
    deleteError: { message: "User not allowed" },
  });
  const out = await runAccountDeletion(p);

  assert.equal(p.calls.deleteAuthUser, 1);
  assert.equal(out.status, 502);
  assert.equal(out.body.detail, AUTH_DELETE_FAILED_DETAIL);
});

test("every refusal carries a detail string the dialog can render", async () => {
  // `AccountSection` surfaces `detail` verbatim and falls back to a generic
  // sentence when it is missing, so a refusal without one would silently
  // become "isn't available on this deployment yet" — the wrong explanation
  // for a backend outage, and the reassurance about their data would be lost.
  const outcomes = await Promise.all([
    runAccountDeletion({ purge: null, deleteAuthUser: null }),
    runAccountDeletion({ purge: async () => ({ ok: true, status: 200 }), deleteAuthUser: null }),
    runAccountDeletion({
      purge: async () => ({ ok: false, status: 503 }),
      deleteAuthUser: async () => ({ error: null }),
    }),
  ]);

  for (const out of outcomes) {
    assert.notEqual(out.status, 200);
    assert.equal(typeof out.body.detail, "string");
    assert.ok(out.body.detail.length > 0);
  }
});
