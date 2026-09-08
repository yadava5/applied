/**
 * `groupReviewItems` — the queue's rows collapsed into the things it asks ABOUT.
 *
 * WHY THIS FILE IS SHAPED THE WAY IT IS. A grouping bug renders exactly like
 * the behaviour before grouping existed: every row still on screen, every
 * control still answerable, nothing missing. So an assertion that the rows are
 * present cannot fail, and a suite built out of those assertions would be green
 * from birth and green forever — the defect class this repository keeps finding
 * in its own gates. Every test below pins STRUCTURE (how many units, which key,
 * which order) and each one names the mutation that reds it. Those mutations
 * were applied, watched red, and reverted; the results are in the commit body.
 *
 * The band law this is built under, from the measurement that closed the
 * alternative (#517): classifier output may ORDER and GROUP the asking and may
 * never ANSWER it. Nothing here reads a suggested stage to decide whether a row
 * is worth asking about — only whether a group opens collapsed.
 *
 * Node-loadable directly: `lib/dashboard/review.ts` is deliberately free of
 * React, of `@/` and of the generated schema, which is what lets the grouping
 * be tested as a function rather than inferred from a rendered tree.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { groupReviewItems } from "../../lib/dashboard/review.ts";

/**
 * The group key's separator, composed rather than imported.
 *
 * An expectation read from the module under test compares that module to
 * itself and passes for every value it could hold. This is built from the
 * brand, by hand, the way the key is meant to read.
 */
const NUL = String.fromCharCode(0);

/** Invented, per `docs/TEST_DATA_POLICY.md` — this repository is public. */
const BRAND = "Ferrisgate";
const OTHER_BRAND = "Marlowe Union";

const card = (id, company, position = "Backend Engineer") => ({
  id,
  company,
  position,
  status: "applied",
});

const held = (message_id, subject, sender_email, received_at, extra = {}) => ({
  message_id,
  subject,
  sender_name: null,
  sender_email,
  received_at,
  ...extra,
});

/**
 * #517's own shape: four held messages, one employer, one board card, three
 * sending addresses, no role on any of them. The queue asked four times.
 *
 * The subjects carry the brand because the QUEUE'S arm of `reviewCandidates` is
 * the weak one — a review item carries no `employer_token`, so matching is
 * `haystack.includes(company)` over sender and subject. A fixture that relied
 * on the token arm would exercise a path this surface never takes.
 */
