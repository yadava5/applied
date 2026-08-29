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
 * DISAGREEMENTS PINNED ON PURPOSE.
 *
 * s06 is STALE, and it is the fixture that is stale — not a rules bug. Its
 * stored rejection verdict was written when `rules.json` scored that body at
 * 90%; the table has moved eight times since (#324, #356, #444, #455, #459,
 * #498, #524) and the same body now scores 12 with a margin of 12, which is the
 * 95% tier. Verified 2026-08-29 against BOTH engines — the browser port and
 * `backend/jobtracker/classifier/rules.py` — which agree with each other on all
 * eleven messages and disagree with the fixture only here.
 *
 * It is pinned rather than corrected because correcting it is a product change
 * to a public page: `/demo/inbox` renders "rejection @ 90% — regex answered"
 * beside a live recompute reading 95%, and `tests/e2e/sample-inbox.spec.ts`
 * asserts that stale string is visible.
 *
 * WHEN THE FIXTURE IS CORRECTED THIS ENTRY MUST GO. It asserts the exact pair
 * of values on both sides, so it reds if the fixture is fixed, it reds if the
 * rules move again, and a second entry appearing here shows up in a diff.
 */
const PINNED_STALE = new Map([
  [
    "s06",
    {
      why: "fixture predates the rejection patterns added since; both engines say 0.95",
      stored: { category: "rejection", confidence: 0.9 },
      computed: { category: "rejection", confidence: 0.95 },
    },
  ],
]);

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
  const pinsSeen = [];

  for (const email of emails) {
    messages += 1;

    // The one recompute. Same call the page makes; see the signature note above.
    const live = classifyWithRules(email.subject, email.body);

    // Every message walked layer 1, so every trace carries its step — even the
    // three where a deeper layer rendered the final call.
    const step = email.verdict.trace.find((s) => s.layer === "rules");
    assert.ok(step, `${email.id} has no "rules" step in its trace; nothing to compare.`);

    const pin = PINNED_STALE.get(email.id);
    if (pin) {
      pinsSeen.push(email.id);
      // The pin is itself a gate: it names what the rules layer computes TODAY.
      assert.equal(
        live.category,
        pin.computed.category,
        `${email.id} is pinned as a known-stale fixture (${pin.why}) but the rules layer now ` +
          `computes category "${live.category}", not "${pin.computed.category}". The pin is out ` +
          "of date: re-verify against backend/jobtracker/classifier/rules.py and update it.",
      );
      assert.equal(
        live.confidence,
        pin.computed.confidence,
        `${email.id} is pinned as a known-stale fixture (${pin.why}) but the rules layer now ` +
          `computes ${live.confidence}, not ${pin.computed.confidence}. The pin is out of date: ` +
          "re-verify against backend/jobtracker/classifier/rules.py and update it.",
      );
      // And it pins the fixture's side too, so CORRECTING sampleInbox.ts reds
      // this file and forces the pin to be deleted in the same commit.
      assert.equal(
        step.confidence,
        pin.stored.confidence,
        `${email.id} no longer holds the disagreement pinned in PINNED_STALE: its stored rules ` +
          `confidence is ${step.confidence}, not the pinned ${pin.stored.confidence}. If ` +
          "sampleInbox.ts was corrected, delete the entry (and fix " +
          "tests/e2e/sample-inbox.spec.ts, which asserts the same stale string is on screen). " +
          "If it moved some other way, re-verify it before re-pinning.",
      );
    }

    // What the fixture SHOULD say. For a pinned row that is the stale value it
    // is known to hold; for every other row it is whatever the rules layer just
    // computed. Nothing else is ever an accepted answer.
    const expected = pin ? pin.stored : { category: live.category, confidence: live.confidence };

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

  // The pin is scoped: one known disagreement, and no message may quietly join
  // it. A new entry is a deliberate, reviewable line in a diff.
  //
  // Sorted on both sides — the fixture's order is a curated reading order and a
  // pin declared in a different one is not a defect. This must fail for the
  // reason it names, which is a pinned id that no longer matches any row.
  assert.deepEqual(
    [...pinsSeen].sort(),
    [...PINNED_STALE.keys()].sort(),
    "PINNED_STALE names a message the walk never reached. Every pinned disagreement must " +
      "correspond to a live fixture row.",
  );
  assert.equal(
    PINNED_STALE.size,
    1,
    `PINNED_STALE holds ${PINNED_STALE.size} known disagreements. Each one is a public page ` +
      "stating something the shipped classifier does not; adding another needs the same argument " +
      "the s06 entry carries, and removing the last one should delete the map.",
  );
});
