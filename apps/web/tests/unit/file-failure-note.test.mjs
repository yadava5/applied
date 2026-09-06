/**
 * Unit tests for the inbox file bar's FAILURE copy (`lib/gmail/file-outcome.ts`).
 *
 * THE SENTENCE THESE PIN REPLACED A FALSE ONE (#604). The bar used to say
 * "Couldn't file these (500) — nothing was changed." and, when the request
 * threw, "Couldn't reach the server — nothing was filed." `POST /gmail/sync`
 * commits the filed mail inside the merge and only then stamps the cursor, so
 * every failure after that commit — the migrate-window `UndefinedColumn` that
 * surfaced it, a stamp deadlock, a dropped connection, a function killed on its
 * ceiling — leaves mail filed and tells the reader nothing changed. The backend
 * half of this is `backend/tests/test_gmail_sync_failure_keeps_the_filed_mail.py`,
 * which runs the endpoint against a database missing those columns and asserts
 * the mail rows are there.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { fileFailureNote } from "../../lib/gmail/file-outcome.ts";

/** The clause every failure branch must carry. */
const KEPT = /anything filed before the failure stays that way/;

/**
 * The shape the whole issue is about: the merge committed, the stamp raised,
 * the proxy answered 500. Mail IS filed.
 */
test("a failed file with mail already persisted does not claim nothing changed", () => {
  const note = fileFailureNote({ kind: "status", status: 500 });

  assert.equal(note, "Couldn't file these (500) — anything filed before the failure stays that way.");
  assert.match(note, KEPT);
  assert.doesNotMatch(
    note,
    /nothing was changed/,
    "the 500 branch claims nothing changed again — the merge commits before the stamp",
  );
  // Still a failure, and still names the status the reader can quote.
  assert.match(note, /^Couldn't file these \(500\)/);
});

/**
 * The same lie with a different trigger, and this one needs no schema drift: a
 * request whose response never arrives may have filed everything.
 */
test("an unreachable server does not claim nothing was filed", () => {
  const note = fileFailureNote({ kind: "unreachable" });

  assert.equal(
    note,
    "Couldn't reach the server — anything filed before the failure stays that way.",
  );
  assert.match(note, KEPT);
  assert.doesNotMatch(
    note,
    /nothing was filed/,
    "the network branch claims nothing was filed again — a lost response is not a lost write",
  );
  assert.match(note, /^Couldn't reach the server/);
});

/**
 * Both corrected branches share the TAIL — that is the one true clause — and
 * must not share the LEAD. A builder that collapsed them would tell a reader
 * whose request never left the browser that the server answered with a status.
 */
test("the two corrected notes agree on the tail and differ on the cause", () => {
  const status = fileFailureNote({ kind: "status", status: 502 });
  const unreachable = fileFailureNote({ kind: "unreachable" });

  assert.notEqual(status, unreachable, "the two failures render the same sentence");
  assert.equal(
    status.split(" — ")[1],
    unreachable.split(" — ")[1],
    "the two failures make different claims about what survived",
  );
  assert.notEqual(
    status.split(" — ")[0],
    unreachable.split(" — ")[0],
    "the two failures name the same cause",
  );
  // The status is read off the argument, not baked in — a same-typed swap for
  // another number must change the sentence.
  assert.match(status, /\(502\)/);
  assert.doesNotMatch(status, /\(500\)/);
});

/**
 * 409 LEGITIMATELY KEEPS THE STRONGER CLAIM, and this test exists so nobody
 * "corrects" it to match the other two. 409 means "Gmail is not connected" on
 * this endpoint (`SyncAlreadyRunning` took 429 rather than reuse it), and the
 * only place `POST /gmail/sync` raises it is the first page of a server-side
 * scan coming back empty — before anything is classified and before either
 * merge runs.
 */
test("the not-connected refusal may still say nothing was filed", () => {
  const note = fileFailureNote({ kind: "not-connected" });

  assert.equal(note, "Gmail isn't connected — nothing was filed.");
  assert.doesNotMatch(note, KEPT, "the 409 branch was flattened into the generic one");
});

/**
 * The component's source with its COMMENTS removed.
 *
 * The tripwire below greps for the sentence this change deleted, and that grep
 * is a false positive waiting to happen: the correct thing for a comment beside
 * the fix to do is QUOTE the wording it replaced, and `InboxWorkbench.tsx` does
 * exactly that. A gate that reds because the code explains itself is an
 * inverted gate — red when the product is right — and this repo has the scar.
 * So the assertion runs against what the component can RENDER.
 *
 * Deliberately naive, and bounded by that: `//` is only stripped when it opens
 * a line, so a `https://` inside a string is safe, and the positive control in
 * the tripwire proves both that something was removed and that the code around
 * it survived.
 */
function withoutComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
}

/**
 * WIRING. Everything above passes against a module nothing imports, which is
 * exactly how the lie would survive its own fix.
 */
test("TRIPWIRE: the workbench renders the builder and holds neither old literal", () => {
  const raw = readFileSync(
    new URL("../../components/gmail/InboxWorkbench.tsx", import.meta.url),
    "utf8",
  );
  const source = withoutComments(raw);

  // The wiring first, so that a component which never adopted the builder reds
  // on THAT and not on a stripper control which is only meaningful once it has.
  assert.match(
    source,
    /import \{ fileFailureNote \} from "@\/lib\/gmail\/file-outcome"/,
    "InboxWorkbench does not import the failure-note builder",
  );

  // POSITIVE CONTROL for the stripper, and it is not decoration: if
  // `withoutComments` silently returned the whole file, or ate it, the
  // `doesNotMatch` below would be measuring the wrong string and would still be
  // green. The component quotes the deleted sentence in a comment beside the
  // fix, so this trio is exercised on every run.
  assert.match(raw, /nothing was changed/, "the component no longer explains what it replaced");
  assert.doesNotMatch(source, /nothing was changed/, "withoutComments did not strip a comment");
  assert.match(source, /fileFailureNote\(/, "withoutComments ate the code as well");
  // All THREE failure kinds are handed to it — the 409, the generic status and
  // the thrown request. Asserting the kinds rather than a call count is what
  // makes a re-inlined branch visible: dropping one from the component leaves
  // the builder imported and the other two still calling it.
  for (const kind of [
    /\{ kind: "not-connected" \}/,
    /kind: "status",\s*\n\s*status: res\.status,/,
    /\{ kind: "unreachable" \}/,
  ]) {
    assert.match(source, kind, `no failure branch hands the builder ${kind}`);
  }
  // #852: the status branch must build its detail through the ROUTE-scoped
  // guard, not from the raw body. Reading `res.body` directly here would render
  // "· rate_limited" on a 429 — worse than the generic it replaced. Pinned as
  // the whole expression, because a substring (`proxySyncDetail(`) survives
  // `proxySyncDetail(res.status, res.body) ?? someRawFallback`.
  assert.match(
    source,
    /detail: proxySyncDetail\(res\.status, res\.body\),/,
    "the workbench does not build its file-failure detail through proxySyncDetail",
  );
  // Neither old literal can be RENDERED from here again. `nothing was filed`
  // is still a sentence this product says — the 409 branch keeps it — but it
  // says it from `file-outcome.ts`, so a copy of it in the component means one
  // of the two corrected branches was re-inlined.
  assert.doesNotMatch(
    source,
    /nothing was filed/,
    "the network branch's false sentence is back in InboxWorkbench",
  );
});

/**
 * #852 — THE BACKEND'S SENTENCE REACHES THIS SURFACE, AND THE VALENCE SURVIVES.
 *
 * `POST /gmail/sync` answers a failed cursor stamp with "3 filed and 1 queued of
 * 4 scanned before it failed; sync again to finish" (#643). #848 carried that to
 * the dashboard. The workbench's `file()` returned on `!res.ok` before reading
 * anything, so the same endpoint told one caller what survived and the other
 * nothing — one endpoint, two callers, one of them blind.
 *
 * The risk being pinned is NOT that the detail is missing. It is that the detail
 * arrives and eats the lead: a note reading "3 filed and 1 queued of 4 scanned"
 * has turned a 500 into a success report.
 */
test("the backend's sentence is appended to the failure, never substituted for it", () => {
  const TYPED = "3 filed and 1 queued of 4 scanned before it failed; sync again to finish";
  const note = fileFailureNote({ kind: "status", status: 500, detail: TYPED });

  assert.equal(
    note,
    `Couldn't file these (500) — anything filed before the failure stays that way. · ${TYPED}`,
  );
  // The three properties that make it an append rather than a replacement, each
  // able to fail on its own.
  assert.match(note, /^Couldn't file these \(500\)/, "the failure lead was displaced");
  assert.match(note, KEPT, "the surviving-work clause was dropped for the detail");
  assert.ok(note.indexOf(TYPED) > note.search(KEPT), "the detail precedes the clause it qualifies");
});

/**
 * The guard that makes the append safe, exercised through THIS surface's
 * renderer rather than only through `proxySyncDetail`'s own unit tests.
 *
 * `app/api/gmail/sync/route.ts` flattens every failure kind into one `detail`
 * key, so a 429 arrives as `{detail:"rate_limited"}`. Rendering that gives
 * "Couldn't file these (429) — … · rate_limited": a machine token shown to a
 * person as prose, worse than the generic line it replaced.
 */
test("a status the route flattens to a machine token renders no detail", async () => {
  const { proxySyncDetail } = await import("../../lib/gmail/sync-detail.ts");

  for (const [status, token] of [
    [401, "unauthenticated"],
    [403, "auth"],
    [429, "rate_limited"],
    [503, "unavailable"],
  ]) {
    const detail = proxySyncDetail(status, { detail: token });
    const note = fileFailureNote({ kind: "status", status, detail });

    assert.equal(detail, null, `${status} let a machine token through`);
    assert.equal(
      note,
      `Couldn't file these (${status}) — anything filed before the failure stays that way.`,
    );
    assert.doesNotMatch(note, new RegExp(token), `${status} rendered "${token}" as prose`);
  }
});

/** A body with nothing quotable leaves the sentence exactly as it was. */
test("an unquotable body leaves the generic note byte-identical", async () => {
  const { proxySyncDetail } = await import("../../lib/gmail/sync-detail.ts");
  const generic = fileFailureNote({ kind: "status", status: 500 });

  for (const body of [null, undefined, {}, { detail: "" }, { detail: "   " }, { detail: 7 }, []]) {
    assert.equal(
      fileFailureNote({ kind: "status", status: 500, detail: proxySyncDetail(500, body) }),
      generic,
      `a body of ${JSON.stringify(body) ?? "undefined"} changed the generic note`,
    );
  }
});

/**
 * The 409 branch cannot acquire a detail. It renders "nothing was filed", and an
 * appended "3 filed…" would contradict the sentence it is attached to. The type
 * forbids it — `detail` lives only on the `status` kind — and this asserts the
 * rendered result rather than trusting `tsc`, because the unit runner strips
 * types and would not catch a `switch` that read `failure.detail` unguarded.
 */
test("the not-connected branch renders no detail even when one is smuggled in", () => {
  const note = fileFailureNote({
    kind: "not-connected",
    detail: "3 filed and 1 queued of 4 scanned",
  });

  assert.equal(note, "Gmail isn't connected — nothing was filed.");
});

/**
 * TRANSPORT WIRING. Everything above passes against a `file()` that still
 * returns before reading the body — which is the bug. This is the #848 lesson
 * repeating verbatim: a `detail` threaded through and rendered nowhere
 * typechecked, passed all 18 tests and the full suite, because no test asserted
 * the producer produced it.
 */
test("TRIPWIRE: file() reads the body on the non-OK path", () => {
  const source = withoutComments(
    readFileSync(new URL("../../lib/gmail/transport.ts", import.meta.url), "utf8"),
  );

  // The read must come BEFORE the branch: `res.json()` cannot be consumed
  // twice, so a second read placed after `!res.ok` would resolve to a rejected
  // promise and the detail would be silently null on every failure.
  const early = source.indexOf("const body = await res.json()");
  const branch = source.indexOf("if (!res.ok) return { ok: false");
  assert.ok(early > 0, "file() no longer reads the response body");
  assert.ok(branch > 0, "file()'s non-OK early return changed shape — re-read this pin");
  assert.ok(early < branch, "the body is read after the non-OK return, so it is never read");

  assert.match(
    source,
    /if \(!res\.ok\) return \{ ok: false, status: res\.status, counts: \{\}, body \};/,
    "the non-OK return does not carry the body",
  );
});
