/**
 * TWO REVIEW COUNTS, TWO QUESTIONS, AND THEY MUST NOT SHARE A PHRASE (#445).
 *
 * Production, one account, one moment: the dashboard said "Needs review (8)"
 * and the Inbox said "needs review 9" and rendered 9 rows. Both were right.
 *
 *   - the dashboard counts the WORK QUEUE — `classified_as = NEEDS_REVIEW`
 *     AND `application_id IS NULL` AND `is_reviewed = false`, deduped by
 *     `pipeline.review_dedup_key`;
 *   - the Inbox chip counts STORED MAIL carrying that verdict, one entry per
 *     message, whatever its linkage or reviewed state. `applications.py`
 *     spells out why it must NOT adopt the queue's predicates: a message
 *     reviewed once would drop out for good, a message linked to a row would
 *     drop out too, and an account whose mail all classified confidently would
 *     get an empty audit screen.
 *
 * So the inbox is always the larger number and the gap is real: messages
 * already reviewed, messages already linked, and same-application siblings in
 * one thread. Reconciling the queries re-creates two bugs. The fix is words.
 *
 * WHAT THIS FILE DEFENDS. Not the numbers — the LABELS. A later cleanup that
 * notices two names for "the review thing" and unifies them puts the identical
 * phrase back on two numbers that are allowed to differ, and re-creates the
 * confusion with every other test still green. Both phrases are exported
 * constants and both are IMPORTED here, so unification cannot pass: the moment
 * `REVIEW_QUEUE_LABEL` and `CATEGORY_META.needs_review.chipLabel` agree, the
 * first test reds.
 *
 * Asserting `"to review" !== "held for review"` against literals would be the
 * `checks-that-cannot-fail` shape — true forever, whatever the product says.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { REVIEW_QUEUE_LABEL } from "../../lib/dashboard/review.ts";
import { CATEGORY_META, categoryChips } from "../../lib/gmail/types.ts";

const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (rel) => readFileSync(join(WEB_ROOT, rel), "utf8");

/** Prose about the fix is not the fix — every source assertion reads code
 *  only. Same helper as `locked-pages-declare-their-scroller.test.mjs`. */
function withoutComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.replace(/(^|[^:'"`\\])\/\/.*$/, "$1"))
    .join("\n");
}

/** The Inbox's word for a count of stored mail with the review verdict. */
const chipLabel = () => CATEGORY_META.needs_review.chipLabel;

test("the queue's label and the inbox chip's label are different words", () => {
  const queue = REVIEW_QUEUE_LABEL;
  const chip = chipLabel();

  assert.ok(typeof chip === "string" && chip.length > 0, "the needs_review chip has no label");
  assert.notEqual(
    chip,
    queue,
    `both review counts are labelled "${queue}". The dashboard counts a work queue and the ` +
      "inbox counts stored mail; the inbox is always the larger number, so one phrase over " +
      "both is what #445 was filed about. Give them different words rather than the same one.",
  );

  // Not merely unequal — neither may read as the other with a word bolted on.
  // "held to review" vs "to review" would pass a bare notEqual and put the
  // reader right back where they started.
  assert.ok(
    !chip.includes(queue) && !queue.includes(chip),
    `"${queue}" and "${chip}" are one phrase inside the other, which is not a distinction a ` +
      "reader glancing between two screens can make.",
  );
});

test("the chip label is an override, not a rename — the row badge keeps the verdict's name", () => {
  const chips = categoryChips({ needs_review: 9, applied: 3 });
  const held = chips.find((c) => c.value === "needs_review");

  assert.ok(held, "needs_review has no chip at a non-zero count");
  assert.equal(held.label, chipLabel(), "the chip does not use `chipLabel`");
  assert.equal(held.count, 9);

  // A chip counts a SET; a badge names ONE message's verdict. They are
  // different statements, and collapsing `chipLabel` back into `label` would
  // rename every row badge and the application trail with it.
  assert.notEqual(
    CATEGORY_META.needs_review.label,
    chipLabel(),
    "`chipLabel` no longer overrides anything — the chip and the row badge say the same thing",
  );

  // Every other category is unaffected: one vocabulary, one exception.
  for (const c of chips.filter((c) => c.value !== "needs_review")) {
    assert.equal(c.label, CATEGORY_META[c.value].label, `${c.value} grew a chip-only label`);
  }
});

/**
 * Everything above holds two constants apart. These hold the SURFACES to them —
 * a constant nothing renders is a distinction that exists only in this file.
 */
const QUEUE_SURFACES = [
  "components/dashboard/ReviewQueue.tsx", // the card header
  "components/dashboard/PipelinePulse.tsx", // the auto-filed cell's link
  "components/dashboard/PulseDetail.tsx", // the provenance panel's row
  "lib/dashboard/boardPrefs.ts", // the empty board's subtitle
];

test("every surface that counts the work queue reads the shared label", () => {
  // Stated, not assumed: `includes(undefined)` searches for the STRING
  // "undefined", which several of these files contain (`: undefined` in JSX),
  // so a missing chip label would red the loop below for the wrong reason.
  const inboxPhrase = chipLabel();
  assert.equal(typeof inboxPhrase, "string", "the needs_review chip has no label to collide with");

  for (const rel of QUEUE_SURFACES) {
    const code = withoutComments(read(rel));
    assert.ok(
      code.includes("REVIEW_QUEUE_LABEL"),
      `${rel} counts the review queue with a phrase of its own. Four surfaces printed three ` +
        "different wordings for this one number before #445; import the constant.",
    );
    assert.ok(
      !code.includes(inboxPhrase),
      `${rel} prints "${inboxPhrase}", which is the INBOX's phrase for a different and larger ` +
        "count. That is the collision #445 removed.",
    );
  }
});

test("the inbox's filter plate says on screen what its counts are over", () => {
  const code = withoutComments(read("components/mail/FiledMailList.tsx"));

  // The explanation is rendered text, not a tooltip and not a comment: the
  // reader who saw 8 on the dashboard and 9 here has to be able to learn why
  // by reading the screen.
  assert.match(
    code,
    /counts every stored message/,
    "the filed-mail filters no longer say what they count over",
  );
  assert.ok(
    code.includes("REVIEW_QUEUE_LABEL"),
    "the inbox names the dashboard's count with a literal of its own, which will drift from it",
  );
});

/**
 * THE CONTROL — measured, not asserted. Six mutations applied to this tree,
 * each reverted, `node --test` on this file (and on `empty-subtitle.test.mjs`
 * for the last one). Baseline and every restore: 4 pass, 0 fail.
 *
 *   1. `chipLabel: "held for review"` → `"to review"` in `CATEGORY_META` — the
 *      unification this file exists to catch. Reds test 1 only, and that is
 *      the right answer: the four dashboard surfaces reference the CONSTANT,
 *      so none of them holds a literal that could collide.
 *   2. `chipLabel` deleted outright (the chip falls back to the badge's "needs
 *      review", which is exactly where production was). Reds tests 1, 2 and 3.
 *   3. `meta.chipLabel ?? meta.label` → `meta.label` in `categoryChips`. Reds
 *      test 2 — the override stops reaching the chip.
 *   4. the literal `held for review` restored in `PipelinePulse.tsx`. Reds
 *      test 3, naming that file.
 *   5. the explanation <p> reworded out of `FiledMailList.tsx`. Reds test 4.
 *   6. `boardPrefs.ts` back to its own `need review` literal. Reds test 3
 *      here AND "held mail is counted with the queue's own words" in
 *      `empty-subtitle.test.mjs` — the behavioural half of the same claim.
 */
