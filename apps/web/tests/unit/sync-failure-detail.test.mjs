/**
 * The backend's failure sentence surviving the Next proxy (#848).
 *
 * WHAT WAS BROKEN. `POST /gmail/sync` answers a failed cursor stamp with a
 * sentence naming what survived — "3 filed and 1 queued of 4 scanned before it
 * failed; sync again to finish" (#643). `syncGmailPipeline` classified every
 * non-OK response from `status` and `headers` alone:
 *
 *     if (!res.ok) return classifyBadResponse(res.status, res.headers);
 *     return { kind: "ok", result: (await res.json()) as GmailSyncOutcome };
 *
 * `res.json()` was only ever reached on the OK path. The sentence was
 * reachable by direct API consumers and by tests, and by nothing a user would
 * ever see.
 *
 * Each test below names the mutation that reds it, because a test that passes
 * against the broken proxy is worth nothing.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { backendSyncDetail, withBackendSyncDetail } from "../../lib/gmail/sync-detail.ts";

/** Verbatim from `backend/jobtracker/cloud/gmail_oauth.py` — the sentence the
 *  whole issue exists to deliver. Kept literal so a reword on either side
 *  shows up as a diff here rather than as silence. */
const TYPED_500 =
  "Could not record this sync. 3 filed and 1 queued of 4 scanned before it failed; sync again to finish.";

/** What `classifyBadResponse` builds from a 500 with no body read. */
const GENERIC = { kind: "backend", message: "Backend responded 500", status: 500 };

// --- the extractor ----------------------------------------------------------

test("the typed 500's own sentence is what comes out", () => {
  // MUTATION: return null unconditionally -> red. This is the case the issue is.
  assert.equal(backendSyncDetail({ detail: TYPED_500 }), TYPED_500);
});

test("a body with nothing to quote yields null, so the caller keeps its generic", () => {
  // MUTATION: return String(body?.detail) -> red on every row here, and each
  // row is a shape a real failure actually produces.
  for (const body of [
    null, // res.json() threw: an HTML error page, a 502 from the edge
    undefined,
    {}, // the client transport's own `.catch(() => ({}))` fallback
    { message: "nope" }, // not the field this proxy emits
    [{ loc: ["body"], msg: "bad" }], // a pydantic validation error is a LIST
    { detail: "" },
    { detail: "   " }, // present, falsy-adjacent, and not a message
    { detail: 500 },
    { detail: { nested: "object" } }, // `String()` here shipped "[object Object]" once (#490)
    "a bare string body",
    42,
  ]) {
    assert.equal(
      backendSyncDetail(body),
      null,
      `unusable body was quoted to the reader: ${JSON.stringify(body)}`,
    );
  }
});

test("a quotable detail is trimmed, never blanked", () => {
  // MUTATION: drop the .trim() -> the rendered line opens with a stray space
  // after its separator. Cheap to get wrong, invisible in review.
  assert.equal(backendSyncDetail({ detail: `  ${TYPED_500}  ` }), TYPED_500);
});

// --- the proxy's decision ---------------------------------------------------

test("the backend failure carries the backend's sentence, replacing the generic", () => {
  // MUTATION: `return failure` unconditionally -> red. This IS the fix.
  const out = withBackendSyncDetail(GENERIC, { detail: TYPED_500 });
  assert.equal(out.message, TYPED_500);
  assert.equal(out.status, 500, "the status a reader can quote must survive");
  assert.equal(out.kind, "backend");
});

test("an unquotable body leaves the status-derived line intact", () => {
  // MUTATION: `{...failure, message: detail ?? ""}` -> red. A failure with no
  // text at all is worse than a generic one: the alert renders an empty
  // sentence and the reader has nothing to report.
  for (const body of [null, {}, { detail: "  " }]) {
    assert.deepEqual(withBackendSyncDetail(GENERIC, body), GENERIC);
  }
});

test("the kinds rendered from their kind are never rewritten", () => {
  // MUTATION: drop the `kind !== "backend"` guard -> red on all three. A
  // sentence written into `auth` or `rate_limited` lands in a field nothing
  // reads, which is exactly the shape of the bug being fixed.
  const others = [
    { kind: "auth", status: 401 },
    { kind: "unavailable" },
    { kind: "rate_limited", retryAfterSeconds: 60 },
  ];
  for (const failure of others) {
    assert.deepEqual(
      withBackendSyncDetail(failure, { detail: TYPED_500 }),
      failure,
      `${failure.kind} was rewritten with a message nothing renders`,
    );
  }
});

test("the input is not mutated in place", () => {
  // MUTATION: `failure.message = detail; return failure` -> red. React state
  // holds these; an in-place write is a stale-render bug that would not show
  // up in any assertion about the returned value.
  const original = { ...GENERIC };
  withBackendSyncDetail(original, { detail: TYPED_500 });
  assert.deepEqual(original, GENERIC);
});

// --- what the DASHBOARD may render, given the status ------------------------

