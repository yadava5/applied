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
 * WHAT IS COVERED HERE. `asksWhichApplication` and `classifyDecisionBody` are
 * executed directly, so the hop that carries the answer from a surface's state
 * into the request body is a real gate on the queue's path and the ledger's
 * path alike. The queue's component wiring is gated by
 * `tests/e2e/review-picker.spec.ts` on `/demo/shell`.
 *
 * The ledger has no public twin — the filed view is behind a session, and every
 * session-gated e2e test in this repo skips (`tests/e2e/session.ts`) — so its
 * mount used to be held by a SOURCE TRIPWIRE, a regex asserting that the right
 * call appeared in the file. That was defeatable and was measured to be: both
 * `board.slice(0, 1)` at the mount and `const showPicker = false` in the
 * control silence the question permanently, and both left the whole web suite,
 * `tsc` and `eslint` green with the tripwire still matching. The bottom of this
 * file now MOUNTS the real ledger over a real-shaped listing row, clicks
 * through it, and looks for the question on the page.
 *
 * The other half of "one rule" is cross-language: which board rows belong to a
 * message's employer is decided in TypeScript here and in Python there, and the
 * two are held together by `tests/fixtures/employer-token-match.json`, which
 * `backend/tests/test_one_employer_rule.py` executes as well.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  LIFECYCLE_ANSWERS,
  asksWhichApplication,
  canSubmitReview,
  classifyDecisionBody,
  matchesEmployerToken,
  reviewCandidates,
} from "../../lib/dashboard/review.ts";
import { React, importApp, mount } from "./helpers/mountApp.mjs";
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

// --- The question has to be REACHABLE on the mail it exists for --------------

test("a board name longer than the mail's is still the same employer", () => {
  // THE DIVERGENCE, AND IT IS THE ORDINARY CASE. A board row stores the human
  // display name ("Northwind Traders"); the backend resolves mail to a TOKEN
  // built from the first word of what the mail says ("northwind"). Asking
  // whether the message's text CONTAINS the row's name answers no, while the
  // backend's `_company_rows` matches it on the leading word — so the ledger
  // showed no question and the endpoint moved a live application anyway.
  // Measured against the real endpoint on this exact fixture:
  //
  //     board  [(1 "Northwind Traders" applied), (2 "Northwind Traders" applied)]
  //     POST   {"category": "interview"}  ->  application_id 1, interviewing
  //     ledger candidates 0 -> asks nothing
  const LONGER = [
    { id: 51, company: "Northwind Traders", position: "Backend Engineer", status: "applied" },
    { id: 52, company: "Northwind Traders", position: "Platform Engineer", status: "applied" },
  ];
  const relay = {
    sender_email: "no-reply@greenhouse.io",
    sender_name: "Northwind Hiring Team",
    subject: "Update on your application",
    employer_token: "northwind",
  };
  assert.equal(
    reviewCandidates(relay, LONGER).length,
    2,
    "a stored name longer than the token is the same employer — the backend " +
      "matches it and files onto it, so the question must offer it",
  );
  assert.equal(
    asksWhichApplication({
      category: "rejection",
      candidates: reviewCandidates(relay, LONGER),
      linkedApplicationId: null,
    }),
    true,
  );

  // The negative control, and it is directional: a name that merely SHARES
  // letters is not this employer, or the picker would offer strangers' rows.
  assert.equal(
    reviewCandidates(relay, [
      { id: 61, company: "Northgate Systems", position: "SRE", status: "applied" },
      { id: 62, company: "Windward Labs", position: "SRE", status: "applied" },
    ]).length,
    0,
  );
});

test("the employer token is what makes the question fire on ATS mail", () => {
  // THE MAIL THIS DEFECT LIVES ON. A lifecycle message at an employer holding
  // several rows is almost never sent from that employer's domain: it is an ATS
  // relay. The backend names the employer from the sender's display name or the
  // subject's leading segment — never from the body, which is filing grade the
  // resolver refuses (`pipeline.resolve_employer`) — and the mail listing ships
  // that token on every row, linked or not.
  const ats = {
    sender_email: "no-reply@greenhouse.io",
    sender_name: "Greenhouse",
    subject: "Update on your application",
    employer_token: "northwind",
  };
  assert.equal(reviewCandidates(ats, TWO).length, 2);
  assert.equal(
    asksWhichApplication({
      category: "rejection",
      candidates: reviewCandidates(ats, TWO),
      linkedApplicationId: null,
    }),
    true,
    "the ledger must ask about an ATS relay — that is the whole population",
  );

  // The control, and it is the pre-fix behaviour: drop the resolved employer
  // and the same message matches nothing at all.
  const withoutEmployer = { ...ats, employer_token: null };
  assert.equal(
    reviewCandidates(withoutEmployer, TWO).length,
    0,
    "if this is not 0 the assertion above proves nothing about the employer token",
  );

  // A two-letter name is still not evidence found INSIDE a haystack — it has to
  // be the whole of an exact signal.
  const ge = [
    { id: 7, company: "GE", position: "Analyst", status: "applied" },
    { id: 8, company: "GE", position: "Engineer", status: "applied" },
  ];
  assert.equal(reviewCandidates({ ...ats, employer_token: "ge" }, ge).length, 2);
  assert.equal(
    reviewCandidates(
      { ...ats, subject: "Your GE application", employer_token: "northwind" },
      ge,
    ).length,
    0,
    "'GE' inside a subject would match half an inbox",
  );
});

