/**
 * A server-side PKCE exchange spends verifier cookies it cannot name, so the
 * callback responses must expire them (#321).
 *
 * WHAT WAS MEASURED, AND WHY THIS FILE ASSERTS WHAT IT DOES. Against a fake
 * Supabase Auth server with the installed `@supabase/ssr` + `@supabase/auth-js`
 * — a real browser flow start minting real verifier cookies, then a real
 * server exchange:
 *
 *   flow start  writes THREE cookies at Max-Age=34560000 (400 days): the flow
 *               slot `…-flow-<id>-code-verifier`, the index
 *               `…-flows-code-verifier`, and the fixed `…-code-verifier`.
 *   SUCCESS     the library deletes the fixed key only. Slot + index survive.
 *   FAILURE     the library deletes NOTHING — the fixed key survives too,
 *               because the removal is buffered and only flushed on SIGNED_IN
 *               and friends, and a failed exchange fires only INITIAL_SESSION.
 *
 * The failure branch is why the assertions below are run on BOTH branches. A
 * fix applied after a successful exchange only would leave the worse of the
 * two cases untouched, and would pass any gate that tested the happy path.
 *
 * WHAT MUST NOT BE SWEPT. #321's own constraint: a second tab mid-sign-in owns
 * a verifier slot that is still live, and a prefix sweep over
 * `*-code-verifier` would delete it. The fixtures here therefore always
 * include a PENDING flow whose slot must come through untouched — without
 * that case, "delete every verifier cookie" passes this file.
 *
 * WHAT THIS DOES NOT CLAIM. The residue is hygiene, not breakage: measured, a
 * retry after a failed exchange succeeds, because the next flow start
 * overwrites the fixed key. Nothing here asserts a sign-in is repaired.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import {
  CALLBACK_ROUTES,
  FAILING_CODE,
  FLOW_INDEX,
  LEGACY_VERIFIER,
  mintVerifierCookies,
  runCallback,
  slotFor,
} from "./helpers/callbackSession.mjs";

/** Two tabs. The second one started last, so the fixed key mirrors it. */
const PENDING = {
  flowId: "1f0c3a7d9b2e4f6081a3c5d7e9fb0213",
  verifier: "pending-tab-verifier-3f7a1c9e5b2d8046a1c3e5f709b2d4f6",
};
const SPENT = {
  flowId: "9e8d7c6b5a4938271605f4e3d2c1b0a9",
  verifier: "spent-flow-verifier-b1d3f5709a2c4e6880d2f4061a3c5e79",
};

/**
 * The Set-Cookie headers AS NEXT WILL EMIT THEM, not as the handler wrote them.
 *
 * This round-trip is the test, not a formality. When the request-scoped
 * `cookies()` store has mutations — what a SUCCESSFUL exchange produces, and a
 * failed one does not — Next merges it into the route handler's response by
 * parsing each `Set-Cookie` back into an object and re-serializing it. That
 * parser's `compact()` drops every falsy field, so a deletion expressed as
 * `maxAge: 0` alone loses the only attribute that made it a deletion, on
 * exactly the branch that matters most.
 *
 * Caught on a production build (`next build && next start`), where `/callback`
 * returned `sb-…-code-verifier=; Path=/` — emptied, not dropped — while the
 * same assertions read straight off the response object were green. Asserting
 * on the raw response object is therefore a check that cannot fail for this
 * defect, which is why this goes through the same `parseSetCookie` /
 * `stringifyCookie` pair Next uses. Deep import for the same reason the
 * helpers reach into `@supabase/ssr/dist`: the real thing, or nothing.
 *
 * APPLIED TO EVERY BRANCH ON PURPOSE, which is STRICTER than production —
 * there, the merge happens only when the cookie store was mutated, i.e. on the
 * success branch. Do not "correct" this to match: matching it would restore
 * the blind spot on the one branch where the defect actually shipped, and a
 * deletion that survives the round-trip unconditionally is the simpler
 * invariant to keep true.
 */
const { parseSetCookie, stringifyCookie } = createRequire(import.meta.url)(
  "next/dist/compiled/@edge-runtime/cookies",
);

