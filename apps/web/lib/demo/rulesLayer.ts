/**
 * Layer 1 of the classifier — the regex rules engine — ported to the browser.
 *
 * This is a faithful, byte-for-byte port of the scoring in the shipped
 * classifier: `backend/jobtracker/classifier/rules.py` and its in-browser
 * twin `ml/browser/site/app.js`. That twin used to be published as a Hugging
 * Face Space; the Space was made private on 2026-08-15 because it served the
 * weights of a checkpoint fitted partly on a real mailbox (iCloud IMAP, not
 * Gmail). This port is
 * unaffected — it carries no weights and never did.
 * Same 218 patterns, same weights (strong +3 / +6-in-subject, weak +1 / +2,
 * negative −5), same veto cap, same margin→confidence tiers, same ATS-domain
 * boost, same #417 cap on a verdict its own sender contradicted.
 *
 * It is pure JavaScript — no model, no network, no WASM — so it runs live in
 * the visitor's tab under the app's strict CSP. The `/demo/inbox` sample view
 * uses it to recompute layer 1 on the spot, proving the pipeline is real code
 * and not a canned animation. Layers 2–3 (e5 embeddings + the SetFit head)
 * need the 23 MB ONNX model, so their outputs are precomputed offline by the
 * exact same pipeline and stored in `sampleInbox.ts`.
 */
import rulesRaw from "./rules.json";

export interface RulesVerdict {
  /** Winning category, or "other" when nothing scored above zero. */
  category: string;
  /** Confidence in [0,1], from the same tier table as the Python engine. */
  confidence: number;
  /** Raw per-category integer scores, for display / debugging. */
  scores: Record<string, number>;
}

interface CompiledCategory {
  strong: RegExp[];
  weak: RegExp[];
  negative: RegExp[];
  veto: RegExp[];
}

interface RawCategory {
  strong: string[];
  weak: string[];
  negative: string[];
  /** `assessment` and `follow_up` declare vetoes; the key is absent elsewhere. */
  veto?: string[];
}

const RAW_CATS = rulesRaw.categories as Record<string, RawCategory>;

const CATS: Record<string, CompiledCategory> = Object.fromEntries(
  Object.entries(RAW_CATS).map(([cat, g]) => [
    cat,
    {
      strong: g.strong.map((p) => new RegExp(p, "i")),
      weak: g.weak.map((p) => new RegExp(p, "i")),
      negative: g.negative.map((p) => new RegExp(p, "i")),
      veto: (g.veto ?? []).map((p) => new RegExp(p, "i")),
    },
  ]),
);

const ATS_DOMAINS: string[] = rulesRaw.ats_domains;

const ATS_BOOSTED = new Set(["applied", "rejection", "interview", "offer"]);

/** The categories whose mail REPORTS on an application that already exists, as
 *  opposed to `applied`, whose mail ASSERTS one into being.
 *
 *  The port of `rules.REPORTS_ON_AN_APPLICATION` (#451), and it is a partition
 *  rather than a ranking: a report ENTAILS the assertion (an offer for a job
 *  presupposes you applied for it) and the entailment does not run the other
 *  way, so at equal evidence the report is the reading that accounts for all
 *  of it. Members within the set are unordered — this says nothing about a
 *  rejection against an interview, because nothing true would.
 *
 *  `pending_application` is in it on the same reasoning the pipeline already
 *  uses: "please verify your email before we can review your application" is
 *  an outstanding STEP in an application that exists, so it reports. */
const REPORTS_ON_AN_APPLICATION = new Set([
  "rejection",
  "interview",
  "assessment",
  "offer",
  "pending_application",
]);

/** Which tier of a category's rule set a pattern belongs to. */
export type RuleTier = "strong" | "weak" | "negative" | "veto";

/**
 * One pattern's hit, exactly as the scoring saw it: the tier it scored under,
 * the field it scored IN (strong/weak try the subject first and only fall
 * back to the body — the trace records the field that actually scored), the
 * points it contributed (0 for a veto, which caps rather than adds), and the
 * first match's offsets in that field from the same compiled RegExp. The
 * engine tests each pattern once per field, so one hit per pattern is not a
 * simplification — it is the whole of what the score saw.
 */
