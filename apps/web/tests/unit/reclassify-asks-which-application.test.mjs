/**
 * "Which application is this about?" — the predicate, the wire, and the one
 * renderer, for BOTH surfaces that put the question (#554, #560).
 *
 * THE DEFECT THESE GUARD, measured against the real endpoint before the fix:
 *
 *     rows                      -> [1, 2]        two Northwind applications
 *     unlinked reclassify       -> filed on 1    the oldest
 *     board -> [(2,'Northwind','applied'), (1,'Northwind','interviewing')]
 *
 * Row 1 was moved to `interviewing` by a message nobody had said was about it.
 * `ReclassifyControl` sent a literal `null` in the `application_id` position —
 * it never asked, so it never had an answer to send — and with no link to
 * outrank it the backend's `_pick_application` rule 4 tie-broke onto the
 * employer's oldest row. The picker is the fix, and this file is what says the
 * answer reaches the wire.
 *
 * WHAT IS AND IS NOT COVERED HERE, stated because the gap matters more than
 * the coverage. `asksWhichApplication` and `classifyDecisionBody` are executed
 * directly, so the hop that carries the answer from a surface's state into the
 * request body is a real gate on the queue's path and the ledger's path alike.
 * What no unit test in this repo can execute is a `.tsx` component that uses
 * hooks — `ReclassifyControl` reaches for `useRouter`, so `renderTsx` cannot
 * load it. The queue's component wiring is gated by
 * `tests/e2e/review-picker.spec.ts` on `/demo/shell`; the ledger's has no
 * public twin (the filed view is behind a session), so its call site is held by
 * the SOURCE TRIPWIRE at the bottom of this file and by a browser pass, and it
 * is labelled as a tripwire rather than counted as a gate.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  LIFECYCLE_ANSWERS,
  asksWhichApplication,
  canSubmitReview,
  classifyDecisionBody,
} from "../../lib/dashboard/review.ts";
import { importTsx, markup, readSource } from "./helpers/renderTsx.mjs";

/** Two applications at one employer — the smallest board with a question on it. */
const TWO = [
  { id: 41, company: "Northwind", position: "Backend Engineer", status: "applied" },
  { id: 42, company: "Northwind", position: "Platform Engineer", status: "applied" },
];
const ONE = [TWO[0]];
const THREE = [
  ...TWO,
  { id: 43, company: "Northwind", position: "Data Engineer", status: "applied" },
];

// --- The three cases the fix is defined by -----------------------------------

test("case 1 — a message already filed against a row is not asked anything", () => {
  for (const candidates of [TWO, THREE]) {
    assert.equal(
      asksWhichApplication({ category: "rejection", candidates, linkedApplicationId: 42 }),
      false,
      "a linked message has an answer already: its link outranks the backend's " +
        "tie-break (#546/#548), and offering 'none of these' over a message that " +
        "is already tracked is a new way to scatter a record",
    );
  }
  // And the link is not merely un-asked, it is un-sendable: a pick left over
  // from before the row was linked must not ride along as an answer.
  const body = classifyDecisionBody({
    category: "rejection",
    candidates: THREE,
    linkedApplicationId: 42,
    assignment: 43,
  });
  assert.equal(body.application_id, undefined);
  assert.equal(body.none_of_these, undefined);
});

test("case 2 — an unlinked message at a single-application employer is not asked", () => {
  assert.equal(
    asksWhichApplication({ category: "rejection", candidates: ONE, linkedApplicationId: null }),
    false,
    "one option is not a question, and the tie-break has the right row to " +
      "land on anyway",
  );
  assert.equal(
    asksWhichApplication({ category: "rejection", candidates: [], linkedApplicationId: null }),
    false,
  );
  const body = classifyDecisionBody({
    category: "rejection",
    candidates: ONE,
    linkedApplicationId: null,
    assignment: 41,
  });
  assert.equal(
    body.application_id,
    undefined,
    "nobody was asked, so nothing may be sent as their answer",
  );
});

