/**
 * THE DEMO CHECKS ITS OWN VERDICTS AGAINST THE RULES IT SHIPS (#465).
 *
 * `lib/demo/sampleInbox.ts` hard-codes a verdict per sample email — category,
 * confidence, method, and a per-layer trace whose prose restates the same two
 * values. `lib/demo/rulesLayer.ts` is the live port of layer 1, and
 * `components/demo/SampleInbox.tsx` renders the two side by side on
 * `/demo/inbox`, claiming the stored trace is real output rather than a canned
 * animation. Until this file, nothing compared them: the fixture could claim
 * the classifier says X while the classifier shipped Y, with every gate green.
 *
 * The direction is not symmetric. `rulesLayer.ts` and `rules.json` are the
 * PRODUCT; `sampleInbox.ts` is a fixture describing it. When they disagree the
 * fixture is what is wrong. Do not edit a pattern to make this file green — you
 * would be changing what the classifier does so a demo's caption stays true.
 *
 * ---------------------------------------------------------------------------
 * WHAT IS COMPARED — 19 of the file's 27 hard-coded confidences.
 *
 *   - The rules step of all ELEVEN traces. Every message walked layer 1, and
 *     the step records what layer 1 said even when it passed the message on
 *     ("top other @ 50% — not confident enough"). So its `confidence`, the
 *     category and percentage in its `note`, and its `state` are all
 *     recomputable. That is 11 confidences.
 *   - The FINAL category and confidence of the EIGHT messages layer 1 answered
 *     (`method: "rules"`). For those the rules layer is the whole verdict.
 *     That is the other 8.
 *
 * WHAT IS DELIBERATELY NOT COMPARED — the remaining 8 confidences.
 *
 * They belong to layers 2 and 3, the e5 embedding similarity and the SetFit
 * head, which need a 23 MB ONNX model the browser cannot load under the app's
 * CSP and which have no port in this tree at all. Nothing here can recompute
 * them, and re-deriving them from anything else would be inventing a number:
 *
 *     p9  final 0.8772 (embeddings), trace embeddings 0.8772
 *     s02 final 0.1922 (setfit),     trace embeddings 0.6866, setfit 0.1922
 *     s09 final 0.1947 (setfit),     trace embeddings 0.8065, setfit 0.1947
 *
 * Their final CATEGORIES (p9 `interview`, s02/s09 `needs_review`) and their
 * `method` values are out of reach for the same reason. What this file still
 * holds for those three is that layer 1 did not answer them and that the rules
 * step says exactly what the rules layer says.
 *
 * ---------------------------------------------------------------------------
 * THE SIGNATURE IS A DECISION, AND s11 IS WHERE IT SHOWS.
 *
 * The comparison runs `classifyWithRules(subject, body)` with NO sender,
 * because that is the call `SampleInbox.tsx` makes on the page and it is the
 * call the fixture was generated from. It is not the call production makes:
 * `classify(subject, body, sender_email)` gives a known ATS domain a +0.05
 * boost on lifecycle categories.
 *
 * One message discriminates. s11 arrives from `no-reply@lever.co` and is
 * `applied`, so with its sender it scores 0.95; the fixture stores 0.90, which
 * is the no-sender answer. Adding the sender argument here would turn s11 red
 * with no explanation on screen, so if that is ever the right change it is a
 * change to the fixture and to the page, not to this line.
 *
 * The confidences are compared with strict equality, which is safe only on that
 * signature: every value it can return is a literal off the tier table, while
 * the ATS path adds 0.05 and is not float-exact. Belt and braces, since s11
 * reds first, but it is the second thing to settle if the sender is ever
 * passed.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { importApp } from "./helpers/appModule.mjs";

const { classifyWithRules } = await importApp("lib/demo/rulesLayer.ts");
const { sampleEmails } = await importApp("lib/demo/sampleInbox.ts");

/** Floors, not targets — see `scripts/assert-unit-suite-ran.mjs` for the house
 *  argument. A fixture reshaped into something the walk cannot see, a renamed
 *  export, or a trace that stops carrying a rules step, all have to fail loudly
 *  here rather than quietly compare nothing. Raise these when the fixture
 *  grows; lowering one is a claim that coverage was removed on purpose. */
const FLOOR_MESSAGES = 11;
const FLOOR_CONFIDENCES = 19;
const FLOOR_NOTES = 11;

/**
 * NOTHING IS PINNED HERE, AND THAT IS THE POINT (#586).
 *
 * One disagreement used to be. s06's stored rejection verdict was written when
 * `rules.json` scored that body at 90%; the table moved eight times since
 * (#324, #356, #444, #455, #459, #498, #524) and the same body now scores 12
 * with a margin of 12, which is the 95% tier. A `PINNED_STALE` map held that
 * disagreement with the exact values on both sides rather than correcting it,
 * because correcting it was a product change to a public page: `/demo/inbox`
 * rendered "rejection @ 90% — regex answered" beside a live recompute reading
 * 95%, and `tests/e2e/sample-inbox.spec.ts` asserted the stale string was
 * visible.
 *
 * #586 took that decision and corrected the fixture, so the map is gone —
 * which is what its own closing assertion said to do with the last entry. The
 * walk below now admits NO exceptions: every recomputable value must equal
 * what the rules layer computes, for all eleven messages.
 *
 * IF A DISAGREEMENT EVER HAS TO BE PINNED AGAIN, re-add the map with the
 * argument that one carried — both sides' values written out, so the pin reds
 * when the fixture is corrected AND when the rules move again, and a second
 * entry has to appear in a diff. Do not instead loosen an assertion below;
 * that lets a stale fixture through silently, which is the whole failure this
 * file exists to catch.
 */