export interface RuleHit {
  category: string;
  tier: RuleTier;
  field: "subject" | "body";
  points: number;
  start: number;
  end: number;
  /** The pattern's source, verbatim from rules.json — a machine value. */
  source: string;
}

/** A verdict plus every pattern hit that produced it. */
export interface RulesTrace {
  verdict: RulesVerdict;
  hits: RuleHit[];
}

/** Points per tier and field — the numbers in `score`'s branches, named once
 *  so the trace cannot quote a different weight than the walk applied.
 *
 *  `replySubject` is the same match in a subject the mail client COPIED from
 *  the message being replied to (#441). Below body weight, not equal to it: at
 *  equal weight a copied headline still ties with what this sender actually
 *  wrote. */
const POINTS = {
  strong: { subject: 6, replySubject: 2, body: 3 },
  weak: { subject: 2, replySubject: 1, body: 1 },
} as const;

/**
 * Genre filters: the negatives that say "this is not job mail at all" (a
 * receipt, a promotion, a security alert, a mailing list) as opposed to the
 * ones that say "this IS job mail and it is not THIS category". Only the first
 * kind yields to strong body evidence.
 *
 * Kept in lockstep with `_NOISE_NEGATIVES` in
 * `backend/jobtracker/classifier/rules.py`, membership by exact source string.
 * A pattern edited on one side and not the other silently returns to full
 * weight rather than silently keeping the exemption, which is the safer
 * direction to fail.
 */
const NOISE_NEGATIVES: ReadonlySet<string> = new Set([
  "\\b(unsubscribe|manage preferences|newsletter|digest)\\b",
  "subscribe|unsubscribe",
  "newsletter",
  "\\b(discount|promo(?:tion)?|coupon|sale|limited time offer|flash sale)\\b",
  "\\b(discount|promo(?:tion)?|coupon|sale|limited time offer)\\b",
  "discount|promo|sale|off\\b",
  "\\b(order|purchase|shipment|tracking number)\\b",
  "\\b(shop|buy|cart|checkout|order|purchase|shipment|tracking number)\\b",
  "\\b(security alert|verification code|otp|one[- ]time (passcode|password|code)|sign[- ]in|login)\\b",
  "open.{0,20}account",
  "premium.{0,20}(free|gift)",
  "your course",
]);

const CONDITIONAL_RE = /\b(?:if|should you|in the event(?:\s+that)?|unless|in case)\b/i;

/**
 * Sentence boundary, in two deterministic steps rather than one regex.
 *
 * The obvious single pattern is `/(?<=[.!?])\s+(?=["\u201c(A-Z])/`. It is a
 * polynomial ReDoS: the greedy `\s+` is followed by a lookahead that can fail,
 * so a run of N spaces is retried at every offset. The body arrives from
 * whoever emailed the user, and on this surface it is not even length-capped
 * the way the server's is.
 *
 * Splitting on `\s+` with nothing after it cannot backtrack, and the
 * capital-letter test then happens in ordinary code. Same boundaries, and it
 * matches `_SENTENCE_SPLIT` / `_sentences` in the Python original line for
 * line.
 */
