/**
 * A RESCINDED OFFER IS HELD FOR REVIEW IN THE BROWSER ENGINE TOO (#417).
 *
 * This file replaces `rescission-divergence-417.test.mjs`, which pinned the
 * gap rather than closing it: `lib/demo/rulesLayer.ts` mirrored
 * `MIN_ASSERTED_CHARS` and `stripQuotedHistory` but not the cap, so "We must
 * withdraw the offer." — 27 characters above a quoted offer, under the floor,
 * therefore scored through its own quote — came back `offer` at 0.95 and the
 * demo asserted an offer nobody holds. That pin was written to go red when the
 * port landed and it did, on the confidence assertion: `0.8 !== 0.95`.
 *
 * WHAT IS ASSERTED HERE, and why each case has to be in the file:
 *
 *   1. The fixture really is under the floor. Without this the rest could pass
 *      for the wrong reason — a stripped quote reaches `other` at 0.50, which
 *      is also "not auto-filed" and is not what this measures.
 *   2. The cap: `offer` at exactly `REFUTED_CONFIDENCE`, under the 0.85 gate.
 *   3. THE NEAR-MISS THAT MUST NOT MOVE. "Thursday works for me." over a
 *      quoted invitation is under the floor too and is RIGHT to score its
 *      quote. A cap that fires on every fallback passes case 2 and sends that
 *      correct auto-file to the review queue. Same for "fyi" over a quoted
 *      rejection, which is `rejection` — a category retraction may never touch.
 *   4. The floor is real, walked across 39/40 with the quote held constant.
 *   5. The ORDER against the ATS bonus, with a liveness control first: the
 *      +0.05 has to be shown firing for that sender on a comparable message,
 *      or "the bonus did not push it over the gate" is a sentence about a
 *      domain the engine never recognised.
 *   6. Lockstep on the one vocabulary this port could not derive.
 *      `_RETRACTION` is read out of `backend/jobtracker/classifier/rules.py`
 *      itself, so the oracle is the Python engine rather than a copy of it,
 *      and a change on that side that is not made here goes red. That
 *      cross-tree read costs no workflow edit: `frontend-ci.yml` already lists
 *      `backend/jobtracker/classifier/rules.py` in both trigger blocks for the
 *      ATS census next door.
 *
 * The corpus cannot help here — of 18,020 messages, 460 carry a quote boundary
 * and none has own text under the floor — so these cases are the only thing in
 * the repository that touches the branch. Verified by mutation rather than by
 * a green run: with `Math.min(confidence, REFUTED_CONFIDENCE)` deleted, cases
 * 2 and 5 go red and the rest stay green.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { importApp } from "./helpers/appModule.mjs";

const { classifyWithRules, stripQuotedHistory, ownTextSpan, ownTextRefutes } =
  await importApp("lib/demo/rulesLayer.ts");

/** The value the server-side pipeline files at, unrounded. */
const AUTO_FILE_GATE = 0.85;
/** `_REFUTED_CONFIDENCE`, and the number this port exists to produce. */
const REFUTED_CONFIDENCE = 0.8;

/** The offer this thread is about, quoted back by the sender's client. */
const QUOTED_OFFER =
  "\n\nOn Tuesday, Cedarhollow Systems Talent wrote:\n" +
  "> Hi Ayush,\n" +
  "> We are pleased to offer you the position of Backend Engineer at\n" +
  "> Cedarhollow Systems. Your start date will be 1 September and your\n" +
  "> annual salary $145,000. Please sign and return the offer letter.\n";

/** The invitation the near-miss replies to. */
const QUOTED_INVITE =
  "\n\nOn Tuesday, Cedarhollow Systems Recruiting wrote:\n" +
  "> Hi Ayush,\n" +
  "> We would like to invite you to interview for the Backend Engineer\n" +
  "> role. Would you be available on Thursday at 2pm for a 45 minute\n" +
  "> technical interview? Please confirm your availability and we will\n" +
  "> send a calendar invite.\n";

const SUBJECT = "Re: Your offer from Cedarhollow Systems";
const SENDER = "talent@cedarhollow.example";
/** A real relay shape: a proper subdomain of a listed ATS domain. */
const ATS_SENDER = "no-reply@cedarhollow.greenhouse.io";
const WITHDRAWAL = "We must withdraw the offer.";

test("the withdrawal is under the floor, so this measures the right thing", () => {
  const body = WITHDRAWAL + QUOTED_OFFER;
  assert.ok(WITHDRAWAL.length < 40, "the fixture stopped being a short reply");
  assert.equal(
    stripQuotedHistory(body),
    body,
    "the quote was stripped, so the quote is not what scored and every case " +
      "below would be measuring the stripped path instead",
  );
  assert.equal(
    ownTextSpan(body),
    WITHDRAWAL,
    "the span the cap reads is not the sender's own words",
  );
});

test("a rescinded offer is held for review rather than filed", () => {
  const verdict = classifyWithRules(SUBJECT, WITHDRAWAL + QUOTED_OFFER, SENDER);

  assert.equal(
    verdict.category,
    "offer",
    "capping must not flip the category: `other` lands at 0.50, which DROPS " +
      "the mail that would have corrected the board",
  );
  assert.equal(verdict.confidence, REFUTED_CONFIDENCE);
  assert.ok(
    verdict.confidence < AUTO_FILE_GATE,
    `a rescinded offer scored ${verdict.confidence}, at or over the gate`,
  );
});