const FOUR_AT_ONE_EMPLOYER = [
  held("m1", `Are you still interested in the ${BRAND} role?`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-01T09:00:00.000Z"),
  held("m2", `Your ${BRAND} assessment expires in 24 hours`, `assessments@${BRAND.toLowerCase()}.example`, "2026-09-02T09:00:00.000Z"),
  held("m3", `Reminder from ${BRAND}`, `careers@${BRAND.toLowerCase()}.example`, "2026-09-03T09:00:00.000Z"),
  held("m4", `Thank you for your ${BRAND} application`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-04T09:00:00.000Z"),
];

test("four rows at one employer become ONE unit, keyed on the brand", () => {
  const units = groupReviewItems(FOUR_AT_ONE_EMPLOYER, [card(1, BRAND)]);

  // STRUCTURE, not presence. `assert.equal(rows.length, 4)` holds whether or
  // not anything grouped, which is the whole reason it is not the assertion.
  assert.equal(units.length, 1, "four rows at one employer are still four questions on screen");
  assert.equal(units[0].members.length, 4);
  assert.equal(units[0].key, `ferrisgate${NUL}`, "the key is the normalised brand and an absent role");
  assert.equal(units[0].company, BRAND, "the header gets the BOARD's spelling, not the mail's");
  assert.equal(units[0].role, null);

  // MUTATION: make the body return singletons — `return items.map((item) => ({
  // key: null, ... }))` — and this reds while every row-presence assertion in
  // the repo stays green.
});

test("with an EMPTY board the same four rows are four ungrouped singletons", () => {
  // The directional control for the test above: ONE thing varies, the board.
  // Without it, a key derived from the mail's own sender domain would pass
  // there and this suite could not tell the two apart — and a key read off the
  // mail is a key the picker would not agree with.
  const units = groupReviewItems(FOUR_AT_ONE_EMPLOYER, []);

  assert.equal(units.length, 4);
  for (const unit of units) {
    assert.equal(unit.members.length, 1);
    assert.equal(unit.key, null, "a row with no candidate must not be keyed on anything");
    assert.equal(unit.company, null);
  }
});

test("a row naming TWO different employers stands alone, candidates and all", () => {
  const board = [card(1, BRAND), card(2, OTHER_BRAND)];
  const ambiguous = [
    held(
      "m1",
      `${BRAND} and ${OTHER_BRAND} are both hiring`,
      "digest@jobs.example",
      "2026-09-01T09:00:00.000Z",
    ),
  ];

  const units = groupReviewItems(ambiguous, board);

  assert.equal(units.length, 1);
  // The load-bearing pair: the row DID resolve two candidates, and is still
  // ungrouped. Without the first assertion this passes against a fixture that
  // resolved nothing, which is a different test.
  assert.equal(units[0].members[0].candidates.length, 2, "the fixture no longer names two employers");
  assert.equal(units[0].key, null, "two employers is not one employer");

  // MUTATION: key on `candidates[0].company` instead of requiring one shared
  // name — reds here, stays green on the four-row test above, which is what
  // makes it a discriminating control rather than a second copy of test 1.
});

test("one employer holding TWO cards still groups — the rule is one NAME", () => {
  // #454: an employer legitimately holds several applications, and the picker
  // exists precisely for that. "All candidates share one name" is the rule;
  // "exactly one candidate" would silently stop grouping for every employer the
  // reader has applied to twice, which is the population this issue is about.
  const board = [card(1, BRAND, "Backend Engineer"), card(2, BRAND, "Platform Engineer")];
  const pair = [
    held("m1", `Reminder from ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-01T09:00:00.000Z"),
    held("m2", `Your ${BRAND} assessment expires soon`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-02T09:00:00.000Z"),
  ];

  const units = groupReviewItems(pair, board);

  assert.equal(units.length, 1);
  assert.equal(units[0].members.length, 2);
  assert.equal(units[0].members[0].candidates.length, 2, "the fixture no longer offers two cards");

  // MUTATION: narrow the condition to `candidates.length === 1` — reds here.
});

test("ROLE splits one employer's rows, and only role", () => {
  const board = [card(1, BRAND)];
  const differentRoles = [
    held("m1", `Thank you for applying to ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-01T09:00:00.000Z", {
      role: "Backend Engineer, Alarms",
    }),
    held("m2", `Thank you for applying to ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-02T09:00:00.000Z", {
      role: "Frontend Engineer - Access Control",
    }),
  ];

  const split = groupReviewItems(differentRoles, board);
  assert.equal(split.length, 2, "two requisitions at one employer are two questions (#454)");
  assert.equal(split[0].members.length, 1);
  assert.equal(split[1].members.length, 1);
  assert.notEqual(split[0].key, split[1].key, "the two units share a key, so nothing tells them apart");

  // The other arm, so this is a control and not half of one: same fixture, one
  // variable changed.
  const sameRole = differentRoles.map((item) => ({ ...item, role: "Backend Engineer, Alarms" }));
  const joined = groupReviewItems(sameRole, board);
  assert.equal(joined.length, 1);
  assert.equal(joined[0].members.length, 2);
  assert.equal(joined[0].key, `ferrisgate${NUL}backend engineer, alarms`);
  assert.equal(joined[0].role, "Backend Engineer, Alarms", "the header keeps the mail's own spelling");

  // MUTATION: drop the role component from the key — the first arm collapses to
  // one unit and reds.
});

test("every count in one mixed queue is distinct, so no two operands are swappable", () => {
  // A fixture whose numbers coincide cannot fail a swap: with `filed == scanned`
  // an exchange of the two is byte-identical and survives every assertion. A
  // 3-group, a 2-group and two lone rows give 7 rows, 4 units, and member
  // counts 3, 2, 1, 1 — every number this function reports is a different
  // number.
  const board = [card(1, BRAND), card(2, OTHER_BRAND)];
  const items = [
    held("g1", `${BRAND} assessment reminder`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-07T09:00:00.000Z"),
    held("g2", `Your ${BRAND} assessment expires in 24 hours`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-06T09:00:00.000Z"),
    held("g3", `Reminder from ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-05T09:00:00.000Z"),
    held("h1", `${OTHER_BRAND} — next steps`, "no-reply@marlowe.example", "2026-09-04T09:00:00.000Z"),
    held("h2", `A note from ${OTHER_BRAND}`, "no-reply@marlowe.example", "2026-09-03T09:00:00.000Z"),
    held("s1", "Quick question about your background", "maya@unmatched.example", "2026-09-02T09:00:00.000Z"),
    held("s2", "Re: your note", "priya@alsounmatched.example", "2026-09-01T09:00:00.000Z"),
  ];

  const units = groupReviewItems(items, board);
  const rows = units.reduce((n, u) => n + u.members.length, 0);

  assert.equal(rows, 7);
  assert.equal(units.length, 4);
  assert.deepEqual(
    units.map((u) => u.members.length),
    [3, 2, 1, 1],
  );
  assert.equal(new Set([rows, units.length, 3, 2, 1]).size, 5, "two of these numbers coincide again");
});

test("units sort by their NEWEST member, members newest-first, and a lone row lands between", () => {
  // Interleaved on purpose: the group's two members straddle the lone row's
  // date, so "sort the group by its newest" and "sort the group by its oldest"
  // put the two units in opposite orders. A fixture where the group is wholly
  // newer than the singleton cannot tell those apart.
  const board = [card(1, BRAND)];
  const items = [
    held("old", `Reminder from ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-01T09:00:00.000Z"),
    held("mid", "Quick question about your background", "maya@unmatched.example", "2026-09-03T09:00:00.000Z"),
    held("new", `Your ${BRAND} assessment expires in 24 hours`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-05T09:00:00.000Z"),
  ];

  const units = groupReviewItems(items, board);

  assert.equal(units.length, 2);
  assert.deepEqual(
    units.map((u) => u.members.map((m) => m.item.message_id)),
    [["new", "old"], ["mid"]],
    "the group is behind the lone row, so the unit is being dated by its OLDEST member",
  );
  assert.equal(units[0].receivedAt, "2026-09-05T09:00:00.000Z", "the header would show a stale date");

  // MUTATION: date a unit by its oldest member (or invert `newestFirst`) — reds
  // on the order AND on the header's date, which are two different claims.
});

test("a dateless row sorts last rather than wherever the engine happens to put it", () => {
  // The queue renders rows with no receipt time — that branch is in the row
  // component and predates this. An undefined comparator result there is a
  // render order that changes between engines.
  const board = [card(1, BRAND)];
  const items = [
    held("nodate", `Reminder from ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, null),
    held("dated", "Quick question about your background", "maya@unmatched.example", "2026-09-01T09:00:00.000Z"),
  ];

  const units = groupReviewItems(items, board);
  assert.deepEqual(
    units.map((u) => u.members[0].item.message_id),
    ["dated", "nodate"],
  );
  assert.equal(units[1].receivedAt, null);
});

test("the gate reads suggested_category and NOTHING else does", () => {
  // The one lawful use. Uniform agrees and the group may open collapsed;
  // disagreement forces it open. All-absent is agreement — an older backend
  // that sends no category at all has not disagreed about anything, and
  // treating silence as conflict would expand every group in production.
  const board = [card(1, BRAND)];
  const two = (a, b) => [
    held("m1", `Reminder from ${BRAND}`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-02T09:00:00.000Z", {
      suggested_category: a,
    }),
    held("m2", `Your ${BRAND} assessment expires soon`, `no-reply@${BRAND.toLowerCase()}.example`, "2026-09-01T09:00:00.000Z", {
      suggested_category: b,
    }),
  ];

  assert.equal(groupReviewItems(two("assessment", "assessment"), board)[0].uniformCategory, true);
  assert.equal(groupReviewItems(two("assessment", "applied"), board)[0].uniformCategory, false);
  // The realistic mixed backend, and the arm that would otherwise ship
  // untested: one row carrying a category, one carrying none.
  assert.equal(groupReviewItems(two("assessment", null), board)[0].uniformCategory, false);
  assert.equal(groupReviewItems(two(null, null), board)[0].uniformCategory, true);
});