const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+/;
const STARTS_SENTENCE_RE = /^["\u201c(A-Z]/;

function sentences(body: string): string[] {
  const out: string[] = [];
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
 * Where a reply stops speaking and starts repeating.
 *
 * Four client shapes, all anchored to the start of a line, which is what keeps
 * them out of prose. "We wrote to you on Tuesday" is not an attribution, and a
 * rejection must not lose its verdict to a loose match.
 *
 *   1. `>` — a quoted line, for clients that write no attribution at all.
 *   2. `----- Original Message -----` / `----- Forwarded message -----`.
 *   3. `Begin forwarded message:` — Apple Mail.
 *   4. `On <anything> wrote:` — the attribution every major client writes.
 *
 * The Outlook `From: … \n Sent: …` header block is the one shape the Python
 * side matches and this does not: it needs a multi-line alternative, and the
 * cases it catches are already caught by 2 in practice. Noted rather than
 * silently dropped — see #427 on parity.
 *
 * Written as one alternation with `m` rather than Python's VERBOSE form,
 * because JavaScript has no verbose flag. The bounded `{0,200}` on the
 * attribution is deliberate and matches the original: an unbounded `.*?`
 * before `wrote:` scans the whole body on every non-matching line.
 *
 * Mirrors `_QUOTE_BOUNDARY` in `backend/jobtracker/classifier/rules.py`.
 */
const QUOTE_BOUNDARY_RE =
  /^(?:[ \t]*>|[ \t]*-{2,}\s*(?:original\s+message|forwarded\s+message)\s*-{2,}|[ \t]*begin\s+forwarded\s+message\s*:|[ \t]*on\b[^\n]{0,200}?\bwrote\s*:)/im;

/**
 * Below this many characters, a reply's own words are treated as no words at
 * all and the quote is scored after all.
 *
 * Not a tuning knob. Someone forwarding a rejection to themselves with "fyi"
 * above it has written nothing a classifier can read, and scoring the eleven
 * characters they did write means scoring nothing — which abstains on a
 * message whose verdict is sitting right there in the quote. So a reply that
 * adds no substance falls back to the whole body, and only a reply that SAYS
 * something gets to speak over its history.
 *
 * Mirrors `_MIN_ASSERTED_CHARS` in the Python original.
 */
const MIN_ASSERTED_CHARS = 40;

/**
 * Only the part of `body` this message wrote itself.
 *
 * ISSUE #441. The scoring walk had no notion of whose words it was reading, so
 * a follow-up that quoted its own confirmation scored the QUOTE: every such
 * message read as `applied`, and an interview invitation never advanced the
 * card it belonged to. It is also the mechanism behind #417 — a withdrawal
 * that quotes the offer it is withdrawing scores the offer.
 *
 * The quote is often the only place the ROLE appears, so this must never sit
 * in front of identity extraction: only scoring loses the history.
 *
 * THE FLOOR IS NOT THE ONLY READER OF THAT SPAN, and that is the whole of
 * #417's short-reply half: `ownTextSpan` below returns the span whether or not
 * it clears the floor, because "which words get SCORED" and "which words did
 * the sender WRITE" are different questions.
 *
 * Mirrors `strip_quoted_history` in the Python original.
 */
export function stripQuotedHistory(body: string): string {
  if (!body) return body;
  const marker = QUOTE_BOUNDARY_RE.exec(body);
  if (marker === null) return body;
  const own = body.slice(0, marker.index).trim();
  return own.length < MIN_ASSERTED_CHARS ? body : own;
}

/**
 * The words this message wrote ABOVE its quoted history — floor or no floor.
 *
 * `null` when there is no quote at all, which is a different answer from `""`
 * (a reply that quoted something and wrote nothing above it), and both are
 * different from a span too short to be scored.
 *
 * ISSUE #417. `stripQuotedHistory` refuses to strip below
 * `MIN_ASSERTED_CHARS`, so the whole body — quote included — goes to the
 * scorer. That is right for "fyi" over a forwarded rejection and wrong for "We
 * must withdraw the offer.", which is 27 characters. The floor cannot tell
 * those apart because it counts characters, and nothing else was looking at
 * the span at all. This is what looks.
 *
 * Deliberately NOT a lower floor: the floor is doing its job, which is to stop
 * a substanceless reply from being reduced to nothing. Lowering it moves every
 * short reply there is; this moves only the ones whose own words contradict
 * the verdict their quote produced.
 *
 * Mirrors `own_text_span` in the Python original.
 */
export function ownTextSpan(body: string): string | null {
  if (!body) return null;
  const marker = QUOTE_BOUNDARY_RE.exec(body);
  if (marker === null) return null;
  return body.slice(0, marker.index).trim();
}

/**
 * A subject that belongs to the CONVERSATION rather than to this message.
 *
 * Bounded on every quantifier, and the optional counter carries its own
 * trailing space. The obvious form is `/^\s*(?:re|fw|fwd)\s*(?:\[\d+\])?\s*:/`
 * and it is a polynomial ReDoS for the same reason `SENTENCE_SPLIT_RE` above
 * is written the way it is: with the counter absent the two `\s*` sit
 * adjacent, so a run of N spaces after "Re" is re-partitioned at every offset.
 * Subjects come from whoever emailed the user, and on this surface they are
 * not length-capped the way the server's are.
 *
 * Mirrors `_REPLY_SUBJECT` in the Python original.
 */
const REPLY_SUBJECT_RE = /^[ \t]{0,8}(?:re|fw|fwd)[ \t]{0,8}(?:\[\d{1,4}\][ \t]{0,8})?:/i;

/**
 * The part of a body the sender is ASSERTING.
 *
 * A phrase can appear in a message without being claimed. The case this exists
 * for is an application confirmation that explains, conditionally, what a
 * rejection would look like:
 *
 *   "... If you see the job moved to an inactive state, that means the position
 *    is either no longer open, you withdrew from consideration, or you were not
 *    selected for the role."
 *
 * Nothing has been decided, but two strong rejection patterns fire on it. In
 * production that scored `rejection` at 0.60 and the message was discarded
 * without a trace; it cost the owner four applications on 2026-08-21.
 *
 * The mask runs from the conditional marker to the END of its sentence, never
 * over the whole sentence: "You were not selected for the role, and if you
 * would like feedback please ask" is a real rejection whose verdict sits before
 * the marker.
 *
 * Mirrors `asserted_text` in `backend/jobtracker/classifier/rules.py`.
 */
export function assertedText(body: string): string {
  if (!body) return body;
  // Quotes first, then conditionals, and the order matters: a conditional
  // inside quoted history is not this message's hypothesis and should never
  // have been walked sentence by sentence in the first place.
  const own = stripQuotedHistory(body);
  return sentences(own)
    .map((sentence) => {
      const marker = CONDITIONAL_RE.exec(sentence);
      return marker ? sentence.slice(0, marker.index) : sentence;
    })
    .join(" ");
}

/**
 * When a reply's own words contradict the verdict its quote produced — #417.
 *
 * A reply under `MIN_ASSERTED_CHARS` keeps its quote, so the quote is what
 * gets scored. For "fyi" over a forwarded offer that is correct and everything
 * below stays out of the way. For "We must withdraw the offer." it is the
 * defect: 27 characters of the sender's own words are discarded, the quoted
 * "we are pleased to offer you the position" wins at 0.95, and the demo
 * asserts an offer the person does not hold.
 *
 * THE FIX MAY NOT BE "DISTRUST THE FALLBACK". "Thursday works for me." over a
 * quoted interview invitation is also under the floor, also scores its quote,
 * and is RIGHT to: the card should advance. Capping every fallback sends that
 * correct auto-file to the review queue. So the span is read, and the verdict
 * is capped only when the span REFUTES the category the quote won with.
 */

/** The categories whose mail says nothing about an application of yours at
 *  all. Mirrors `_SAYS_NOTHING_ABOUT_AN_APPLICATION`; `needs_review` and
 *  `other` are named even though `rules.json` carries no patterns for either,
 *  so the subtraction below reads the same on both sides. */
const SAYS_NOTHING_ABOUT_AN_APPLICATION = new Set(["follow_up", "needs_review", "other"]);

/** The categories a retraction can refute: everything that claims an
 *  application is ALIVE.
 *
 *  DERIVED rather than listed, so it cannot drift from the rules the walk
 *  reads: Python subtracts from `EmailCategory`, this subtracts from
 *  `rules.json`'s categories, and the two land on the same five members
 *  (`applied`, `pending_application`, `interview`, `offer`, `assessment`).
 *
 *  `rejection` is subtracted by hand and is the only judgement in this
 *  constant: "we have withdrawn your application from consideration" is a
 *  rejection written in retraction words, and the classifier is already too shy
 *  about asserting a negative outcome to have that one pushed back into the
 *  queue. */
const RETRACTABLE: ReadonlySet<string> = new Set(
  Object.keys(CATS).filter(
    (cat) => !SAYS_NOTHING_ABOUT_AN_APPLICATION.has(cat) && cat !== "rejection",
  ),
);

/**
 * A sender taking back the thing their quote is about.
 *
 * The one vocabulary here that `rules.json` does not already carry, and it is
 * deliberately the smallest thing that can be true: it never scores and never
 * names a verdict — there is no `rescinded` category — so all it can do is stop
 * a verdict from being asserted.
 *
 * SCOPED TO THE OPPORTUNITY AND NOT TO A DIARY. "no longer" and "closed" are
 * required to land near the role, the offer or the opening, because "Thursday
 * no longer works for me" above a quoted invitation is a rescheduling note and
 * the interview it belongs to still exists.
 *
 * Bounded on every quantifier and applied only to a span shorter than
 * `MIN_ASSERTED_CHARS`, so the ReDoS reasoning that shaped `REPLY_SUBJECT_RE`
 * has nothing to bite on: the alternatives are disjoint and the two gaps are
 * capped at 30 characters of a class that excludes the sentence delimiter.
 *
 * SOURCE-IDENTICAL to `_RETRACTION` in the Python original — it uses no
 * lookbehind, no inline flags and nothing else `RegExp` lacks, so the pattern
 * is the same bytes on both sides and `tests/unit/rescission-cap-417.test.mjs`
 * asserts that against `rules.py` itself rather than against a copy.
 *
 * ONE SEMANTIC DIFFERENCE SURVIVES THAT EQUALITY and is named rather than
 * approximated, the way the Outlook `From:`/`Sent:` gap above is named:
 * Python's `\b` is Unicode-aware on `str` patterns and JavaScript's is
 * ASCII-only, so a word like `withdrawé` has a boundary here and none there —
 * this engine caps a message Python would not. The `u` flag does not close it
 * (`\w` stays ASCII under it); only rewriting the family in `\p{…}` classes
 * would, and that is a different pattern than the one this mirrors.
 */
const RETRACTION_RE =
  /\b(?:withdraw|withdrawn|withdrawing|withdrawal|rescind(?:ed|ing)?|revok(?:e|ed|ing)|retract(?:ed|ing)?)\b|\bno longer\b[^.\n]{0,30}\b(?:available|able|open|hiring|proceeding|moving)\b|\b(?:role|position|offer|opportunity|req|requisition|opening)\b[^.\n]{0,30}\b(?:closed|cancell?ed|frozen|filled|eliminated|on hold)\b|\b(?:hiring freeze|headcount freeze|put on hold)\b/i;

/** The semantic half of each category's negatives.
 *
 *  DERIVED from the very RegExps the scoring walk uses, through the same
 *  `NOISE_NEGATIVES` split, so no second copy of the vocabulary can rot —
 *  `_SEMANTIC_REFUTATIONS` is built exactly this way from `PATTERNS`. The split
 *  is the one `NOISE_NEGATIVES` already names: a genre filter ("this is not job
 *  mail") says nothing about which category is right and must not cap anything,
 *  while a semantic refutation ("regret to inform" against `offer`) is the
 *  sender contradicting the verdict in so many words. */
const SEMANTIC_REFUTATIONS: Record<string, RegExp[]> = Object.fromEntries(
  Object.entries(CATS).map(([cat, g]) => [
    cat,
    g.negative.filter((re) => !NOISE_NEGATIVES.has(re.source)),
  ]),
);

/** What a verdict is worth once the sender's own words have contradicted it.
 *
 *  BETWEEN the review floor (0.70) and the auto-file gate (0.85), and both
 *  bounds are load-bearing. At or over the gate this is the bug. Under the
 *  floor the message is DROPPED rather than queued, which is why the
 *  alternative shape — letting the refutation flip the category to `other` — is
 *  worse: `other` lands at 0.50, so the mail that corrects the board would be
 *  destroyed instead of shown to the reader. Capping asks a question; flipping
 *  deletes the evidence.
 *
 *  Mirrors `_REFUTED_CONFIDENCE` in the Python original. */
const REFUTED_CONFIDENCE = 0.8;

/**
 * Which of `own`'s words argue AGAINST `category`.
 *
 * Empty when the sender wrote nothing readable against it, which is the common
 * case and the one that must stay cheap. The pattern sources are returned
 * rather than a boolean so a caller can say WHY: a cap nobody can trace back to
 * a phrase is a magic number in the making.
 *
 * THE TWO CLAUSES ARE INDEPENDENT, exactly as in Python, and the asymmetry is
 * not an oversight. Every category is checked against its own semantic
 * negatives; only the retraction family is gated on `RETRACTABLE`. So a
 * `rejection` winner can still be refuted by its own negatives — it just
 * cannot be refuted by withdrawal vocabulary, because a withdrawal from
 * consideration IS a rejection.
 *
 * Mirrors `own_text_refutes` in the Python original.
 */
export function ownTextRefutes(own: string, category: string): string[] {
  if (!own) return [];
  const hits = (SEMANTIC_REFUTATIONS[category] ?? [])
    .filter((re) => re.test(own))
    .map((re) => re.source);
  if (RETRACTABLE.has(category) && RETRACTION_RE.test(own)) hits.push(RETRACTION_RE.source);
  return hits;
}

/**
 * The one scoring walk. `classifyWithRules` runs it bare; `traceRules` passes
 * a recorder. Splitting the walk from the wrappers is what keeps the trace
 * honest by construction: there is no second reading of the rules that could
 * drift from the one that scores.
 */

/**
 * Order the categories best-first, breaking ties on what they CLAIM.
 *
 * The port of `rules.winner_first` (#451), and exported for the same reason it
 * is a named function in Python: so a test can exercise the real comparator
 * rather than a message that happens to reach it. Constructing text that ties
 * `applied` against each of five categories is a test of the PATTERNS.
 *
 * Without the second term this is a stable sort over an object whose key order
 * is `rules.json`'s — `rejection`, `interview`, `offer`, `applied`, … — which
 * is not even the order the Python side tied on (`EmailCategory` declaration
 * order, `applied` first). Two engines calling themselves the same classifier
 * resolved the same tie differently, and neither order was about the message.
 *
 * The margin is untouched: tied scores are equal, so reordering them cannot
 * move `runnerUp` and cannot move `confidence`. This decides WHICH verdict,
 * never HOW SURE.
 */
export function winnerFirst(scores: Record<string, number>): [string, number][] {
  return Object.entries(scores).sort(
    (a, b) =>
      b[1] - a[1] ||
      Number(REPORTS_ON_AN_APPLICATION.has(b[0])) -
        Number(REPORTS_ON_AN_APPLICATION.has(a[0])),
  );
}

function score(
  subject: string,
  body: string,
  sender: string | null | undefined,
  record?: (hit: RuleHit) => void,
): RulesVerdict {
  const scores: Record<string, number> = {};

  // READ BEFORE `assertedText` DESTROYS IT. When the span clears the floor it
  // IS what gets scored and there is no second reading to do; when it does
  // not, the quote is scored on its behalf and this is the only remaining
  // record of what the sender actually wrote. #417.
  //
  // `null` (no quote) and `""` (quoted and wrote nothing above it) are both
  // excluded here rather than left to falsiness: there is nothing of the
  // sender's to read in either, so nothing to contradict the quote with.
  const ownText = ownTextSpan(body);
  const quoteSpokeForIt =
    ownText !== null && ownText.length > 0 && ownText.length < MIN_ASSERTED_CHARS;

  // ONCE, before any pattern sees it. Every `re.test(body)` below is testing
  // what the sender ASSERTS. The subject's TEXT is left alone by design: it is
  // short, and a conditional subject is not a real shape. What changes below is
  // only how much a match in it is worth.
  body = assertedText(body);

  // A REPLY'S SUBJECT IS ABOUT THE THREAD, NOT ABOUT THIS MESSAGE (#441).
  //
  // The doubler exists because a subject is a headline: a sender who puts the
  // verdict there means it. Clients copy the headline onto every reply, so
  // "Re: Thank you for applying to X" is what the interview invitation, the
  // rejection and the scheduling note in that thread ALL look like.
  //
  // Demoted, not discarded — a bare "Re: Your application" carries the thread's
  // subject as its only signal. And demoted BELOW body weight rather than to
  // it: at equal weight a copied subject still ties with what the sender
  // actually wrote, and the tie-break sent a genuine interview invitation to
  // `applied`.
  const isReply = REPLY_SUBJECT_RE.test(subject ?? "");
  const strongSubject = isReply ? POINTS.strong.replySubject : POINTS.strong.subject;
  const weakSubject = isReply ? POINTS.weak.replySubject : POINTS.weak.subject;

  // THE ATS LIST IS A LIST OF DOMAINS, NOT OF SUBSTRINGS (#260, ported in #651).
  //
  // The match is ANCHORED, the same way `rules.is_ats_sender` is: a sender
  // qualifies only when its domain IS a listed domain or is a PROPER subdomain
  // of one. Do not "simplify" this back to `domain.includes(a)` — unanchored
  // containment matched an ATS name anywhere in the host, so
  // `greenhouse.io.mailgun.net`, `notlever.co.example.com` and
  // `myworkday.company.net` all read as ATS relays, and every one of those is
  // registrable by a stranger. `domain.endsWith(a)` is the same bug one step
  // in: it still accepts `xgreenhouse.io`. Only `===` or a leading dot is a
  // real boundary.
  //
  // It is load-bearing HERE and not only in Python, because `/import` is
  // public and unauthenticated: the sender arrives as a string the visitor
  // typed. On the 0.80 rung below, the +0.05 bonus lands exactly on 0.85 —
  // the value `AUTO_FILE_GATE` uses on the server for "may assert a hard
  // status" — so a domain anyone can register moved a message from held to
  // filed in this engine's answer.
  //
  // Anchoring makes two entries of `rules.json`'s `ats_domains` load-bearing
  // that containment had made redundant: `myworkday.com` does not end with
  // `.workday.com`, and `greenhouse-mail.io` is not a suffix of
  // `greenhouse.io`. Both are relays production really sees; neither may be
  // deduplicated away.
  let isAts = false;
  if (sender && sender.includes("@")) {
    const domain = sender.toLowerCase().split("@").pop() ?? "";
    isAts = ATS_DOMAINS.some((a) => domain === a || domain.endsWith(`.${a}`));
  }

  // Where a pattern matched, from the same compiled RegExp that scored it.
  // None carry the `g` flag, so `.match` returns the first match with its
  // index — the engine's `.test` answered off that same first match.
  const at = (cat: string, tier: RuleTier, field: "subject" | "body", points: number, re: RegExp) => {
    if (!record) return;
    const m = (field === "subject" ? subject : body).match(re);
    if (!m || m.index === undefined) return;
    record({ category: cat, tier, field, points, start: m.index, end: m.index + m[0].length, source: re.source });
  };

  for (const [cat, g] of Object.entries(CATS)) {
    let s = 0;
    // Tracked apart from the subject case: a subject is a headline and the
    // cheapest part of a message to make look like job mail, so it does NOT
    // outrank a genre filter reading the body. Earned, not designed — letting
    // it count turned "Thanks for applying" / "your course is unfortunately
    // over" from other into applied.
    let hasStrongBody = false;
    for (const re of g.strong) {
      if (re.test(subject)) {
        s += strongSubject;
        at(cat, "strong", "subject", strongSubject, re);
      } else if (re.test(body)) {
        s += POINTS.strong.body;
        hasStrongBody = true;
        at(cat, "strong", "body", POINTS.strong.body, re);
      }
    }
    for (const re of g.weak) {
      if (re.test(subject)) {
        s += weakSubject;
        at(cat, "weak", "subject", weakSubject, re);
      } else if (re.test(body)) {
        s += POINTS.weak.body;
        at(cat, "weak", "body", POINTS.weak.body, re);
      }
    }
    for (const re of g.negative) {
      if (!(re.test(subject) || re.test(body))) continue;
      // A negative says "this only RESEMBLES the category". Strong body
      // evidence says it does more than resemble it — but only a GENRE filter
      // may be outranked. A semantic refutation ("regret to inform" on offer)
      // keeps its full weight however strong the positive evidence, which is
      // what stops a rescinded offer reading as an offer.
      if (hasStrongBody && NOISE_NEGATIVES.has(re.source)) continue;
      s -= 5;
      at(cat, "negative", re.test(subject) ? "subject" : "body", -5, re);
    }
    for (const re of g.veto) {
      if (re.test(subject) || re.test(body)) {
        s = Math.min(s, 0);
        at(cat, "veto", re.test(subject) ? "subject" : "body", 0, re);
      }
    }
    scores[cat] = s;
  }

  const sorted = winnerFirst(scores);
  const [winner, winnerScore] = sorted[0];
  const runnerUp = sorted[1] ? sorted[1][1] : 0;

  if (winnerScore <= 0) {
    return { category: "other", confidence: 0.5, scores };
  }

  const margin = winnerScore - runnerUp;
  let confidence = 0.6;
  if (winnerScore >= 10 && margin >= 5) confidence = 0.95;
  else if (winnerScore >= 6 && margin >= 3) confidence = 0.9;
  else if (winnerScore >= 4 && margin >= 2) confidence = 0.8;
  else if (winnerScore >= 2 && margin >= 1) confidence = 0.7;

  if (isAts && ATS_BOOSTED.has(winner)) {
    confidence = Math.min(confidence + 0.05, 0.95);
  }

  // THE QUOTE SPOKE, AND THE SENDER'S OWN WORDS CONTRADICT IT. #417.
  //
  // Only reachable when the floor refused to strip, so a message whose own
  // words WERE scored can never land here — that verdict already came from the
  // sender and there is nothing to distrust. And only when those words refute
  // this particular winner, which is what keeps "Thursday works for me." over a
  // quoted invitation auto-filing as it should.
  //
  // AFTER THE ATS BONUS, not before. The bonus is +0.05 and the cap is 0.05
  // under the gate, so capping first hands every withdrawal from a Greenhouse
  // relay straight back over 0.85 — the same arithmetic that makes the anchored
  // sender match above load-bearing. `Math.min` and not assignment, so a
  // verdict already below the cap is not RAISED to it.
  //
  // The refuting patterns are not recorded on the trace. Python appends them to
  // `matched_patterns`; `RulesVerdict` has no counterpart — negatives and vetoes
  // do not surface there either — and `RuleHit` describes the SCORING walk,
  // which a refutation adds no points to. `ownTextRefutes` is exported instead,
  // so the reason is available to a caller that wants it.
  if (quoteSpokeForIt && ownTextRefutes(ownText ?? "", winner).length > 0) {
    confidence = Math.min(confidence, REFUTED_CONFIDENCE);
  }

  return { category: winner, confidence, scores };
}

/**
 * Classify a subject/body (and optional sender) with the rules layer only.
 *
 * Mirrors `RulesClassifier.classify` / `rulesClassify`: strong patterns score
 * +6 in the subject or +3 in the body; weak +2 / +1; a negative match anywhere
 * is −5; a veto match anywhere caps the category at 0 (it never raises a
 * negative score, so the runner-up margin is untouched). The top category
 * wins; confidence comes from its score and its margin over the runner-up. A
 * message from a known ATS domain gets a small boost on lifecycle categories.
 */
export function classifyWithRules(
  subject: string,
  body: string,
  sender?: string | null,
): RulesVerdict {
  return score(subject, body, sender);
}

/**
 * The same classification, with its evidence: every pattern hit the walk
 * scored, with tier, field, points and offsets. This is what "show why it
 * decided" renders from — a surface that lights matched spans must read them
 * from here, never re-run its own regexes over the text (a second derivation
 * drifts the moment rules.json moves).
 */
export function traceRules(subject: string, body: string, sender?: string | null): RulesTrace {
  const hits: RuleHit[] = [];
  const verdict = score(subject, body, sender, (hit) => hits.push(hit));
  return { verdict, hits };
}