test("both sides of the wire answer the shared employer table identically", () => {
  // ONE RULE, TWO LANGUAGES. `matchesEmployerToken` here and
  // `pipeline.matches_company_token` there decide the same question — is this
  // board row this employer? — and they cannot share an implementation. They
  // can be made to fail together: this table is the only copy of the answers,
  // and `backend/tests/test_one_employer_rule.py` asserts exactly these rows.
  // Editing one side's answer alone is impossible, because there is one answer.
  const table = JSON.parse(
    readFileSync(fileURLToPath(new URL("../fixtures/employer-token-match.json", import.meta.url)), "utf8"),
  );
  assert.ok(table.cases.some((c) => c.matches === true));
  assert.ok(
    table.cases.some((c) => c.matches === false),
    "a table with no negative rows passes against a function that returns true",
  );
  for (const row of table.cases) {
    assert.equal(
      matchesEmployerToken(row.company, row.token),
      row.matches,
      `${JSON.stringify(row.company)} / ${JSON.stringify(row.token)}: ${row.why}`,
    );
  }
});

test("the review queue's own matching is unchanged", () => {
  // A `ReviewItem` carries `suggested_employer` — a question the backend is
  // ASKING — and no resolved token, so the queue passes nothing and this change
  // cannot move what it offers. Its e2e gate stays meaningful.
  const queueItem = {
    sender_email: "no-reply@greenhouse.io",
    sender_name: "Greenhouse",
    subject: "Update on your application",
  };
  assert.equal(reviewCandidates(queueItem, TWO).length, 0);
  assert.equal(
    reviewCandidates(
      { sender_email: "talent@northwind.com", sender_name: "Northwind", subject: "Update" },
      TWO,
    ).length,
    2,
    "the sender/subject path still matches exactly as it did",
  );
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

// --- The ledger's own mount, on a screen ------------------------------------
//
// WHAT THIS REPLACED, AND WHY. These two used to be source TRIPWIRES: one
// regex over `ReclassifyControl.tsx` and one over `FiledMailList.tsx`, both
// labelled as tripwires rather than gates because nothing in CI could execute
// a `.tsx` component that uses hooks. They were not merely weak, they were
// defeatable — measured, each applied alone:
//
//     FiledMailList: reviewCandidates(m, board) -> reviewCandidates(m, board.slice(0, 1))
//       unit 631/631 GREEN · tsc EXIT 0 · lint EXIT 0 · tripwire still matched
//     ReclassifyControl: const showPicker = ... -> const showPicker = false
//       same, green everywhere
//
// Either one silences this question forever. `helpers/mountApp.mjs` is what
// closed that: the real components are mounted over a real-shaped listing row
// and the question is looked for on the page. Reading source is how #560 was
// misdiagnosed in the first place; a regex standing in for behaviour is not
// coverage.

/** One stored message as `GET /applications/mail` actually serves it. */
const RELAY_ROW = {
  message_id: "m-relay",
  thread_id: "t-relay",
  subject: "Update on your application",
  sender_name: "Northwind Hiring Team",
  sender_email: "no-reply@greenhouse.io",
  received_at: "2026-05-25T09:00:00+00:00",
  snippet: "Thanks for your interest.",
  category: "needs_review",
  confidence: 0.62,
  method: "rules",
  user_corrected: false,
  review_disposition: null,
  is_reviewed: false,
  // UNLINKED — the population the question exists for.
  application_id: null,
  on_board: false,
  // The LINKED row's employer, and it is null here BY CONSTRUCTION. Read the
  // pair together: a matcher keyed on this field can only fire where the
  // question is never asked.
  company: null,
  employer_token: "northwind",
  gmail_link: "https://mail.google.com/mail/u/0/#inbox/t-relay",
};

/** The employer's rows, named as a human would store them — LONGER than the
 *  token, which is the ordinary case and the one that used to match nothing. */
const LEDGER_BOARD = [
  { id: 51, company: "Northwind Traders", position: "Backend Engineer", status: "applied" },
  { id: 52, company: "Northwind Traders", position: "Platform Engineer", status: "applied" },
];

/**
 * Mount the ledger over one listing payload and open that row's correction.
 *
 * The row is built by `readFiledMailPage` from a raw body rather than typed as
 * an object, so a field the parser drops on the floor is a field this test
 * cannot see either — which is exactly what happened to the last attempt at
 * making the question reachable.
 */
async function openLedgerCorrection(rawMessage, board) {
  const { readFiledMailPage } = await importApp("lib/mail/filed.ts");
  const { FiledMailList } = await importApp("components/mail/FiledMailList.tsx");
  const page = readFiledMailPage({
    messages: [rawMessage],
    total: 1,
    page: 1,
    page_size: 50,
    category_counts: { needs_review: 1 },
  });
  const view = await mount(
    React.createElement(FiledMailList, { page, activeCategory: null, q: null, board }),
  );
  await view.click('button[aria-label^="Reclassify"]');
  // The question is only put for a LIFECYCLE answer — a stage a message can
  // actually be about. Chosen the way a reader chooses it.
  await view.choose(`select#reclass-${rawMessage.message_id}`, "rejection");
  return view;
}

test("the filed ledger asks which application an unlinked ATS correction is about", async () => {
  const view = await openLedgerCorrection(RELAY_ROW, LEDGER_BOARD);

  assert.match(
    view.html(),
    /which application is this about\?/,
    "the ledger drew no question over an unlinked message at an employer " +
      "holding two rows — this is #560 on the screen",
  );
  assert.equal(
    view.queryAll('input[type="radio"]').length,
    3,
    "both of the employer's rows, plus 'none of these'",
  );
  assert.deepEqual(
    view.queryAll('input[type="radio"]').map((input) => input.value),
    ["51", "52", "none"],
    "the options carry the board ids the answer will travel as",
  );
  assert.equal(
    view.queryAll('input[type="radio"]:checked').length,
    0,
    "nothing is pre-selected — the option that DISCARDS the question used to " +
      "be the default (#554)",
  );
  await view.unmount();
});

test("a message already filed against a row is asked nothing", async () => {
  // The opposite direction, and it is what stops the test above passing on a
  // build that asks everything. A link outranks the tie-break (#546/#548), so
  // there is nothing to ask; offering "none of these" over a tracked message
  // is a new way to scatter a record.
  const view = await openLedgerCorrection(
    { ...RELAY_ROW, application_id: 51, on_board: true, company: "Northwind Traders" },
    LEDGER_BOARD,
  );
  assert.doesNotMatch(view.html(), /which application is this about\?/);
  assert.equal(view.queryAll('input[type="radio"]').length, 0);
  await view.unmount();
});

test("one candidate is not a question", async () => {
  // The threshold, on the mount rather than on the predicate alone: one option
  // is not a choice, and the backend's resolution already has the right row.
  const view = await openLedgerCorrection(RELAY_ROW, [LEDGER_BOARD[0]]);
  assert.doesNotMatch(view.html(), /which application is this about\?/);
  await view.unmount();
});

test("the answer the reader picks is the id the request carries", async () => {
  // The last hop, and the one #560 actually was: `ReclassifyControl` put a
  // literal `null` in the `application_id` position, so even a perfect picker
  // sent nothing. `classify` is the component's own transport seam — the prop
  // `/demo/scan` uses — so this reads the real request body off the real
  // click path, with no source regex anywhere in it.
  const { readFiledMailPage } = await importApp("lib/mail/filed.ts");
  const { FiledMailList } = await importApp("components/mail/FiledMailList.tsx");
  const { ReclassifyControl } = await importApp("components/mail/ReclassifyControl.tsx");
  const { reviewCandidates } = await importApp("lib/dashboard/review.ts");

  // The candidates come from the LEDGER's own mount, not from this test: read
  // the page the same way the list does, then hand the control what the list
  // would hand it.
  const page = readFiledMailPage({ messages: [RELAY_ROW], total: 1, page: 1, page_size: 50 });
  const message = page.messages[0];
  assert.ok(FiledMailList, "the ledger must still be loadable — the mount above is the gate");

  const sent = [];
  const view = await mount(
    React.createElement(ReclassifyControl, {
      messageId: message.message_id,
      subject: message.subject,
      company: message.company,
      candidates: reviewCandidates(message, LEDGER_BOARD),
      linkedApplicationId: message.application_id,
      classify: async (messageId, body) => {
        sent.push({ messageId, body });
        return { ok: true, body: { application_id: body.application_id } };
      },
    }),
  );
  await view.click('button[aria-label^="Reclassify"]');
  await view.choose(`select#reclass-${message.message_id}`, "rejection");

  const apply = view.queryAll("button").find((b) => b.textContent.trim() === "apply");
  // STATED with `aria-disabled`, never with the DOM's `disabled` (#425): a
  // focused element that becomes disabled is blurred by the browser to <body>
  // and does not get the focus back, and this button is where the reader is
  // standing when they submit. `aria-disabled` is ADVISORY — the click still
  // arrives — so the refusal has to be real in the handler, which is what the
  // click below measures rather than the attribute.
  assert.equal(
    apply.getAttribute("aria-disabled"),
    "true",
    "an unanswered question must not be submittable — a click here files the " +
      "correction against a row nobody named",
  );
  assert.equal(
    apply.disabled,
    false,
    "the lock must not be the attribute that blurs the button (#425)",
  );
  await view.click(apply);
  assert.equal(
    sent.length,
    0,
    "the click on an unanswered question reached the handler and was NOT dropped — " +
      "with an advisory lock, a gate that only writes an attribute is no gate",
  );

  await view.click('input[type="radio"][value="52"]');
  assert.equal(apply.getAttribute("aria-disabled"), "false");
  // The same dispatch, un-refused, DOES send — so the zero above is the
  // component's decision and not a dead click.
  await view.click(apply);

  assert.equal(sent.length, 1);
  assert.equal(
    sent[0].body.application_id,
    52,
    "the row the reader picked did not reach the wire — the picker is decoration",
  );
  assert.equal(sent[0].body.category, "rejection");
  await view.unmount();
});

test("a second apply while the first is still in flight is dropped", async () => {
  // #425's other half. The in-flight lock on this control is `aria-disabled`
  // now, because the DOM's `disabled` blurs the focused button to <body> and
  // never gives the focus back — measured on /demo/scan at t=8ms, with the node
  // still in the document, and asserted over a whole trace in
  // `tests/e2e/stage-focus.spec.ts`. But `aria-disabled` does not stop the
  // event: the browser delivers the second click, so a lock written only as an
  // attribute would be weaker than the one it replaced.
  //
  // This is where that is COUNTED. The e2e can press mid-write but cannot count
  // applies — a second one sends the same body and lands on the same verdict,
  // so the surface looks identical either way. Here the transport is held open
  // and `sent.length` is the measurement.
  const { ReclassifyControl } = await importApp("components/mail/ReclassifyControl.tsx");

  const sent = [];
  let release;
  const inFlight = new Promise((resolve) => {
    release = resolve;
  });
  const view = await mount(
    React.createElement(ReclassifyControl, {
      messageId: "m-inflight",
      subject: "Update on your application",
      company: "Northwind",
      // Linked, and no candidates: this test is about the write, so the
      // question must not be on the page to answer first.
      candidates: [],
      linkedApplicationId: 51,
      classify: async (messageId, body) => {
        sent.push({ messageId, body });
        await inFlight;
        return { ok: true, body: { application_id: 51 } };
      },
    }),
  );
  await view.click('button[aria-label^="Reclassify"]');
  await view.choose("select#reclass-m-inflight", "rejection");

  const apply = view.query("button#reclass-apply-m-inflight");
  const select = view.query("select#reclass-m-inflight");
  await view.click(apply);
  assert.equal(sent.length, 1, "the first press has to send, or there is no write to be in flight");
  assert.equal(apply.getAttribute("aria-busy"), "true", "the write is announced, not just drawn");
  assert.equal(apply.getAttribute("aria-disabled"), "true");
  assert.equal(
    apply.disabled,
    false,
    "the in-flight lock must NOT be the DOM disabled property — that is defect #425",
  );
  assert.equal(select.getAttribute("aria-disabled"), "true");
  assert.equal(select.disabled, false, "and the category select is locked the same way");

  await view.click(apply);
  assert.equal(
    sent.length,
    1,
    "a second press while the write was in flight fired a second correction — " +
      "`aria-disabled` does not stop the event, so the handler has to",
  );

  await view.choose(select, "offer");
  assert.equal(
    select.value,
    "rejection",
    "a category picked mid-write is ignored and the controlled value snaps back",
  );

  await React.act(async () => {
    release();
    await inFlight;
  });
  assert.match(view.html(), /your call is the verdict now/);
  await view.unmount();
});
