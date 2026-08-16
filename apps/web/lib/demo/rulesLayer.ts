/**
 * Layer 1 of the classifier — the regex rules engine — ported to the browser.
 *
 * This is a faithful, byte-for-byte port of the scoring in the shipped
 * classifier: `backend/jobtracker/classifier/rules.py` and its in-browser
 * twin `ml/browser/site/app.js`. That twin used to be published as a Hugging
 * Face Space; the Space was made private on 2026-08-15 because it served the
 * weights of a checkpoint fitted partly on restricted-scope Gmail. This port is
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
  const scores: Record<string, number> = {};

  let isAts = false;
  if (sender && sender.includes("@")) {
    const domain = sender.toLowerCase().split("@").pop() ?? "";
    isAts = ATS_DOMAINS.some((a) => domain.includes(a));
  }

  for (const [cat, g] of Object.entries(CATS)) {
    let s = 0;
    for (const re of g.strong) {
      if (re.test(subject)) s += 6;
      else if (re.test(body)) s += 3;
    }
    for (const re of g.weak) {
      if (re.test(subject)) s += 2;
      else if (re.test(body)) s += 1;
    }
    for (const re of g.negative) {
      if (re.test(subject) || re.test(body)) s -= 5;
    }
    for (const re of g.veto) {
      if (re.test(subject) || re.test(body)) s = Math.min(s, 0);
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
