/**
 * `live.file()` — the inbox workbench's half of `POST /api/gmail/sync` (#852).
 *
 * WHY THIS FILE EXISTS, AND WHY A BROWSER PASS COULD NOT REPLACE IT.
 * `/demo/scan` renders `<InboxWorkbench mode="demo">`, and `scanTransport("demo")`
 * returns a transport whose `file()` never fetches and never parses a body:
 *
 *     async file(items) {
 *       await delay(200);
 *       return { ok: true, status: 200, counts: { ..., scanned: items.length } };
 *     }
 *
 * So the edited lines are structurally unreachable from the only board a
 * visitor can load, and a regression in them leaves the demo output
 * byte-identical. A browser run of that page is a rendering check, not a
 * regression check — it would pass whatever `live.file()` did. The live path
 * needs an authed, Gmail-connected session, which no test harness here has.
 * Stubbing `fetch` is the instrument that actually reaches it.
 *
 * WHAT IT GUARDS. `file()` used to return on `!res.ok` BEFORE reading anything:
 *
 *     if (!res.ok) return { ok: false, status: res.status, counts: {} };
 *
 * so the backend's typed sentence — "3 filed and 1 queued of 4 scanned before
 * it failed; sync again to finish" (#643) — reached the dashboard, whose
 * `sync()` always read the body, and died here. One endpoint, two callers, one
 * of them blind.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { scanTransport } from "../../lib/gmail/transport.ts";

const TYPED_500 = "3 filed and 1 queued of 4 scanned before it failed; sync again to finish";

/** Drive `live.file()` against one canned response, restoring `fetch` after. */
async function fileAgainst(response) {
  const live = scanTransport("live");
  const realFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, init) => {
    seen.push({ url: String(url), init });
    return response();
  };
  try {
    return { result: await live.file([]), seen };
  } finally {
    globalThis.fetch = realFetch;
  }
}

test("a typed failure body survives the non-OK path", async () => {
  const { result, seen } = await fileAgainst(
    () => new Response(JSON.stringify({ detail: TYPED_500 }), { status: 500 }),
  );

  assert.equal(result.ok, false);
  assert.equal(result.status, 500);
  assert.deepEqual(result.counts, {}, "a failure must not publish counts");
  assert.deepEqual(
    result.body,
    { detail: TYPED_500 },
    "the backend's sentence was dropped at the last hop — this is #852",
  );
  // It really went to the endpoint under discussion, with the relay's own mode.
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "/api/gmail/sync");
  assert.equal(JSON.parse(seen[0].init.body).mode, "additive");
});

test("the success path still returns the counts, not the raw body", async () => {
  // THE REGRESSION RISK OF THE FIX ITSELF. `counts` is now sourced from a
  // variable read before the branch rather than from a fresh `await`, and the
  // demo page cannot exercise that. A `body ?? {}` that became `body` would
  // publish `null` here; one that re-read the stream would throw.
  const counts = { created: 3, updated: 1, applications: 2, scanned: 4 };
  const { result } = await fileAgainst(
    () => new Response(JSON.stringify(counts), { status: 200 }),
  );

  assert.equal(result.ok, true);
  assert.equal(result.status, 200);
  assert.deepEqual(result.counts, counts);
});

test("a body that is not JSON does not throw on either path", async () => {
  // A 502 from the edge, an HTML error page, a killed function: all arrive with
  // no JSON at all. `.catch(() => null)` is what keeps those from becoming an
  // unhandled rejection in the click handler.
  const { result: failed } = await fileAgainst(
    () => new Response("<html>gateway</html>", { status: 502 }),
  );
  assert.equal(failed.ok, false);
  assert.equal(failed.status, 502);
  assert.equal(failed.body, null);

  const { result: ok } = await fileAgainst(() => new Response("", { status: 200 }));
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.counts, {}, "an empty 200 must coalesce to {}, not to null");
});

test("the response body is consumed exactly once", async () => {
  // `res.json()` cannot be called twice — the second rejects. The fix reads the
  // body once BEFORE branching precisely so both paths can have it, and a
  // future edit that moves the read back inside a branch, or adds a second one,
  // is the failure this pins.
  const live = scanTransport("live");
  const realFetch = globalThis.fetch;
  let jsonCalls = 0;
  globalThis.fetch = async () => {
    const res = new Response(JSON.stringify({ detail: TYPED_500 }), { status: 500 });
    const realJson = res.json.bind(res);
    res.json = () => {
      jsonCalls += 1;
      return realJson();
    };
    return res;
  };
  try {
    const result = await live.file([]);
    assert.equal(jsonCalls, 1, `the body was read ${jsonCalls} times, not once`);
    assert.deepEqual(result.body, { detail: TYPED_500 });
  } finally {
    globalThis.fetch = realFetch;
  }
});
