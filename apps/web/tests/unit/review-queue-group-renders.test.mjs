/**
 * What the grouped review queue actually DRAWS — mounted, clicked, read.
 *
 * NO SOURCE-REGEX TRIPWIRES IN THIS FILE. `helpers/mountApp.mjs` records why:
 * the question "which application is this about?" was held by a regex over the
 * source, and two one-line changes silenced it permanently while still matching
 * the tripwire's own pattern. A regex reads intent. These tests put the tree on
 * a screen and look for what a person would see.
 *
 * The two tripwires here are the ones that matter for #517, and both are
 * EQUALITY pins rather than absence checks:
 *
 *   - the header carries exactly ONE interactive control. A `doesNotMatch` on
 *     the word "select" survives a widened condition and survives a second
 *     control appearing next to the expander; a count does not.
 *   - the header's full text equals a hand-written string of raw facts. Any
 *     leak of a `CATEGORY_CHOICES` label — "assessment", "rejection" — reds it,
 *     and so does any other word the machine produced, including ones nobody
 *     has thought of yet. An absence check only catches the words it lists.
 *
 * A group-level ANSWER control is the named hazard: it would let a rejection
 * misread as a status-quo confirmation be swept in as an authoritative user
 * answer, which outranks machine evidence permanently. That is what test one of
 * those two exists to make impossible to add quietly.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { importApp, mount, React } from "./helpers/mountApp.mjs";
import { visibleText } from "./helpers/visibleText.mjs";

const { ReviewQueue } = await importApp("components/dashboard/ReviewQueue.tsx");

/** Invented, per `docs/TEST_DATA_POLICY.md` — this repository is public. */
const BRAND = "Ferrisgate";
/**
 * The domain LABEL only — the reserved `.example` suffix is a literal at the
 * interpolation site below rather than part of this constant.
 *
 * `check_test_data.py` reads the part of a built address that no interpolation
 * can change. An address whose suffix is the interpolated value seals nothing —
 * it is whatever the call site passes in — and is counted; one whose suffix is
 * a reserved literal cannot route whatever this constant holds.
 *
 * This comment deliberately does NOT spell the unsealed form out. Writing the
 * bad shape into the prose that explains the rule is how the policy document
 * itself once failed its own gate, and it is counted from a comment exactly as
 * it is from code.
 */
const DOMAIN = "ferrisgate";

const card = (id, company, position = "Backend Engineer") => ({
  id,
  company,
  position,
  status: "applied",
  // The board rows the queue is handed are full `Application` objects; the
  // picker's pool reads four fields off them and the rest ride along.
  created_at: "2026-08-01T09:00:00.000Z",
});

const held = (message_id, subject, received_at, extra = {}) => ({
  message_id,
  subject,
  sender_name: null,
  sender_email: `no-reply@${DOMAIN}.example`,
  received_at,
  snippet: "A short note about your application.",
  confidence: 0.74,
  gmail_link: null,
  hold_reason: "below_gate",
  role: null,
  ...extra,
});

/** Four held messages at one employer, all agreeing about the machine's guess. */
const uniformFour = () => [
  held("m1", `Are you still interested in the ${BRAND} role?`, "2026-09-05T09:00:00.000Z", {
    suggested_category: "assessment",
  }),
  held("m2", `Your ${BRAND} assessment expires in 24 hours`, "2026-09-04T09:00:00.000Z", {
    suggested_category: "assessment",
  }),
  held("m3", `Reminder from ${BRAND}`, "2026-09-03T09:00:00.000Z", {
    suggested_category: "assessment",
  }),
  held("m4", `Thank you for your ${BRAND} application`, "2026-09-02T09:00:00.000Z", {
    suggested_category: "assessment",
  }),
];

const BOARD = [card(1, BRAND)];

const queue = (items, applications = BOARD) =>
  React.createElement(ReviewQueue, { items, applications });

/** Every element in `root` a person can operate. */
const INTERACTIVE = 'button, select, input, textarea, a[href], [role="button"], [tabindex]';