test("the route's machine tokens never reach the reader as prose", async () => {
  // THE REGRESSION THIS GUARD EXISTS FOR. `withBackendSyncDetail` protects the
  // proxy's `message`, and that protection does not survive the wire: the route
  // flattens every failure kind into the same `detail` key. Measured before the
  // guard, rendering the route's real answers through the failure note:
  //
  //   429 -> sync failed · anything it filed or removed before stopping stays
  //          that way · rate_limited try again
  //
  // MUTATION: `return backendSyncDetail(body)` unconditionally -> red on all
  // five. Each row is verbatim what `app/api/gmail/sync/route.ts` emits.
  const { proxySyncDetail } = await import("../../lib/gmail/sync-detail.ts");
  for (const [status, body] of [
    [401, { detail: "unauthenticated" }],
    [401, { detail: "auth" }],
    [403, { detail: "auth" }],
    [429, { detail: "rate_limited" }],
    [503, { detail: "unavailable" }],
    [409, { detail: "not_connected" }],
  ]) {
    assert.equal(
      proxySyncDetail(status, body),
      null,
      `a ${status} would render the machine token "${body.detail}" as the backend's sentence`,
    );
  }
});

test("the statuses that carry prose still carry it", async () => {
  // MUTATION: add 500 to RENDERED_FROM_STATUS -> red, and #848 is back. The
  // guard must be narrow: 500 is the typed stamp failure and 502 is the
  // proxy's own status-derived line, and both are for the reader.
  const { proxySyncDetail } = await import("../../lib/gmail/sync-detail.ts");
  assert.equal(proxySyncDetail(500, { detail: TYPED_500 }), TYPED_500);
  assert.equal(
    proxySyncDetail(502, { detail: "Backend responded 502" }),
    "Backend responded 502",
  );
});

/**
 * THE GUARD IS A HAND-MAINTAINED COPY OF A PARTITION IT DOES NOT IMPORT.
 *
 * `RENDERED_FROM_STATUS` is exactly the complement of the one `GmailFailure`
 * arm that carries prose. `classifyBadResponse` in `lib/gmail/server.ts`
 * partitions every non-OK status:
 *
 *     401 | 403 -> auth           429 -> rate_limited
 *     503        -> unavailable   everything else -> backend
 *
 * and only `backend` reaches the route's `{detail: result.message}`. So a
 * status is suppressible IF AND ONLY IF `classifyBadResponse` gives it a
 * non-backend kind (409 aside, which is raised before the classifier and
 * renders its own stronger sentence).
 *
 * Nothing enforced that correspondence. Moving 503 into the `backend` arm, or
 * adding a branch for a new status, leaves the guard stale and silently wrong —
 * and since #852 there are TWO renderers reading it, so a stale guard now
 * costs two surfaces instead of one. That is the scope increase #852 created,
 * which is why the pin lands with it.
 *
 * NOT CIRCULAR: the expected set is read out of `server.ts`'s SOURCE, and
 * checked against `proxySyncDetail`'s observable behaviour. It never compares
 * `RENDERED_FROM_STATUS` to itself.
 *
 * AND NOT BLIND TO GAINS: a source scan that simply collects branches passes
 * when a NEW branch appears that it does not understand, because there is
 * merely one more status it never asks about. The `deepEqual` on the whole set
 * is what makes an added branch red — the author is then forced to decide
 * whether the new status belongs in the guard.
 */
test("every status classifyBadResponse diverts from `backend` is suppressed", async () => {
  const { proxySyncDetail } = await import("../../lib/gmail/sync-detail.ts");
  const server = readFileSync(new URL("../../lib/gmail/server.ts", import.meta.url), "utf8");

  const body = server.slice(
    server.indexOf("function classifyBadResponse"),
    server.indexOf("const RETRY_AFTER_FALLBACK_SECONDS"),
  );
  assert.ok(body.includes("kind: \"backend\""), "classifyBadResponse was not located");

  // Every numeric literal the function compares `status` against. Those are its
  // diversions; whatever it does not name falls through to `backend`.
  const diverted = [...body.matchAll(/status === (\d{3})/g)].map((m) => Number(m[1]));

  assert.deepEqual(
    [...new Set(diverted)].sort(),
    [401, 403, 429, 503],
    "classifyBadResponse's partition changed — RENDERED_FROM_STATUS in " +
      "lib/gmail/sync-detail.ts is a copy of it and must be revisited",
  );

  for (const status of diverted) {
    assert.equal(
      proxySyncDetail(status, { detail: "a machine token" }),
      null,
      `${status} is diverted from the backend arm, so its body is a machine token`,
    );
  }

  // The converse, and the half that keeps the guard NARROW: a status the
  // classifier leaves alone reaches `backend`, whose detail is the reader's.
  for (const status of [500, 502, 504]) {
    assert.ok(!diverted.includes(status), `${status} is no longer a backend status`);
    assert.equal(proxySyncDetail(status, { detail: "the backend's sentence" }), "the backend's sentence");
  }
});
