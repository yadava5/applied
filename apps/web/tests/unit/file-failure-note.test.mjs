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
    /\{ kind: "status", status: res\.status \}/,
    /\{ kind: "unreachable" \}/,
  ]) {
    assert.match(source, kind, `no failure branch hands the builder ${kind}`);
  }
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