/** The trace's percentage form: `0.95` -> `95%`. */
const pct = (confidence) => `${Math.round(confidence * 100)}%`;

const emails = sampleEmails();

const disagreement = (email, field, stored, computed) =>
  [
    `${email.id} "${email.subject}": stored ${field} is ${JSON.stringify(stored)},`,
    `the rules layer computes ${JSON.stringify(computed)}.`,
    "lib/demo/rulesLayer.ts is the product and is right by construction;",
    "lib/demo/sampleInbox.ts is a fixture describing it and is what to correct.",
    "Do NOT edit rules.json or rulesLayer.ts to match a stale fixture.",
  ].join(" ");

test("every stored verdict is what lib/demo/rulesLayer.ts actually computes", () => {
  let messages = 0;
  let confidences = 0;
  let notes = 0;

  for (const email of emails) {
    messages += 1;

    // The one recompute. Same call the page makes; see the signature note above.
    const live = classifyWithRules(email.subject, email.body);

    // Every message walked layer 1, so every trace carries its step — even the
    // three where a deeper layer rendered the final call.
    const step = email.verdict.trace.find((s) => s.layer === "rules");
    assert.ok(step, `${email.id} has no "rules" step in its trace; nothing to compare.`);

    // What the fixture SHOULD say: whatever the rules layer just computed.
    // Nothing else is ever an accepted answer.
    const expected = { category: live.category, confidence: live.confidence };

    // ---- The rules step of the trace, for all eleven messages. ----
    // Structural, not thresholded: the step said "answered" exactly when the
    // final method is "rules". Deriving it from a confidence cutoff instead
    // would invent a rule the product has not settled (SampleInbox.tsx's
    // comment says 0.90, lib/classification/gate.ts says 0.85, and no fixture
    // sits between them, so such an assertion could not tell them apart).
    const answered = email.verdict.method === "rules";
    assert.equal(
      step.state,
      answered ? "answered" : "passed",
      disagreement(email, "trace rules state", step.state, answered ? "answered" : "passed"),
    );

    assert.equal(
      step.confidence,
      expected.confidence,
      disagreement(email, "trace rules confidence", step.confidence, expected.confidence),
    );
    confidences += 1;

    // The note restates the category and the confidence in prose. A number
    // checked in one place and re-typed in another is how a false claim ships
    // with every gate green, so it is derived here rather than eyeballed.
    const note = answered
      ? `${expected.category} @ ${pct(expected.confidence)} — regex answered`
      : `top ${expected.category} @ ${pct(expected.confidence)} — not confident enough`;
    assert.equal(step.note, note, disagreement(email, "trace rules note", step.note, note));
    notes += 1;

    // When layer 1 answered, the deeper layers must say they never ran. That is
    // derived from the rules layer answering, not from the fixture agreeing
    // with itself.
    if (answered) {
      for (const deeper of email.verdict.trace.filter((s) => s.layer !== "rules")) {
        assert.deepEqual(
          { state: deeper.state, confidence: deeper.confidence },
          { state: "skipped", confidence: null },
          `${email.id}: layer 1 answered, so the ${deeper.layer} layer never ran, but the ` +
            `fixture records state "${deeper.state}" at ${deeper.confidence}.`,
        );
      }

      // ---- The final verdict, for the eight messages layer 1 answered. ----
      assert.equal(
        email.verdict.category,
        expected.category,
        disagreement(email, "category", email.verdict.category, expected.category),
      );
      assert.equal(
        email.verdict.confidence,
        expected.confidence,
        disagreement(email, "confidence", email.verdict.confidence, expected.confidence),
      );
      confidences += 1;
    } else {
      // Layer 1 passed, so the final call came from a layer with no port here.
      // The one thing still checkable is that it did not claim to be the rules.
      assert.notEqual(
        email.verdict.method,
        "rules",
        `${email.id} says method "rules" while its rules step did not answer.`,
      );
    }
  }

  // ---- Vacuity guard. ----
  assert.ok(
    messages >= FLOOR_MESSAGES,
    `walked ${messages} sample emails, floor is ${FLOOR_MESSAGES}. sampleEmails() returned ` +
      "fewer messages than this gate was built against — a shrunken, renamed or reshaped " +
      "fixture must fail here rather than silently compare nothing.",
  );
  assert.ok(
    confidences >= FLOOR_CONFIDENCES,
    `compared ${confidences} stored confidences, floor is ${FLOOR_CONFIDENCES}. Fewer values ` +
      "reached the comparison than this gate was built against; see the header for the 19 that " +
      "are meant to be recomputable and the 8 that are deliberately not.",
  );
  assert.ok(
    notes >= FLOOR_NOTES,
    `compared ${notes} trace notes, floor is ${FLOOR_NOTES}. The prose restating each verdict ` +
      "stopped being checked, which is exactly how a re-typed number drifts.",
  );
});