function responseCookies(response) {
  const out = new Map();
  for (const original of response.headers.getSetCookie()) {
    const raw = stringifyCookie(parseSetCookie(original));
    const [pair, ...attrs] = raw.split(";").map((s) => s.trim());
    const name = pair.slice(0, pair.indexOf("="));
    const attr = (key) =>
      attrs.map((a) => a.split("=")).find(([k]) => k.toLowerCase() === key)?.[1];
    const maxAge = attr("max-age");
    const expires = attr("expires");
    out.set(name, {
      maxAge: maxAge === undefined ? undefined : Number(maxAge),
      expiresAt: expires === undefined ? undefined : Date.parse(expires),
    });
  }
  return out;
}

/** Expired for a browser: a past `Expires`, or a `Max-Age` of zero — surviving the merge. */
function deleted(response, name) {
  const c = responseCookies(response).get(name);
  if (!c) return false;
  return c.maxAge === 0 || (c.expiresAt !== undefined && c.expiresAt <= 0);
}

test("the fixture is the shape the fix turns on: slot and fixed key are byte-identical", async () => {
  const minted = await mintVerifierCookies([PENDING, SPENT]);
  const byName = new Map(minted.map(({ name, value }) => [name, value]));

  assert.equal(
    byName.size,
    4,
    `expected a slot per flow plus the index plus the fixed key, got ${[...byName.keys()].join(", ")}`,
  );
  assert.ok(
    byName.get(LEGACY_VERIFIER),
    "the library minted no fixed verifier cookie — every assertion below would be vacuous",
  );
  assert.equal(
    byName.get(slotFor(SPENT.flowId)),
    byName.get(LEGACY_VERIFIER),
    "the spent flow's slot must carry the same encoded value as the fixed key — value equality is how the sweep tells a spent flow from a live one",
  );
  assert.notEqual(
    byName.get(slotFor(PENDING.flowId)),
    byName.get(LEGACY_VERIFIER),
    "the pending flow's slot must differ, or the 'left alone' assertions prove nothing",
  );
});

for (const route of CALLBACK_ROUTES) {
  for (const branch of [
    { name: "a successful exchange", code: undefined },
    { name: "a FAILED exchange", code: FAILING_CODE },
  ]) {
    test(`${route.name} expires the spent verifier cookies after ${branch.name}`, async () => {
      const cookies = await mintVerifierCookies([PENDING, SPENT]);
      const { response, writes } = await runCallback(route, {
        ...(branch.code ? { code: branch.code } : {}),
        cookies,
      });

      assert.ok(
        response.headers.getSetCookie().length > 0,
        `${route.name} returned no Set-Cookie at all after ${branch.name} — the verifier cookies were never touched`,
      );

      assert.ok(
        deleted(response, slotFor(SPENT.flowId)),
        `the spent flow's slot ${slotFor(SPENT.flowId)} was not expired by ${route.name} after ${branch.name}`,
      );
      assert.ok(
        deleted(response, LEGACY_VERIFIER),
        `the fixed verifier key was not expired by ${route.name} after ${branch.name}`,
      );

      // The constraint from #321: a flow still in progress keeps its verifier.
      assert.ok(
        !responseCookies(response).has(slotFor(PENDING.flowId)),
        `${route.name} touched ${slotFor(PENDING.flowId)}, which belongs to a sign-in still in progress in another tab`,
      );
      // …and while that flow is live, its entry in the eviction ring must stay.
      assert.ok(
        !responseCookies(response).has(FLOW_INDEX),
        `${route.name} expired the flow index while a pending flow still needs it`,
      );

      // The residue is real: nothing on the library's own cookie path deletes
      // the slot. If this ever fails, the library started clearing it and this
      // whole file can go.
      const librarySlotWrites = writes.filter(
        ({ name }) => name === slotFor(SPENT.flowId),
      );
      assert.equal(
        librarySlotWrites.length,
        0,
        "@supabase/ssr now writes the flow slot itself — re-derive #321 before trusting this gate",
      );
    });
  }

  test(`${route.name} expires the flow index once no slot survives it`, async () => {
    const cookies = await mintVerifierCookies([SPENT]);
    const { response } = await runCallback(route, { cookies });

    assert.ok(
      deleted(response, slotFor(SPENT.flowId)),
      "the only flow's slot must go",
    );
    assert.ok(
      deleted(response, FLOW_INDEX),
      "with no slot left to reference, the index is pure residue and must go too",
    );
  });

  test(`${route.name} writes no verifier deletions when the browser sent none`, async () => {
    const { response } = await runCallback(route, { cookies: [] });

    for (const name of responseCookies(response).keys()) {
      assert.ok(
        !name.endsWith("-code-verifier"),
        `${route.name} expired ${name} on a request that carried no verifier cookies`,
      );
    }
  });
}