test("case 3 — an unlinked message at a multi-application employer is asked, and the answer travels", () => {
  const decision = {
    category: "rejection",
    candidates: TWO,
    linkedApplicationId: null,
  };
  assert.equal(asksWhichApplication(decision), true);

  const picked = classifyDecisionBody({ ...decision, assignment: 42 });
  assert.equal(picked.application_id, 42, "the row the user picked must reach the wire");
  assert.equal(picked.none_of_these, undefined);

  const none = classifyDecisionBody({ ...decision, assignment: "none" });
  assert.equal(none.none_of_these, true);
  assert.equal(
    none.application_id,
    undefined,
    "'none of these' cannot travel as an absent id — absent means nobody asked, " +
      "which the backend answers with the tie-break",
  );

  // Unanswered is unsendable, and that gate is the caller's — asserted here
  // because it is the only thing that makes an unchecked radio mean anything.
  assert.equal(canSubmitReview("rejection", true, null), false);
  assert.equal(canSubmitReview("rejection", true, "none"), true);
  assert.equal(canSubmitReview("rejection", true, 42), true);
});

// --- Directional controls ----------------------------------------------------

test("the threshold has a case sitting ON it", () => {
  const at = (candidates) =>
    asksWhichApplication({ category: "rejection", candidates, linkedApplicationId: null });
  assert.equal(at(ONE), false, "widened to >= 1: a single row is not a question");
  assert.equal(at(TWO), true, "narrowed to >= 3: TWO rows is the smallest ambiguous board");
  assert.equal(at(THREE), true);
});

test("every lifecycle category asks, individually", () => {
  assert.deepEqual(
    [...LIFECYCLE_ANSWERS].sort(),
    ["assessment", "interview", "offer", "rejection"],
    "a set whose members are not asserted individually is a set with one member",
  );
  for (const category of ["interview", "assessment", "offer", "rejection"]) {
    assert.equal(
      asksWhichApplication({ category, candidates: TWO, linkedApplicationId: null }),
      true,
      `${category} answers an application that already exists, so which one is a question`,
    );
  }
});

test("a category that opens a row, or opens nothing, asks nothing", () => {
  for (const category of ["applied", "other", ""]) {
    assert.equal(
      asksWhichApplication({ category, candidates: THREE, linkedApplicationId: null }),
      false,
      `${category || "(placeholder)"} must not put the picker — without this ` +
        "control, 'always ask' satisfies the whole loop",
    );
  }
});

test("the rest of the body still crosses the shared builder", () => {
  const body = classifyDecisionBody({
    category: "rejection",
    company: "  Northwind  ",
    candidates: TWO,
    linkedApplicationId: null,
    assignment: 41,
    message: { sender_email: "talent@northwind.com", received_at: "2026-05-25T09:00:00Z" },
    confirmNewCompany: true,
  });
  assert.equal(body.company, "Northwind");
  assert.equal(body.confirm_new_company, true);
  assert.equal(body.message.sender_email, "talent@northwind.com");
  assert.equal(body.application_id, 41);
});

// --- One question, one renderer ---------------------------------------------

test("the picker renders one option per candidate plus the mint option, and pre-selects nothing", async () => {
  const { ApplicationPicker } = await importTsx("components/review/ApplicationPicker.tsx");
  const html = markup(
    ApplicationPicker({
      name: "reclass-assign-m-1",
      candidates: TWO,
      assignment: null,
      onChange: () => {},
    }),
  );

  assert.match(html, /which application is this about\?/);
  assert.match(html, /Backend Engineer/);
  assert.match(html, /Platform Engineer/);
  assert.match(html, /none of these — track it as a new application/);
  assert.equal(
    (html.match(/type="radio"/g) ?? []).length,
    3,
    "two candidates and the 'none of these' option",
  );
  assert.doesNotMatch(
    html,
    /checked/,
    "nothing is pre-selected: the option that DISCARDS the question used to be " +
      "the default, and that is the defect #554 measured",
  );

  const answered = markup(
    ApplicationPicker({
      name: "reclass-assign-m-1",
      candidates: TWO,
      assignment: 42,
      onChange: () => {},
    }),
  );
  // React emits the attributes in that order; what matters is that the checked
  // one is the row the caller says was picked, and not merely that something is.
  assert.match(answered, /checked=""[^>]*value="42"/);
  assert.equal((answered.match(/checked/g) ?? []).length, 1, "exactly one answer at a time");
});