test("a uniform group collapses to one line, and its rows are UNMOUNTED", async () => {
  const view = await mount(queue(uniformFour()));

  const expander = view.query("button[aria-expanded]");
  assert.ok(expander, "no expander — the four rows are not grouped at all");
  assert.equal(expander.getAttribute("aria-expanded"), "false");
  const name = expander.textContent;
  assert.match(name, new RegExp(BRAND), "the expander does not say which employer");
  assert.match(name, /\b4\b/, "the expander does not say how many messages are behind it");

  // NOT HIDDEN — ABSENT. A collapsed group's rows carry no `<select>` in the
  // document, so they are physically unanswerable. That is the property that
  // makes collapsing safe at all: the evidence has to be on screen before any
  // answer can be given.
  assert.equal(view.queryAll('select[id^="cat-"]').length, 0);

  await view.click(expander);

  assert.equal(expander.getAttribute("aria-expanded"), "true");
  const selects = view.queryAll('select[id^="cat-"]');
  assert.equal(selects.length, 4, "expanding did not restore one answer per message");
  assert.equal(
    new Set(selects.map((s) => s.id)).size,
    4,
    "two rows share an element id, so a label points at the wrong select",
  );
});

test("TRIPWIRE: the group header carries exactly ONE control, and it is the expander", async () => {
  // The hazard, named: any group-level ANSWER — a select, a "these are all the
  // assessment" button, a checkbox that sweeps four rows into one verdict —
  // converts a misread rejection into an authoritative USER answer, and a user
  // answer outranks machine evidence permanently. Pinned as a COUNT because a
  // `doesNotMatch` on a word survives both a widened condition and a second
  // control that happens to be spelled differently.
  const view = await mount(queue(uniformFour()));

  const headers = view.queryAll("h3");
  assert.equal(headers.length, 1, "the group header is no longer the page's only h3");
  const controls = headers[0].querySelectorAll(INTERACTIVE);
  assert.equal(
    controls.length,
    1,
    `the group header grew a second control: ${[...controls].map((c) => c.outerHTML).join(" | ")}`,
  );
  assert.equal(controls[0].getAttribute("aria-expanded"), "false", "the one control is not the expander");
});

test("TRIPWIRE: the header says raw facts and NOTHING the classifier produced", async () => {
  // EQUALITY, not absence. The letter of the band law permits a category count
  // in a header — it is grouping, and nothing persists. It fails on this
  // product's own precedents: the stage select ships a disabled placeholder
  // because "the control must not answer for the user", and #554 measured what
  // a preselection-shaped default cost (19 applications destroyed, 0 once the
  // answer had to be the user's). "assessment x4" printed directly above that
  // select is the machine's guess at the strongest anchoring position on the
  // page, in the band where it misreads rejections.
  //
  // The expected string is written out BY HAND. Comparing it to the header
  // function's own return value would compare the code to itself and pass for
  // every string it could ever produce.
  const view = await mount(queue(uniformFour()));

  const header = view.query("h3");
  assert.equal(visibleText(header.outerHTML), `4 held messages · ${BRAND} · Sep 5`);

  // And it does not claim more than the key proves. Same employer NAME and same
  // derived role is not "one application" — one employer holds several (#454).
  assert.doesNotMatch(header.textContent, /one application/i);
});

test("two groups at ONE employer are told apart by their headers", async () => {
  // THE DEFECT THIS CLOSES, and it is the grouping defect reintroduced one
  // level up: the key distinguishes two requisitions at one employer, and the
  // COPY did not. A reader saw "2 held messages · Ferrisgate" twice, with no
  // way to tell which pile was which — which is exactly the "asking about one
  // employer four times" complaint the group exists to remove.
  //
  // The two groups are given the SAME newest date on purpose. With the date as
  // the only other varying part, a header that omits the role is byte-identical
  // between them, so the role is the single thing under test here.
  const ALARMS = "Backend Engineer, Alarms";
  const ACCESS = "Frontend Engineer - Access Control";
  const items = [
    held("a1", `Thank you for applying to ${BRAND}`, "2026-09-05T09:00:00.000Z", {
      role: ALARMS,
      suggested_category: "applied",
    }),
    held("b1", `Thank you for applying to ${BRAND}`, "2026-09-05T09:00:00.000Z", {
      role: ACCESS,
      suggested_category: "applied",
    }),
    held("a2", `Reminder from ${BRAND}`, "2026-09-04T09:00:00.000Z", {
      role: ALARMS,
      suggested_category: "applied",
    }),
    held("b2", `Reminder from ${BRAND}`, "2026-09-04T09:00:00.000Z", {
      role: ACCESS,
      suggested_category: "applied",
    }),
  ];

  const view = await mount(queue(items));
  const headers = view.queryAll("h3").map((h) => visibleText(h.outerHTML));

  assert.equal(headers.length, 2, "the two requisitions did not stay two groups (#454)");
  // EQUALITY on each, and then on the pair. A substring check ("contains the
  // role") would pass against a header that appended the role to both and a
  // `notEqual` alone would pass on any incidental difference, including the
  // date drifting apart — which is what the shared date above rules out.
  assert.equal(headers[0], `2 held messages · ${BRAND} · ${ALARMS} · Sep 5`);
  assert.equal(headers[1], `2 held messages · ${BRAND} · ${ACCESS} · Sep 5`);
  assert.notEqual(headers[0], headers[1], "one employer's two piles render the same header");

  // …and naming the role still does not overclaim. Same employer name and same
  // derived role is not "one application"; an employer holds several (#454).
  for (const text of headers) assert.doesNotMatch(text, /one application/i);
});