test("a short acceptance over a quoted invitation still advances the card", () => {
  // THE NEAR-MISS. Under the floor, scores its quote, and is right to.
  const verdict = classifyWithRules(
    "Re: Interview for Backend Engineer",
    "Thursday works for me." + QUOTED_INVITE,
    SENDER,
  );

  assert.equal(verdict.category, "interview");
  assert.ok(
    verdict.confidence >= AUTO_FILE_GATE,
    `a short acceptance over a quoted invitation scored ${verdict.confidence}; ` +
      "a cap that fires on every fallback rather than on a refutation looks " +
      "exactly like this",
  );
});

test("a bare forward of a rejection still reads its quote", () => {
  // The other near-miss, and the one that names the asymmetry: `rejection` is
  // subtracted from RETRACTABLE by hand, because "we have withdrawn your
  // application" is a rejection written in retraction words.
  const verdict = classifyWithRules(
    "FW: your application",
    "fyi\n\nOn Tuesday, Talent wrote:\n> We regret to inform you that we are " +
      "not moving forward with your candidacy.\n",
    "talent@acme.example",
  );

  assert.equal(verdict.category, "rejection");
  assert.deepEqual(
    ownTextRefutes(WITHDRAWAL, "rejection"),
    [],
    "withdrawal vocabulary refuted a rejection, which would send every " +
      "'we have withdrawn your application' back to the queue",
  );
  assert.ok(
    ownTextRefutes("We are pleased to offer you the role.", "rejection").length > 0,
    "the semantic half must run for EVERY category — only the retraction " +
      "family is gated on RETRACTABLE",
  );
});

test("the floor is what decides which path a reply takes, at 39 and at 40", () => {
  // One thing varies: the length of the sender's own words. The quote, the
  // subject and the sender are the same in both rows.
  const under = "We must withdraw the offer. Sorry now!!";
  const over = "We must withdraw the offer. Sorry now!!!";
  assert.equal(under.length, 39);
  assert.equal(over.length, 40);

  const capped = classifyWithRules(SUBJECT, under + QUOTED_OFFER, SENDER);
  assert.equal(capped.category, "offer");
  assert.equal(capped.confidence, REFUTED_CONFIDENCE);

  // One character later the span IS the assertion, the quote is dropped, and
  // 40 characters of withdrawal match no positive pattern at all.
  const stripped = classifyWithRules(SUBJECT, over + QUOTED_OFFER, SENDER);
  assert.equal(stripped.category, "other");
  assert.equal(stripped.confidence, 0.5);
});

test("the ATS bonus is live for this sender — otherwise the case below is vacuous", () => {
  const ACK =
    "Thanks for your application. We have received it.\n\n" +
    "On Tuesday, Talent wrote:\n> placeholder\n";

  const plain = classifyWithRules("Your application", ACK, SENDER);
  const relay = classifyWithRules("Your application", ACK, ATS_SENDER);

  assert.equal(plain.category, relay.category);
  assert.ok(
    relay.confidence > plain.confidence,
    `the +0.05 did not fire for ${ATS_SENDER}: ${plain.confidence} -> ${relay.confidence}`,
  );
  assert.ok(
    relay.confidence >= AUTO_FILE_GATE && plain.confidence < AUTO_FILE_GATE,
    "the control has to cross the gate, or it does not model the arithmetic " +
      "the ordering below is about",
  );
});

test("the cap is applied AFTER the ATS bonus, not before", () => {
  // Capping first leaves 0.80, the bonus adds 0.05, and the withdrawal files
  // itself at the gate from any domain a stranger can register on a listed
  // relay. This is the ordering, not the cap.
  const verdict = classifyWithRules(SUBJECT, WITHDRAWAL + QUOTED_OFFER, ATS_SENDER);

  assert.equal(verdict.category, "offer");
  assert.equal(
    verdict.confidence,
    REFUTED_CONFIDENCE,
    "the ATS bonus pushed a capped verdict back over the gate",
  );
});

test("the retraction family is byte-identical to _RETRACTION in rules.py", () => {
  const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
  const path = join(repoRoot, "backend", "jobtracker", "classifier", "rules.py");

  let source;
  try {
    source = readFileSync(path, "utf8");
  } catch (err) {
    assert.fail(
      `rules.py was not at ${path} (${err.code ?? err.message}). If the engine moved, ` +
        "point this case at it in the same commit — a lockstep check that cannot " +
        "read its oracle is a check that measures nothing.",
    );
  }

  // `_RETRACTION = re.compile(` … `re.IGNORECASE,` — the raw string literals in
  // between, concatenated the way Python concatenates them.
  const block = source.match(/_RETRACTION = re\.compile\(\n([\s\S]*?)\n\s*re\.IGNORECASE,/);
  assert.ok(block, "could not find _RETRACTION in rules.py — the extraction failed, not the port");
  const pattern = [...block[1].matchAll(/r"([^"]*)"/g)].map((m) => m[1]).join("");
  assert.ok(pattern.length > 100, `extracted ${pattern.length} characters of pattern, which is not it`);

  assert.ok(
    ownTextRefutes(WITHDRAWAL, "offer").includes(pattern),
    "the ported retraction family is no longer the same bytes as rules.py's. " +
      "Python `re` and JavaScript `RegExp` are not the same language — check " +
      "for lookbehind or inline flags before copying the new source across.",
  );
});