test("the question is set in the text face, not in mono", () => {
  const source = readSource("components/review/ApplicationPicker.tsx");
  const legend = source.slice(source.indexOf("<legend"), source.indexOf("</fieldset>"));
  assert.doesNotMatch(
    legend,
    /font-mono/,
    "the question and its options are prose. Mono means 'this is a machine " +
      "value' — a confidence, a date, an id — and a picker that reads as " +
      "console output is the standing complaint about this codebase",
  );
});

test("both surfaces render the question through that one component", () => {
  for (const file of [
    "components/dashboard/ReviewQueue.tsx",
    "components/mail/ReclassifyControl.tsx",
  ]) {
    const source = readSource(file);
    assert.match(source, /<ApplicationPicker\b/, `${file} must not hand-roll the question`);
    assert.doesNotMatch(
      source,
      /which application is this about/,
      `${file} carries its own wording of a question that has one wording`,
    );
  }
});

// --- Source tripwire, and it is labelled as one ------------------------------

test("TRIPWIRE: ReclassifyControl sends the user's answer, not a literal null", () => {
  // NOT A GATE, and the difference is the point. The behaviour this asserts —
  // "the component puts its own `assignment` state into the decision" — lives
  // in a hooks component that `renderTsx` cannot load and whose only rendered
  // surfaces are behind a Supabase session, so nothing in CI executes it. A
  // tripwire that reads the source is what is available, and reading the
  // source is exactly how #560 was misdiagnosed in the first place: it is
  // worth having and it is not worth trusting. The executable half is
  // `classifyDecisionBody` above; the human half is the browser pass.
  const source = readSource("components/mail/ReclassifyControl.tsx");
  const call = source.slice(
    source.indexOf("classifyDecisionBody({"),
    source.indexOf("const outcome ="),
  );
  assert.ok(call.includes("classifyDecisionBody({"), "the shared builder must build the body");
  for (const field of ["candidates,", "linkedApplicationId,", "assignment,"]) {
    assert.ok(
      call.includes(field),
      `the decision must carry ${field} — passing a literal in that position is ` +
        "the shape of #560, and a hard-coded null there means the picker is decoration",
    );
  }
  assert.doesNotMatch(call, /assignment:\s*null/);
});

test("TRIPWIRE: the filed ledger hands its control the employer's rows", () => {
  // The mount is what makes the question reachable at all: a control that asks
  // correctly, handed `[]` by every mount, asks nothing. The scan mount is NOT
  // asserted here on purpose — it passes `[]` deliberately, and pinning that in
  // a test would red on the day someone gives the scan a board, which is an
  // improvement, not a regression. What holds the scan mount honest is that
  // `candidates` is a REQUIRED prop: a new mount cannot compile without stating
  // its answer, and that is a typecheck, not a regex.
  const source = readSource("components/mail/FiledMailList.tsx");
  const mount = source.slice(source.indexOf("<ReclassifyControl"), source.indexOf("</li>"));
  assert.match(mount, /candidates=\{reviewCandidates\(/);
  assert.match(
    mount,
    /linkedApplicationId=\{m\.application_id\}/,
    "the ledger's rows are mostly LINKED, and a link is what stops the question " +
      "being asked where it has already been answered",
  );
});