test("the header shows the NEWEST member's date, so an aging pile visibly ages", async () => {
  const view = await mount(queue(uniformFour()));
  // Sep 5 is m1's date and the newest of the four; Sep 2 is the oldest. A
  // header dated by the oldest reads as a stale queue nobody has touched.
  assert.match(view.query("h3").textContent, /Sep 5/);
  assert.doesNotMatch(view.query("h3").textContent, /Sep 2/);
});

test("a group of ONE renders no group chrome at all", async () => {
  const view = await mount(queue([uniformFour()[0]]));

  assert.equal(view.queryAll("h3").length, 0, "a lone row grew a group header");
  assert.equal(view.queryAll("button[aria-expanded]").length, 0);
  // …and it is still a live row, which is what makes the two assertions above
  // mean something rather than describing an empty tree.
  assert.equal(view.queryAll('select[id^="cat-"]').length, 1);

  // MUTATION: render every unit through `ReviewGroup` — reds here while the
  // grouped tests above stay green.
});

test("the landing's single-item mount draws no group chrome either", async () => {
  // `HeldExhibit` mounts the REAL `ReviewQueue` with exactly one item over the
  // showcase board, on a marketing page. It is the one place outside the
  // dashboard that renders this component, and grouping must be invisible there.
  const { HeldExhibit } = await importApp("components/marketing/HeldExhibit.tsx");
  const view = await mount(React.createElement(HeldExhibit, { settled: true }));
  // The exhibit resolves `today` in an effect before it mounts the queue —
  // prerendering a relative date bakes the build day in — so let that timer run.
  await React.act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });

  assert.equal(
    view.queryAll('select[id^="cat-"]').length,
    1,
    "the exhibit's queue never mounted, so this test is asserting about an empty tree",
  );
  assert.equal(view.queryAll("h3").length, 0);
  assert.equal(view.queryAll("button[aria-expanded]").length, 0);
});

test("members that DISAGREE about the machine's guess open the group expanded", async () => {
  // The gate, and the only direction the band law permits: band data may buy
  // MORE scrutiny, never less. #517's own four rows are three assessment and
  // one applied, so the pile this issue was filed about renders EXPANDED. That
  // is correct rather than a failure — the win there is the header saying the
  // four are one employer.
  const mixed = uniformFour();
  mixed[3] = { ...mixed[3], suggested_category: "applied" };
  const view = await mount(queue(mixed));

  assert.equal(view.query("button[aria-expanded]").getAttribute("aria-expanded"), "true");
  assert.equal(view.queryAll('select[id^="cat-"]').length, 4, "an expanded group must show its rows");

  // The other arm, same fixture, one field changed — so this is a control and
  // not half of one. MUTATION: invert the gate and BOTH arms red.
  const uniform = await mount(queue(uniformFour()));
  assert.equal(uniform.query("button[aria-expanded]").getAttribute("aria-expanded"), "false");
  assert.equal(uniform.queryAll('select[id^="cat-"]').length, 0);
});

