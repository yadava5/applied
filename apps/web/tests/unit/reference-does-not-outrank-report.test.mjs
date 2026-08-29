/**
 * Issue #451, in the browser port — a reference to an application is not a
 * report about it.
 *
 * `lib/demo/rulesLayer.ts` is a port of `backend/jobtracker/classifier/rules.py`
 * and its own header claims "same margin→confidence tiers, same ATS-domain
 * boost" as the backend. The tie-break was NOT the same, and could not have
 * been: both engines resolved a tie with a stable sort, Python over
 * `EmailCategory` declaration order (`applied` first) and this one over
 * `rules.json`'s key order (`rejection` first). Two engines that call
 * themselves the same classifier disagreed about the same mail, and neither
 * order was about the message.
 *
 * `readme_facts.py` compares the two ports by PATTERN COUNT, so it can see the
 * demotion and cannot see this. That is what this file is for.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

/**
 * `rulesLayer.ts` does `import rulesRaw from "./rules.json"`, which the
 * bundler resolves and bare `node --test` refuses — a JSON module needs an
 * explicit `with { type: "json" }` attribute that Next does not require and
 * this file must not add to production code just to be testable. The resolve
 * hook supplies the attribute, so the module under test is the real one and
 * not a copy of it. This is why no unit test imported this module before.
 */
registerHooks({
  resolve(specifier, context, next) {
    const resolved = next(specifier, context);
    if (resolved.url.endsWith(".json")) {
      resolved.importAttributes = { type: "json" };
    }
    return resolved;
  },
});

const { classifyWithRules, winnerFirst } = await import("../../lib/demo/rulesLayer.ts");

// The message from the issue. Invented; safe in a public repository.
const OFFER_SUBJECT = "An offer from Cedarhollow";
const OFFER_BODY =
  "Hi Ayush, We are delighted to extend you an offer to join us. The written " +
  "terms are attached for your review. This concerns your application for " +
  "the Backend Engineer position.";

test("the offer reads as an offer, at or above the 0.70 review floor", () => {
  const v = classifyWithRules(OFFER_SUBJECT, OFFER_BODY, "careers@cedarhollow.example");
  assert.equal(v.category, "offer", JSON.stringify(v.scores));
  assert.ok(v.confidence >= 0.7, `confidence ${v.confidence}`);
});

test("the reference is weak now: it scores 1 for applied, not 3", () => {
  // At `strong` this earned +3 — exactly what a report of a later stage earns,
  // which is how a reference came to tie with one.
  const v = classifyWithRules(
    "A note",
    "Regarding your application for the Backend Engineer position.",
    null,
  );
  assert.equal(v.scores.applied, 1, JSON.stringify(v.scores));
});

test("a report beats the assertion at equal score, and the margin is unmoved", () => {
  // The corpus's `observed-rejection` shape: a courtesy opener (`applied`,
  // weak) against a volume apology (`rejection`, weak). 1–1.
  const v = classifyWithRules(
    "Important information about your application to Thorncombecross Dynamics",
    "Hi Ayush, Thank you for your interest in Thorncombecross Dynamics and our " +
      "Systems Engineer position. As you can imagine we received many qualified " +
      "applicants and some aligned better than others.",
    "no-reply@ats.rippling.com",
  );
  assert.equal(v.scores.applied, v.scores.rejection, JSON.stringify(v.scores));
  assert.equal(v.scores.applied, 1, JSON.stringify(v.scores));
  assert.equal(v.category, "rejection", JSON.stringify(v.scores));
  // A tie is still read as a tie. The rule decides WHICH verdict, never HOW
  // SURE — raising confidence on a zero margin is how a coin toss becomes a
  // fact stated to the user.
  assert.ok(v.confidence < 0.7, `confidence ${v.confidence}`);
});

test("the tie-break never overturns a score", () => {
  // The same offer with `applied` given a clear lead by its own strong
  // pattern: "thank you for applying" is +3 on top of the reference's +1.
  const v = classifyWithRules(
    "Thanks for applying",
    "Thank you for applying. We have received your application for the " +
      "Backend Engineer position and it is in review.",
    null,
  );
  assert.equal(v.category, "applied", JSON.stringify(v.scores));
});

/**
 * THE TESTS ABOVE PASS WITHOUT THE TIE-BREAK, and that is measured rather
 * than assumed — reverting `winnerFirst` to `sort((a, b) => b[1] - a[1])`
 * leaves all four green.
 *
 * The reason is worth writing down, because it is the whole argument for
 * porting this at all. `rules.json` orders its categories `rejection`,
 * `interview`, `offer`, `applied`, `pending_application`, `assessment`, and
 * `Object.entries` preserves that. So for the two ties the corpus actually
 * contains — applied/offer and applied/rejection — key order ALREADY put the
 * report first, and this engine happened to be right where Python was wrong.
 * Right by accident is indistinguishable from right, until the first case
 * where the accident points the other way.
 *
 * `applied` sits BEFORE `pending_application` and `assessment` in that same
 * key order, so those two ties are where the accident and the rule disagree.
 * The comparator is exported and tested directly for the same reason
 * `winner_first` is a named function in Python: what is under test is the
 * SORT, and building text that ties `applied` against each of five categories
 * would be a test of the patterns.
 */
const CATEGORIES = [
  "rejection",
  "interview",
  "offer",
  "applied",
  "pending_application",
  "assessment",
  "follow_up",
];

for (const report of ["rejection", "interview", "offer", "assessment", "pending_application"]) {
  test(`winnerFirst: ${report} beats applied at equal score`, () => {
    const scores = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
    scores.applied = 3;
    scores[report] = 3;
    const ordered = winnerFirst(scores);
    assert.equal(ordered[0][0], report, JSON.stringify(ordered.slice(0, 3)));
    // The margin is untouched, so the confidence cannot move.
    assert.equal(ordered[0][1] - ordered[1][1], 0);
  });
}

test("winnerFirst leaves a tie between two reports where it was", () => {
  // Neither entails the other, so this rule has nothing true to say about the
  // pair and deliberately does not pretend to. A known limit, not coverage.
  const scores = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
  scores.rejection = 3;
  scores.interview = 3;
  const ordered = winnerFirst(scores);
  assert.deepEqual(
    new Set([ordered[0][0], ordered[1][0]]),
    new Set(["rejection", "interview"]),
  );
});

test("winnerFirst never overturns a score, in either direction", () => {
  for (const leader of ["applied", "offer"]) {
    const scores = Object.fromEntries(CATEGORIES.map((c) => [c, 0]));
    scores.applied = 3;
    scores.offer = 3;
    scores[leader] = 4;
    assert.equal(winnerFirst(scores)[0][0], leader);
  }
});
