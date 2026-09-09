/* What a body means before a pattern is allowed to read it.
 *
 * THE THIRD COPY, AND IT IS DELIBERATE — #955.
 *
 * There are three implementations of one rule set: `backend/jobtracker/
 * classifier/rules.py` (the engine that ships), `apps/web/lib/demo/
 * rulesLayer.ts`, and `app.js` in this directory. All three load a
 * byte-identical `rules.json`, and until this file existed only two of them
 * masked the body before matching. A byte-identical pattern file does not make
 * two engines the same classifier when one consumes a masked body and the
 * other a raw one: the `|if` arm of `be in touch (soon|shortly|if)` is dead in
 * Python and TypeScript because the mask removes the clause it needs, and was
 * LIVE here. One pattern file, two dead arms and one live one.
 *
 * WHY A COPY RATHER THAN A SHARED MODULE. This directory is a static site: the
 * page is opened over `file:` or served flat, so every import it makes has to
 * resolve inside it. A module under `apps/web` cannot be reached from here at
 * runtime, and one placed outside both cannot be reached from a Next build
 * without crossing a workspace boundary. The same argument already settled the
 * same question for `rules.json`, which is duplicated for exactly this reason.
 *
 * WHAT MAKES THE COPY SAFE IS A GATE, NOT A COMMENT. `scripts/
 * cross_engine_differential.py` now runs THIS engine as a third arm against
 * the Python reference over the evaluation corpora, so a divergence between
 * the copies is a red run rather than a discovery. The precedent is
 * `backend/tests/test_the_veto_copy_cannot_drift.py`, which keeps a hand-kept
 * duplicate honest by checking it instead of asking people to remember.
 *
 * The decision to keep this as a copy rather than share it is DEC-011.
 * Every function below mirrors the Python original named in its comment, by
 * way of the TypeScript port that already mirrors it.
 */

/** A word that makes what follows it hypothetical. Mirrors `_CONDITIONAL`. */
const CONDITIONAL_RE = /\b(?:if|should you|in the event(?:\s+that)?|unless|in case)\b/i;

/* Sentence boundary in two deterministic steps rather than one regex. The
 * single pattern `/(?<=[.!?])\s+(?=["“(A-Z])/` is a polynomial ReDoS: the
 * greedy `\s+` is followed by a lookahead that can fail, so a run of N spaces
 * is retried at every offset, and the body arrives from whoever emailed the
 * user. Mirrors `_SENTENCE_SPLIT` / `_sentences`. */
