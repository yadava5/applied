/**
 * THE BROWSER ENGINE STILL FILES A RESCINDED OFFER AS AN OFFER (#417).
 *
 * This file pins a divergence, not a requirement. `backend/jobtracker/
 * classifier/rules.py` was fixed: a reply whose own words are under
 * `_MIN_ASSERTED_CHARS` keeps its quote for scoring, but the span is read
 * anyway and the verdict is capped below the auto-file gate when those words
 * refute the category the quote won with. "We must withdraw the offer." is 27
 * characters, and the server now holds it for review.
 *
 * `lib/demo/rulesLayer.ts` was NOT changed in that commit. It mirrors
 * `_QUOTE_BOUNDARY` and `MIN_ASSERTED_CHARS = 40` and has no cap, so the same
 * message comes back `offer` at 0.95 and the demo asserts an offer nobody
 * holds — the exact defect, in the second of the two engines #417 measured.
 *
 * WHY PIN IT RATHER THAN LEAVE IT UNSAID. Nothing else in this repository can
 * see it. The backend change touched no pattern, so `scripts/readme_facts.py`
 * (which compares pattern counts), the vendored Space copy (Python) and
 * `lib/demo/rules.json` (patterns, not behaviour) are all still green. An
 * undisclosed cross-engine divergence is found six months later as a bug
 * report; a pinned one is found by whoever ports the fix.
 *
 * THIS TEST IS MEANT TO GO RED. If it fails because the verdict is no longer
 * `offer` at 0.95, the port has happened: DELETE THIS FILE and the divergence
 * note in `rulesLayer.ts`. Do not "fix" the port to keep this green — that is
 * the inverted gate this repository keeps re-learning about, a test defending
 * the bug it documents.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { importApp } from "./helpers/appModule.mjs";

const { classifyWithRules, stripQuotedHistory } = await importApp("lib/demo/rulesLayer.ts");

/** The offer this thread is about, quoted back by the sender's client. */
const QUOTED_OFFER =
  "\n\nOn Tuesday, Cedarhollow Systems Talent wrote:\n" +
  "> Hi Ayush,\n" +
  "> We are pleased to offer you the position of Backend Engineer at\n" +
  "> Cedarhollow Systems. Your start date will be 1 September and your\n" +
  "> annual salary $145,000. Please sign and return the offer letter.\n";

const SUBJECT = "Re: Your offer from Cedarhollow Systems";
const SENDER = "talent@cedarhollow.example";
const WITHDRAWAL = "We must withdraw the offer.";

test("the withdrawal really is under the floor, so this measures the right thing", () => {
  const body = WITHDRAWAL + QUOTED_OFFER;
  assert.ok(WITHDRAWAL.length < 40, "the fixture stopped being a short reply");
  assert.equal(
    stripQuotedHistory(body),
    body,
    "the quote was stripped, so the quote is not what scored and this file " +
      "would be pinning nothing",
  );
});

test("PINNED DIVERGENCE: the demo still auto-files a rescinded offer", () => {
  const verdict = classifyWithRules(SUBJECT, WITHDRAWAL + QUOTED_OFFER, SENDER);
  assert.equal(
    verdict.category,
    "offer",
    "the browser engine changed its verdict on a rescission — if the #417 " +
      "cap was ported, delete this file and the note in rulesLayer.ts",
  );
  assert.equal(
    verdict.confidence,
    0.95,
    "the browser engine changed its confidence on a rescission — if the " +
      "#417 cap was ported, delete this file and the note in rulesLayer.ts",
  );
});

test("the directional control the port will have to carry across too", () => {
  // "Thursday works for me" over a quoted INTERVIEW invitation is also under
  // the floor and is RIGHT to score its quote. Whoever ports the cap has to
  // keep this one filing, which is what makes the narrow rule necessary.
  const invite =
    "\n\nOn Tuesday, Cedarhollow Systems Recruiting wrote:\n" +
    "> Hi Ayush,\n" +
    "> We would like to invite you to interview for the Backend Engineer\n" +
    "> role. Would you be available on Thursday at 2pm for a 45 minute\n" +
    "> technical interview? Please confirm your availability and we will\n" +
    "> send a calendar invite.\n";
  const verdict = classifyWithRules(
    "Re: Interview for Backend Engineer",
    "Thursday works for me." + invite,
    SENDER,
  );
  assert.equal(verdict.category, "interview");
  assert.ok(
    verdict.confidence >= 0.85,
    `a short acceptance over a quoted invitation scored ${verdict.confidence}; ` +
      "it should advance the card",
  );
});
