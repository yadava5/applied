/**
 * Unit tests for the review queue's hold reason (`lib/dashboard/review.ts`).
 *
 * THE DEFECT THIS EXISTS FOR (#507). The queue's "why is this here" line was
 * derived from `confidence` alone:
 *
 *     item.confidence >= AUTO_FILE_GATE
 *       ? "cleared the gate · held for a missing employer name"
 *       : `below the ${AUTO_FILE_GATE} gate · your call decides it`
 *
 * so every confident held row claimed a missing employer, whatever had
 * actually stopped it. On the board it was reported about, that guess was
 * RIGHT — those three rows really did fail employer resolution (#512) — which
 * is precisely why it needed a test rather than a look. A label that is
 * correct by coincidence is indistinguishable from one that is correct, until
 * the first row where the two diverge.
 *
 * So the assertions below are written to fail against the OLD behaviour, not
 * merely to pass against the new one. `which_application` is the case the old
 * code got wrong, and the test names that specifically instead of asserting
 * that "some sentence renders" — which the guess satisfies.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { HOLD_REASONS, holdReasonSentence } from "../../lib/dashboard/review.ts";

const GATE = 0.85;

test("every reason gets a sentence, and no two reasons share one", () => {
  const sentences = HOLD_REASONS.map((r) => holdReasonSentence(r, GATE));
  for (const [i, s] of sentences.entries()) {
    assert.equal(typeof s, "string", `${HOLD_REASONS[i]} produced no sentence`);
    assert.ok(s.length > 0, `${HOLD_REASONS[i]} produced an empty sentence`);
  }
  assert.equal(
    new Set(sentences).size,
    HOLD_REASONS.length,
    "two hold reasons render the same sentence, so the row cannot tell them apart",
  );
});

/**
 * THE MUTATION-PROOF ASSERTION.
 *
 * `which_application` is a row whose employer IS known — it is held because
 * the employer has several applications and the mail names no role. The old
 * code sent it the missing-employer sentence, because it scores above the
 * gate. Pinning it to "not about the employer" is what makes this suite go red
 * if anyone reintroduces an inference from `confidence`.
 */
test("a which-application hold is never described as a missing employer", () => {
  const sentence = holdReasonSentence("which_application", GATE);
  assert.doesNotMatch(
    sentence,
    /employer/i,
    "a row held because it could not be placed is being told its employer is missing",
  );
  assert.match(sentence, /which/i);
});

test("the only reason that mentions a missing employer is the one that means it", () => {
  const mentioning = HOLD_REASONS.filter((r) =>
    /couldn't name the employer/i.test(holdReasonSentence(r, GATE) ?? ""),
  );
  assert.deepEqual(mentioning, ["no_employer"]);
});

test("the gate is rendered from the argument, not hard-coded", () => {
  assert.match(holdReasonSentence("below_gate", 0.85), /0\.85/);
  assert.match(holdReasonSentence("below_gate", 0.6), /0\.6/);
});

/**
 * No fallback sentence. An older backend sends no reason at all, and a newer
 * one may send a reason this build predates; both must render nothing rather
 * than borrow a plausible sentence from a case the row does not belong to.
 */
test("an absent or unrecognised reason renders nothing", () => {
  for (const absent of [null, undefined, "", "a_reason_from_the_future"]) {
    assert.equal(
      holdReasonSentence(absent, GATE),
      null,
      `${JSON.stringify(absent)} produced a sentence instead of silence`,
    );
  }
});

/**
 * WIRING. The two tests above pass perfectly well against a component that
 * never calls this function — which is the shape of the original bug, where
 * the sentence was computed at the call site. This asserts the call site
 * actually reads the backend's field, and that the old literal is gone.
 */
test("TRIPWIRE: the queue row renders the reported reason, not a guess", () => {
  const source = readFileSync(
    new URL("../../components/dashboard/ReviewQueue.tsx", import.meta.url),
    "utf8",
  );
  assert.match(
    source,
    /holdReasonSentence\(item\.hold_reason/,
    "ReviewQueue no longer renders the reported hold reason",
  );
  // The old sentence may still be QUOTED in a comment explaining the bug, so
  // strip comments before looking for it as live code.
  const code = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.doesNotMatch(
    code,
    /held for a missing employer name/,
    "the inferred sentence is back in the component",
  );
  assert.doesNotMatch(
    code,
    /confidence >= AUTO_FILE_GATE\s*\n?\s*\?\s*"cleared the gate/,
    "the confidence-based guess is back in the component",
  );
});

test("confirm_employer puts the name we read in front of the user", () => {
  const sentence = holdReasonSentence("confirm_employer", GATE, "Granitethwaitevale");
  assert.match(sentence, /Granitethwaitevale/);
  // …and it must NOT be the sentence #512 is about. This row's employer IS
  // nameable; that is the entire reason it gets a different reason code.
  assert.doesNotMatch(sentence, /couldn't name the employer/i);
});

test("confirm_employer never invents a name it was not given", () => {
  // The backend is the only reader of the message body. If the name did not
  // travel, the web must not re-read the snippet to produce one — a second
  // reading by different code is how the queue came to print a sentence that
  // contradicted the row above it.
  const sentence = holdReasonSentence("confirm_employer", GATE, null);
  assert.equal(typeof sentence, "string");
  assert.doesNotMatch(sentence, /null|undefined/);
});

test("not_fileable blames neither the employer nor the score", () => {
  const sentence = holdReasonSentence("not_fileable", GATE);
  assert.doesNotMatch(sentence, /employer/i);
  assert.doesNotMatch(sentence, new RegExp(String(GATE).replace(".", "\\.")));
});

test("TRIPWIRE: the row hands the suggested employer to the sentence", () => {
  // Without this the backend can report `confirm_employer` with a name and the
  // row still renders the nameless fallback, which reads as a regression to
  // the very sentence this replaced.
  const src = readFileSync(
    new URL("../../components/dashboard/ReviewQueue.tsx", import.meta.url),
    "utf8",
  );
  // The third argument may be wrapped in `safeText` (#424): the suggested
  // employer is a name the backend read OUT of a stranger's mail, so it can
  // carry a direction override like any other header-derived string. The
  // wrapper is optional in this pattern and the FIELD is not — swapping it
  // for `null`, or for any other field, still reds this, which is the whole
  // point of the tripwire.
  assert.match(
    src,
    /holdReasonSentence\(\s*item\.hold_reason,\s*AUTO_FILE_GATE,\s*(?:safeText\(\s*)?item\.suggested_employer/,
  );
});
