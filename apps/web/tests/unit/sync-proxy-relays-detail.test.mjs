/**
 * `syncGmailPipeline` — the proxy hop itself, driven end to end (#848).
 *
 * The sibling files test the extractor and the rendered copy. This one tests
 * THE LINE THAT WAS WRONG: the proxy that never read the body it was handed.
 *
 *     if (!res.ok) return classifyBadResponse(res.status, res.headers);
 *     return { kind: "ok", result: (await res.json()) as GmailSyncOutcome };
 *
 * `server.ts` is server-only — it pulls `env.server` and `supabase/auth` — so
 * it is imported here through `renderTsx`'s stub map, which substitutes those
 * two specifiers and leaves the rest of the graph real. The function's own
 * body, `classifyBadResponse` included, is the shipped one; `fetch` is the
 * only other thing replaced, and it is an INPUT to the code under test, which
 * is where this helper's line is drawn.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { importTsx, stubModule } from "./helpers/renderTsx.mjs";

const TYPED_500 =
  "Could not record this sync. 3 filed and 1 queued of 4 scanned before it failed; sync again to finish.";

/** Load the real module with its two server-only dependencies substituted. */
async function proxy() {
  return importTsx("lib/gmail/server.ts", {
    stubs: {
      "@/lib/env.server": stubModule({
        serverEnv: () => ({ BACKEND_API_URL: "http://backend.test" }),
      }),
      "@/lib/supabase/auth": stubModule({ getAccessToken: async () => "a.jwt.token" }),
    },
  });
}

/** Install a one-shot `fetch` answering exactly once, and record the call. */
function answerWith(response) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return response;
  };
  return { calls, restore: () => { globalThis.fetch = original; } };
}

function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

test("a typed 500 arrives at the caller as the backend's own sentence", async () => {
  // THE case. MUTATION: restore the one-line `if (!res.ok) return
  // classifyBadResponse(...)` -> message is "Backend responded 500" and this reds.
  const { syncGmailPipeline } = await proxy();
  const stub = answerWith(jsonResponse(500, { detail: TYPED_500 }));
  try {
    const result = await syncGmailPipeline({ mode: "additive" });
    assert.equal(result.kind, "backend");
    assert.equal(result.message, TYPED_500);
    assert.equal(result.status, 500);
    assert.equal(stub.calls.length, 1, "the proxy did not reach the backend at all");
    assert.match(stub.calls[0].url, /\/gmail\/sync$/);
  } finally {
    stub.restore();
  }
});

test("a 500 whose body is not JSON keeps the status-derived line", async () => {
  // An HTML error page from the edge, a killed function, a truncated response.
  // MUTATION: drop the `.catch(() => null)` -> this throws and reds, which is
  // the real risk of reading a body that may not be there.
  const { syncGmailPipeline } = await proxy();
  const stub = answerWith(
    new Response("<html><body>502 Bad Gateway</body></html>", {
      status: 500,
      headers: { "Content-Type": "text/html" },
    }),
  );
  try {
    const result = await syncGmailPipeline({});
    assert.equal(result.kind, "backend");
    assert.equal(result.message, "Backend responded 500");
    assert.ok(!/undefined|null|\[object/.test(result.message));
  } finally {
    stub.restore();
  }
});

test("409 is still `not_connected`, decided before any body is read", async () => {
  // MUTATION: move the body read above the 409 check -> the kind changes and
  // this reds. 409 means Gmail is not connected and carries a stronger claim
  // than the generic failure copy; it must not be folded into `backend`.
  const { syncGmailPipeline } = await proxy();
  const stub = answerWith(jsonResponse(409, { detail: "not_connected" }));
  try {
    assert.deepEqual(await syncGmailPipeline({}), { kind: "not_connected" });
  } finally {
    stub.restore();
  }
});

test("a deferral keeps its wait and gains no sentence", async () => {
  // MUTATION: apply the detail to every kind -> `rate_limited` grows a
  // `message` field nothing renders, and the countdown copy silently wins
  // anyway. Red here, invisible in the product: exactly the shape of #848.
  const { syncGmailPipeline } = await proxy();
  const stub = answerWith(
    jsonResponse(429, { detail: "wait 30 seconds" }, { "Retry-After": "30" }),
  );
  try {
    assert.deepEqual(await syncGmailPipeline({}), {
      kind: "rate_limited",
      retryAfterSeconds: 30,
    });
  } finally {
    stub.restore();
  }
});

test("the success path still reads the body, once", async () => {
  // A control for the fix itself: a response body can be consumed ONLY ONCE,
  // so a failure-path read placed above the `res.ok` check would leave the
  // success path with a body already drained. This is the arm whose answer is
  // known, and it must keep working.
  const { syncGmailPipeline } = await proxy();
  const outcome = { created: 2, updated: 1, scanned: 4 };
  const stub = answerWith(jsonResponse(200, outcome));
  try {
    const result = await syncGmailPipeline({});
    assert.equal(result.kind, "ok");
    assert.deepEqual(result.result, outcome);
  } finally {
    stub.restore();
  }
});
