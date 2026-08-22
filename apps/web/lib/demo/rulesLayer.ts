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
 * Same 219 patterns, same weights (strong +3 / +6-in-subject, weak +1 / +2,
 * negative −5), same veto cap, same margin→confidence tiers, same ATS-domain
 * boost.
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
 *  so the trace cannot quote a different weight than the walk applied. */
const POINTS = {
  strong: { subject: 6, body: 3 },
  weak: { subject: 2, body: 1 },
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

const URL_RE = /https?:\/\/\S+|www\.\S+/gi;
const CONDITIONAL_RE = /\b(?:if|should you|in the event(?:\s+that)?|unless|in case)\b/i;
const SENTENCE_END_RE = /(?<=[.!?])\s+(?=["\u201c(A-Z])/;

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
 * URLs go first and that is load-bearing, not tidying: the real message puts a
 * tracking link full of base64 dots immediately before the conditional, so
 * splitting sentences on a bare `.` shatters it and the mask misses the exact
 * message it was written for.
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
  const text = body.replace(URL_RE, " ");
  return text
    .split(SENTENCE_END_RE)
    .map((sentence) => {
      const marker = CONDITIONAL_RE.exec(sentence);
      return marker ? sentence.slice(0, marker.index) : sentence;
    })
    .join(" ");
}

/**
 * The one scoring walk. `classifyWithRules` runs it bare; `traceRules` passes
 * a recorder. Splitting the walk from the wrappers is what keeps the trace
 * honest by construction: there is no second reading of the rules that could
 * drift from the one that scores.
 */
function score(
  subject: string,
  body: string,
  sender: string | null | undefined,
  record?: (hit: RuleHit) => void,
): RulesVerdict {
  const scores: Record<string, number> = {};

  // ONCE, before any pattern sees it. Every `re.test(body)` below is testing
  // what the sender ASSERTS. The subject is left alone by design: it is short,
  // and a conditional subject is not a real shape.
  body = assertedText(body);

  let isAts = false;
  if (sender && sender.includes("@")) {
    const domain = sender.toLowerCase().split("@").pop() ?? "";
    isAts = ATS_DOMAINS.some((a) => domain.includes(a));
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
        s += POINTS.strong.subject;
        at(cat, "strong", "subject", POINTS.strong.subject, re);
      } else if (re.test(body)) {
        s += POINTS.strong.body;
        hasStrongBody = true;
        at(cat, "strong", "body", POINTS.strong.body, re);
      }
    }
    for (const re of g.weak) {
      if (re.test(subject)) {
        s += POINTS.weak.subject;
        at(cat, "weak", "subject", POINTS.weak.subject, re);
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

  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
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