const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+/;
const STARTS_SENTENCE_RE = /^["“(A-Z]/;

/* Where this message stops speaking and its history starts. `^`-anchored under
 * the `m` flag, which is why `reflowParagraphs` must run AFTER this and never
 * before. Mirrors `_QUOTE_BOUNDARY`. */
const QUOTE_BOUNDARY_RE = new RegExp(
  '^(?:' +
    '[ \\t]*>' +
    '|[ \\t]*-{2,}\\s*(?:original\\s+message|forwarded\\s+message)\\s*-{2,}' +
    '|[ \\t]*begin\\s+forwarded\\s+message\\s*:' +
    '|[ \\t]*on\\b[^\\n]{0,200}?\\bwrote\\s*:' +
    '|[ \\t]*from\\s*:[^\\n]{0,200}\\n[ \\t]*sent\\s*:' +
  ')',
  'im',
);

/* Below this, a reply has written nothing a classifier can read, so scoring
 * what it wrote means scoring nothing. Mirrors `_MIN_ASSERTED_CHARS`. */
export const MIN_ASSERTED_CHARS = 40;

const PARAGRAPH_BREAK_RE = /\n{2,}/;
const LINE_INTERIOR_SPACE_RE = /[^\S\n]+/g;

/** Split into sentences without a backtracking regex. Mirrors `_sentences`. */
function sentences(body) {
  const out = [];
  for (const part of body.split(SENTENCE_SPLIT_RE)) {
    if (out.length > 0 && !STARTS_SENTENCE_RE.test(part)) {
      out[out.length - 1] = `${out[out.length - 1]} ${part}`;
    } else {
      out.push(part);
    }
  }
  return out;
}

/**
 * Only the part of `body` this message wrote itself. Mirrors
 * `strip_quoted_history` (#441): a follow-up that quotes its own confirmation
 * otherwise scores the QUOTE, and a withdrawal that quotes the offer it is
 * withdrawing scores the offer.
 *
 * Unchanged when there is no quote, and unchanged when what remains is too
 * thin to be an assertion — "fyi" over a forwarded rejection must not be
 * reduced to three characters.
 */
export function stripQuotedHistory(body) {
  if (!body) return body;
  const marker = QUOTE_BOUNDARY_RE.exec(body);
  if (marker === null) return body;
  const own = body.slice(0, marker.index).trim();
  return own.length < MIN_ASSERTED_CHARS ? body : own;
}

/**
 * The part of a body the sender is ASSERTING. Mirrors `asserted_text`.
 *
 * Quotes first, then conditionals, and the order matters: a conditional inside
 * quoted history is not this message's hypothesis. The mask runs from the
 * conditional marker to the END of its sentence and never over the whole
 * sentence — "You were not selected, and if you would like feedback please
 * ask" is a real rejection whose verdict sits before the marker.
 */
export function assertedText(body) {
  if (!body) return body;
  const own = stripQuotedHistory(body);
  return sentences(own)
    .map((sentence) => {
      const marker = CONDITIONAL_RE.exec(sentence);
      return marker ? sentence.slice(0, marker.index) : sentence;
    })
    .join(' ');
}

/**
 * Join the lines INSIDE a paragraph; keep the blank line between them.
 * Mirrors `reflow_paragraphs`.
 *
 * Real `text/plain` from an ATS is hard-wrapped at 72-78 columns, and `.` does
 * not match a newline, so every bounded gap in `rules.json` — roughly sixty of
 * them — stops bridging a wrap point the moment one exists. RUNS LAST, after
 * the mask, because the quote boundary above is line-anchored and reflowing
 * first would delete the anchors it needs.
 */
export function reflowParagraphs(text) {
  if (!text) return text;
  return text
    .split(PARAGRAPH_BREAK_RE)
    .map((p) => p.replace(/\n/g, ' ').replace(LINE_INTERIOR_SPACE_RE, ' ').trim())
    .filter((p) => p !== '')
    .join('\n\n');
}

/** Exactly what `RulesClassifier.classify` scores: the one line it applies. */
export function scoredBody(body) {
  return reflowParagraphs(assertedText(body ?? ''));
}

/* --------------------------------------------------------------------------
 * The rest of what `rules.json` does not carry.
 *
 * Everything below mirrors `RulesClassifier.classify`'s own control flow, by
 * way of the TypeScript port that already mirrors it. Three mechanisms, each
 * of which this engine was missing entirely and each of which was measured
 * diverging from the Python reference on the cross-engine corpora before it
 * was ported:
 *
 *   #441  a REPLY's subject is about the thread, not about this message, so it
 *         scores 2/1 instead of 6/2;
 *   #451  a genre filter ("this is not job mail") may not outrank a strong
 *         match in the BODY, while a semantic negative still may;
 *   #417  a reply too short to be scored keeps its quote, and the quote is
 *         what wins -- so when the sender's own words REFUTE that winner, the
 *         confidence is capped.
 * -------------------------------------------------------------------------- */

/** A subject that belongs to the CONVERSATION rather than to this message.
 *  Bounded on every quantifier: the obvious form is a polynomial ReDoS and
 *  subjects come from whoever emailed the user. Mirrors `_REPLY_SUBJECT`. */
const REPLY_SUBJECT_RE = /^[ \t]{0,8}(?:re|fw|fwd)[ \t]{0,8}(?:\[\d{1,4}\][ \t]{0,8})?:/i;

/** Scoring weights for a subject match: (strong, weak). A reply's headline was
 *  copied from a message someone else wrote weeks ago, so it is demoted below
 *  body weight rather than discarded — a bare "Re: Your application" still
 *  carries the only signal it has. */
export function subjectWeights(subject) {
  return REPLY_SUBJECT_RE.test(subject ?? '') ? [2, 1] : [6, 2];
}

/** The negatives that say "this is not job mail" rather than "this job mail
 *  says otherwise". Kept in lockstep with `_NOISE_NEGATIVES` in the Python
 *  original and `NOISE_NEGATIVES` in the TypeScript one, BY SOURCE STRING, so
 *  the split is the same three ways. */
export const NOISE_NEGATIVES = new Set([
  '\\b(unsubscribe|manage preferences|newsletter|digest)\\b',
  'subscribe|unsubscribe',
  'newsletter',
  '\\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\\b',
  '\\b(discount|promo(?:tion)?|coupon|sale|limited time offer)\\b',
  'discount|promo|sale|off\\b',
  '\\b(order|purchase|shipment|tracking number)\\b',
  '\\b(shop|buy|cart|checkout|order|purchase|shipment|tracking number)\\b',
  '\\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\\b',
  'open.{0,20}account',
  'premium.{0,20}(free|gift)',
  'your course',
]);

/** Categories whose mail claims nothing about an application existing.
 *  Mirrors `_SAYS_NOTHING_ABOUT_AN_APPLICATION`. */
const SAYS_NOTHING_ABOUT_AN_APPLICATION = new Set(['follow_up', 'needs_review', 'other']);

/** A sender taking back the thing their quote is about. The one vocabulary
 *  here `rules.json` does not carry: it never scores and never would. Source
 *  identical to `_RETRACTION` in the Python original. */
const RETRACTION_RE =
  /\b(?:withdraw|withdrawn|withdrawing|withdrawal|rescind(?:ed|ing)?|revok(?:e|ed|ing)|retract(?:ed|ing)?)\b|\bno longer\b[^.\n]{0,30}\b(?:available|able|open|hiring|proceeding|moving)\b|\b(?:role|position|offer|opportunity|req|requisition|opening)\b[^.\n]{0,30}\b(?:closed|cancell?ed|frozen|filled|eliminated|on hold)\b|\b(?:hiring freeze|headcount freeze|put on hold)\b/i;

/** Where a refuted winner's confidence is capped. Mirrors
 *  `_REFUTED_CONFIDENCE`. */
export const REFUTED_CONFIDENCE = 0.8;

/**
 * The words this message wrote ABOVE its quoted history — floor or no floor.
 *
 * `null` when there is no quote at all, which is a different answer from `""`
 * (a reply that quoted something and wrote nothing above it), and both are
 * different from a span too short to be scored. Mirrors `own_text_span`.
 */
export function ownTextSpan(body) {
  if (!body) return null;
  const marker = QUOTE_BOUNDARY_RE.exec(body);
  if (marker === null) return null;
  return body.slice(0, marker.index).trim();
}

/** Did the QUOTE do the talking? A reply under the floor keeps its history, so
 *  what won is not what the sender wrote. Mirrors `quote_spoke_for_it`. */
export function quoteSpokeForIt(ownText) {
  return ownText !== null && ownText.length > 0 && ownText.length < MIN_ASSERTED_CHARS;
}

/**
 * The semantic half of each compiled category's negatives — DERIVED from the
 * very RegExps the scoring walk uses, through the same `NOISE_NEGATIVES`
 * split, so no second copy of the vocabulary can rot. Mirrors
 * `_SEMANTIC_REFUTATIONS`, which is built exactly this way from `PATTERNS`.
 */
export function semanticRefutations(compiledCategories) {
  const out = {};
  for (const [cat, g] of Object.entries(compiledCategories)) {
    out[cat] = g.negative.filter((re) => !NOISE_NEGATIVES.has(re.source));
  }
  return out;
}

/** Categories a retraction can refute: everything claiming an application is
 *  ALIVE. `rejection` is subtracted by hand and is the only judgement here —
 *  "we have withdrawn your application from consideration" is a rejection
 *  written in retraction words. Mirrors `_RETRACTABLE`. */
export function retractable(compiledCategories) {
  return new Set(
    Object.keys(compiledCategories).filter(
      (cat) => !SAYS_NOTHING_ABOUT_AN_APPLICATION.has(cat) && cat !== 'rejection',
    ),
  );
}

/**
 * Which of `own`'s words argue AGAINST `category`.
 *
 * THE TWO CLAUSES ARE INDEPENDENT, exactly as in Python: every category is
 * checked against its own semantic negatives, and only the retraction family
 * is gated on `retractable`. A `rejection` winner can still be refuted by its
 * own negatives — it just cannot be refuted by withdrawal vocabulary, because
 * a withdrawal from consideration IS a rejection.
 *
 * Mirrors `own_text_refutes`.
 */
export function ownTextRefutes(own, category, refutations, retractableCats) {
  if (!own) return [];
  const hits = (refutations[category] ?? []).filter((re) => re.test(own)).map((re) => re.source);
  if (retractableCats.has(category) && RETRACTION_RE.test(own)) hits.push(RETRACTION_RE.source);
  return hits;
}
