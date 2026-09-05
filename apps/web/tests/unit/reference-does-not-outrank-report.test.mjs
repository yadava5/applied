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

const { classifyWithRules, winnerFirst, REPORTS_ON_AN_APPLICATION } = await import(
  "../../lib/demo/rulesLayer.ts"
);
const rulesRaw = (await import("../../lib/demo/rules.json")).default;

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
 * THE FOUR TESTS ABOVE PASS WITHOUT THE TIE-BREAK, and that is measured rather
 * than assumed — reverting `winnerFirst` to `sort((a, b) => b[1] - a[1])`
 * leaves all four green.
 *
 * The reason is the whole argument for porting this at all. `rules.json` orders
 * its categories `rejection`, `interview`, `offer`, `applied`,
 * `pending_application`, `assessment`, and `Object.entries` preserves that
 * while `Array.prototype.sort` is stable. So for the two ties the corpus
 * actually contains — applied/offer and applied/rejection — key order ALREADY
 * put the report first, and this engine happened to be right where Python was
 * wrong. Right by accident is indistinguishable from right, until the first
 * case where the accident points the other way.
 *
 * THE PARAMETERISED BLOCK BELOW USED TO INHERIT THAT ACCIDENT (#606). It built
 * one `scores` object per case, in a fixed order, so deleting the tie-break
 * reddened only the two reports that sit AFTER `applied` in that order:
 *
 *     RED    assessment, pending_application
 *     GREEN  rejection, interview, offer
 *
 * Three of five cases were passing on insertion order rather than on the rule
 * they name, and would have gone on passing if the rule were deleted. So each
 * case now runs in BOTH orders. The `report inserted first` arm is the one the
 * old test had; the `applied inserted first` arm is the one that can only be
 * green if the comparator, and not the ordering, decided the tie.
 */

/**
 * The universe of categories, DERIVED from `rules.json` rather than copied, so
 * a category added there is tied against `applied` here without anyone
 * remembering to extend a list. The order is taken exactly as it comes: the
 * point of the two arms is that this order cannot matter.
 */
const CATEGORIES = Object.keys(rulesRaw.categories);

/**
 * The claim, WRITTEN OUT rather than imported. Looping over
 * `REPORTS_ON_AN_APPLICATION` itself would compare the module to its own
 * definition and stay green through any edit to it — a category dropped from
 * the set would simply stop being tested, silently. The next test pins the two
 * together so drift in either direction is loud.
 */
const REPORTS = ["rejection", "interview", "offer", "assessment", "pending_application"];

test("the set the comparator uses is the set this file claims", () => {
  assert.deepEqual(
    new Set(REPORTS_ON_AN_APPLICATION),
    new Set(REPORTS),
    "REPORTS_ON_AN_APPLICATION has moved; the cases below no longer cover it",
  );
});

test("every category this file names still exists in rules.json", () => {
  for (const cat of [...REPORTS, "applied"]) {
    assert.ok(CATEGORIES.includes(cat), `${cat} is not a category in rules.json`);
  }
});

/**
 * `Object.entries` preserves insertion order and `sort` is stable, so a tie
 * falls to whichever category was inserted first unless the comparator decides
 * it. Building the two tied categories in a chosen order is therefore the whole
 * experiment; the zero-scored remainder cannot affect it, and is present only
 * so the input looks like a real score map.
 */
function tiedScores(first, second) {
  const scores = {};
  scores[first] = 3;
  scores[second] = 3;
  for (const cat of CATEGORIES) if (!(cat in scores)) scores[cat] = 0;
  return scores;
}

for (const report of REPORTS) {
  for (const [label, build] of [
    ["applied inserted first", () => tiedScores("applied", report)],
    ["report inserted first", () => tiedScores(report, "applied")],
  ]) {
    test(`winnerFirst: ${report} beats applied at equal score (${label})`, () => {
      const ordered = build();
      const sorted = winnerFirst(ordered);
      assert.equal(sorted[0][0], report, JSON.stringify(sorted.slice(0, 3)));
      // The margin is untouched, so the confidence cannot move.
      assert.equal(sorted[0][1] - sorted[1][1], 0);
    });
  }
}

/**
 * The directional control #606 asked for, stated as its own invariant: the
 * answer must be a function of the comparator alone. Today reversing the
 * insertion order changes nothing; with the tie-break removed it changes the
 * winner for all five reports, which is precisely what the old single-order
 * cases could not see.
 */
test("reversing the insertion order changes no answer", () => {
  for (const report of REPORTS) {
    const appliedFirst = winnerFirst(tiedScores("applied", report))[0][0];
    const reportFirst = winnerFirst(tiedScores(report, "applied"))[0][0];
    assert.equal(
      appliedFirst,
      reportFirst,
      `${report}: insertion order decided the winner, not the comparator`,
    );
    assert.equal(appliedFirst, report);
  }
});

test("winnerFirst leaves a tie between two reports where it was", () => {
  // Neither entails the other, so this rule has nothing true to say about the
  // pair and deliberately does not pretend to. A known limit, not coverage.
  const ordered = winnerFirst(tiedScores("rejection", "interview"));
  assert.deepEqual(
    new Set([ordered[0][0], ordered[1][0]]),
    new Set(["rejection", "interview"]),
  );
});

test("winnerFirst never overturns a score, in either direction", () => {
  for (const leader of ["applied", "offer"]) {
    const scores = tiedScores("applied", "offer");
    scores[leader] = 4;
    assert.equal(winnerFirst(scores)[0][0], leader);
  }
});