test("the counts stay MESSAGES while the expander slices UNITS", async () => {
  // Seven messages, five units, four units shown, one hidden — every number
  // this test reads is a different number, so swapping any two of them in any
  // renderer is visible here. The repo has already shipped a "two renderers,
  // one number" defect (a header saying +50 this wk over a momentum line
  // saying 7), and the Inbox chip and the summary tile both count MESSAGES.
  const items = [
    ...uniformFour().slice(0, 3),
    held("s1", "Quick question about your background", "2026-09-01T09:00:00.000Z", {
      sender_email: "maya@unmatched.example",
    }),
    held("s2", "Re: your note — a few thoughts", "2026-08-31T09:00:00.000Z", {
      sender_email: "priya@alsounmatched.example",
    }),
    held("s3", "Scheduling — are you around next week?", "2026-08-30T09:00:00.000Z", {
      sender_email: "scheduling@thirdunmatched.example",
    }),
    held("s4", "Following up on the role we discussed", "2026-08-29T09:00:00.000Z", {
      sender_email: "dan@fourthunmatched.example",
    }),
  ];
  const view = await mount(queue(items));

  const heading = view.query("#needs-classification h2");
  assert.match(heading.textContent, /\b7\b/, "the heading counts units instead of messages");
  assert.doesNotMatch(heading.textContent, /\b5\b/);

  const expander = view.queryAll("button").find((b) => /show all/.test(b.textContent));
  assert.ok(expander, "the list expander is gone");
  assert.equal(expander.textContent.trim(), "show all 7", "the expander counts units instead of messages");

  // COLLAPSED_COUNT is 4 and it slices UNITS, so one of the five is hidden.
  // Hard-coded rather than imported: an expectation read from the constant it
  // is checking compares the code to itself and passes for every value.
  assert.equal(view.queryAll("#needs-classification > ul > li").length, 4);

  await view.click(expander);
  assert.equal(view.queryAll("#needs-classification > ul > li").length, 5);
  assert.equal(view.queryAll("button").find((b) => /show fewer/.test(b.textContent)) !== undefined, true);
});

test("answering one row of a group does not re-collapse the other three", async () => {
  // THE TRIAGE CASE. A member leaving the queue is what `router.refresh()`
  // produces after a classify, and the group is then one row shorter AND has a
  // new newest member — so it can change position among the units. Keyed by
  // index, the group inherits whatever expansion state the unit now at its
  // index had; keyed by its own key, it keeps its own.
  //
  // The fixture is built so the MOVE happens: the lone row's date sits between
  // the group's newest and its second-newest, so dropping the newest member
  // sends the group behind it and the two units swap places. A fixture where
  // the group stays put cannot tell the two keyings apart, because the state
  // would survive an index key too.
  const items = [
    held("g1", `Reminder from ${BRAND}`, "2026-09-05T09:00:00.000Z", {
      suggested_category: "assessment",
    }),
    held("mid", "Quick question about your background", "2026-09-04T09:00:00.000Z", {
      sender_email: "maya@unmatched.example",
    }),
    held("g2", `Your ${BRAND} assessment expires in 24 hours`, "2026-09-03T09:00:00.000Z", {
      suggested_category: "assessment",
    }),
    held("g3", `Are you still interested in the ${BRAND} role?`, "2026-09-02T09:00:00.000Z", {
      suggested_category: "assessment",
    }),
  ];

  // A stateful shell standing in for the server round trip: `mount` builds a
  // fresh React root and the harness's router is inert, so a second `mount`
  // with a shorter array would start collapsed however the units are keyed and
  // would pass under both arms of the mutation.
  function Harness() {
    const [rows, setRows] = React.useState(items);
    return React.createElement(
      "div",
      null,
      React.createElement(
        "button",
        {
          type: "button",
          id: "answer-g1",
          onClick: () => setRows((cur) => cur.filter((r) => r.message_id !== "g1")),
        },
        "answer g1",
      ),
      React.createElement(ReviewQueue, { items: rows, applications: BOARD }),
    );
  }

  const view = await mount(React.createElement(Harness));

  const before = view.queryAll("#needs-classification > ul > li");
  assert.equal(before.length, 2, "the fixture is not one group plus one lone row");
  assert.ok(before[0].querySelector("h3"), "the group is not the first unit, so it cannot move");

  // Scoped to the GROUP's own subtree: the lone row carries a `cat-` select
  // too, and a document-wide count would be measuring both units at once.
  const groupSelects = () =>
    view.query("h3").closest("li").querySelectorAll('select[id^="cat-"]').length;

  await view.click("button[aria-expanded]");
  assert.equal(view.query("button[aria-expanded]").getAttribute("aria-expanded"), "true");
  assert.equal(groupSelects(), 3);

  await view.click("#answer-g1");

  const after = view.queryAll("#needs-classification > ul > li");
  assert.equal(after.length, 2);
  assert.ok(
    after[1].querySelector("h3"),
    "the group did not move behind the lone row, so this fixture cannot tell an index key apart",
  );
  assert.equal(
    view.query("button[aria-expanded]").getAttribute("aria-expanded"),
    "true",
    "answering one of three rows re-collapsed the two the reader is still working through",
  );
  assert.equal(groupSelects(), 2, "the answered row is still on screen");

  // MUTATION: key the units by index — reds on the aria-expanded assertion.
});
