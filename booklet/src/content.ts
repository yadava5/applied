/**
 * Applied System Card — copy + verified data (self-contained).
 *
 * Every number here is verified against the jobtracker repo
 * (branch main) and carries a SOURCE note where it is a
 * measured/enforced fact. Nothing is invented. Two deliberate honesty calls,
 * both grounded in the code rather than the README's marketing line:
 *
 *   · Layer 2 is PRETRAINED `intfloat/e5-small-v2` used for cosine
 *     nearest-neighbor similarity — NOT "fine-tuned e5". (embeddings.py:57
 *     loads it off-the-shelf; the app's own DecisionTrace.tsx:8 labels it
 *     plainly "e5 embedding similarity — semantic match".)
 *   · The ONLY fine-tuned model is the SetFit head, contrastively trained on
 *     `paraphrase-MiniLM-L6-v2` (6-layer MiniLM) — that fine-tuned body is
 *     what WAS exported to int8 ONNX for the browser — that build was
 *     withdrawn on 2026-08-15. (training_metadata.json)
 *
 * Illustrative decision-traces are labeled as such; they demonstrate the
 * mechanism (mirroring the app's own DEMO_REVIEW_QUEUE fixture), not a
 * benchmark result.
 */

import type { SectionKey } from "./theme";

// ---------------------------------------------------------------------------
// Brand / masthead
// ---------------------------------------------------------------------------

export const BRAND = {
  name: "Applied",
  // Two-tone wordmark split — covers tint the "lied" in rules-cyan. Kept in
  // content (not hardcoded in templates) so a rename can never strand an old
  // brand string in the TSX.
  wordmarkHead: "App",
  wordmarkTail: "lied",
  subtitle: "The inbox already holds the verdict. Classify it at the source.",
  author: "Ayush Yadav",
  year: "2026",
  liveUrl: "getapplied.vercel.app",
  qrTarget: "https://getapplied.vercel.app",
  // Was the Hugging Face Space. Made private 2026-08-15: it served the int8
  // ONNX weights of a checkpoint fitted partly on a real mailbox (iCloud IMAP,
  // not Gmail), which should not be redistributed. /import runs the rules layer
  // in the tab and ships no weights, so it is the honest "run it yourself"
  // destination now.
  spaceUrl: "getapplied.vercel.app/import",
} as const;

export const MASTHEAD = {
  volume: "Vol. 01 · System Card",
  kicker: "A 3-layer email classifier, its confidence gate, and the model that ran in a browser tab.",
  // A `colophonLines` field lived here until 2026-08-19 and rendered NOWHERE:
  // MASTHEAD is imported only by CoverPage and EndpaperPage, and only `.volume`
  // and `.kicker` are ever dereferenced. It silently swallowed a licence
  // correction (fc477ad), so it is deleted rather than maintained. The two
  // colophons that DO render are `TOC.colophon` and `BACK_COVER.colophon`.
} as const;

// ---------------------------------------------------------------------------
// Welcome / endpaper — ≤ 80 words.
// ---------------------------------------------------------------------------

export const ABSTRACT = {
  greeting: "Welcome.",
  body:
    "Every job application resolves in your inbox — a rejection, an interview, an offer, an assessment link. The verdict already exists; it is just buried. Applied reads it at the source with a three-layer cascade — 219 regex rules, e5 embedding similarity, a SetFit few-shot head — behind a 0.85 confidence gate. Below the gate, a human decides. The hosted app runs layer 1; the learned head was exported to int8 ONNX and ran in a browser tab.",
} as const;

// ---------------------------------------------------------------------------
// Chapter TOC
// ---------------------------------------------------------------------------

export const CHAPTERS = [
  { num: "01", name: "WHY", pages: "04 – 07", sectionKey: "01_WHY" as const },
  { num: "02", name: "HOW", pages: "08 – 13", sectionKey: "02_HOW" as const },
  { num: "03", name: "INSIDE", pages: "14 – 17", sectionKey: "03_INSIDE" as const },
  { num: "04", name: "PROOF", pages: "18 – 22", sectionKey: "04_PROOF" as const },
  { num: "05", name: "SECURITY", pages: "23 – 26", sectionKey: "05_SECURITY" as const },
  { num: "06", name: "BUILD", pages: "27 – 31", sectionKey: "06_BUILD" as const },
] as const;

// TOC editorial bands ----------------------------------------------------------

export const TOC = {
  chapterTaglines: {
    WHY: "the verdict is already in the inbox",
    HOW: "rules → e5 → SetFit → the gate",
    INSIDE: "int8 ONNX, zero servers — withdrawn",
    PROOF: "0.979 macro-F1 (rules stage), CI-gated",
    SECURITY: "no LLM · on-device · least-privilege",
    BUILD: "train · register · export · ship",
  } as Record<string, string>,
  chapterGlyphs: {
    WHY: "✉",
    HOW: "⌁",
    INSIDE: "◈",
    PROOF: "✓",
    SECURITY: "⬡",
    BUILD: "⣿",
  } as Record<string, string>,
  audience: [
    { key: "Engineers", val: "read the cascade, the thresholds, the ONNX export." },
    { key: "ML / research", val: "the eval + CI gate live on pages 18–22." },
    { key: "Reviewers", val: "start at §01, finish at the build pipeline." },
  ],
  readingPaths: [
    { key: "Skim · 5 min", val: "headlines, the cascade, the F1 hero." },
    { key: "Deep · 20 min", val: "cover to cover — built for one sitting." },
    { key: "Diagrams only", val: "the cascade (p.09), the trace (p.21)." },
  ],
  atAGlance: [
    { key: "3 layers", val: "219 rules · e5 similarity · SetFit head." },
    { key: "0.85 gate", val: "below it, a human decides — not the model." },
    { key: "22.8 MB", val: "int8 ONNX — ran in the browser, withdrawn." },
  ],
  glossary: [
    { term: "Cascade", def: "cheap-certain layers first, learned last." },
    { term: "e5", def: "pretrained embedding model for similarity." },
    { term: "SetFit", def: "few-shot text classifier, contrastive." },
    { term: "Gate", def: "0.85 confidence floor — necessary to auto-file." },
    { term: "macro-F1", def: "per-class F1, averaged — no class hides." },
    { term: "ONNX", def: "portable model format; runs via WASM." },
  ],
  colophon: [
    "© 2026 · Ayush Yadav",
    "Applied · System Card Vol. 01",
    // Kept on two lines: the right-aligned mono column is ~29ch wide, and the
    // single-line form wrapped with "RESERVED" orphaned on a fourth line.
    "Applied is proprietary",
    "All rights reserved",
  ],
  teaser:
    "A printed walkthrough of a live classifier — the why, the cascade, and the receipts. Read it with the demo open.",
} as const;

// ---------------------------------------------------------------------------
// The four layer identities — reused across HOW / INSIDE / PROOF.
// Thresholds from hybrid.py / config.py. Accents map to apps/web globals.css.
// ---------------------------------------------------------------------------

// NOTE 2026-08-19: `.blurb` is dereferenced NOWHERE (grep: 3 definitions, 0
// reads) — the rendered layer prose is HOW.rules / .embeddings / .setfit.
// Unlike MASTHEAD.colophonLines it IS still emitted into the bundle, because
// LAYERS is indexed dynamically, so it is dead COPY rather than dead code:
// a correction made only here changes bytes but nothing a reader sees.
export const LAYERS = [
  {
    id: "rules",
    n: "1",
    label: "Rules",
    accentKey: "02_HOW" as SectionKey, // cyan
    model: "219 regex patterns · 15 ATS domains",
    note: "instant, deterministic",
    accept: "accept ≥ 0.90",
    blurb:
      "Hand-written regular expressions match the phrases a hiring pipeline actually uses — “unfortunately”, “schedule your interview”, “we’d like to make you an offer”. Free, instant, and fully auditable.",
  },
  {
    id: "embeddings",
    n: "2",
    label: "e5 similarity",
    accentKey: "03_INSIDE" as SectionKey, // violet
    model: "intfloat/e5-small-v2 · 384-dim",
    note: "semantic match",
    accept: "accept ≥ 0.85",
    blurb:
      "When no rule is sure, the email is embedded with a pretrained e5-small-v2 model and matched by cosine similarity to the nearest labeled example. It generalizes past the exact wording the rules require. Its neighbor set is the labeled corpus as shipped; corrections do not feed back into it.",
  },
  {
    id: "setfit",
    n: "3",
    label: "SetFit head",
    accentKey: "04_PROOF" as SectionKey, // green
    model: "SetFit · MiniLM-L6 body · few-shot",
    note: "the learned call",
    accept: "accept ≥ 0.70",
    blurb:
      "The only trained model in the stack: a SetFit few-shot classifier, contrastively fine-tuned on paraphrase-MiniLM-L6-v2 from 5–10 examples per category. It is the learned call for the genuinely ambiguous email — and the model that was shipped to the browser.",
  },
] as const;

/** Per-layer accept thresholds — the cascade's fallthrough rule.
 *
 * NOTE 2026-08-19: nothing imports THRESHOLDS. It is dereferenced in no TSX and
 * is dropped from the bundle entirely — the same shape as the deleted
 * MASTHEAD.colophonLines (#345). The thresholds a reader actually sees are the
 * `accept` strings on LAYERS and HOW.cascade.steps. Values here are kept
 * correct, but a correction made ONLY here ships nothing. */
export const THRESHOLDS = {
  rules: "0.90",
  embeddings: "0.85",
  setfit: "0.70",
  gate: "0.85",
  source: "source · hybrid.py:167–168, 292, 384, 424 · config.py:324–331",
} as const;

// ---------------------------------------------------------------------------
// The 9 categories — 8 model-predicted + needs_review (human-review bucket).
// Rule counts from ml/browser/site/rules.json: strong + weak + negative
// (sum = 219 scoring patterns). The 40 `veto` patterns are not scored —
// they cap a category at zero — so they are deliberately not in this sum.
// ---------------------------------------------------------------------------

export const CATEGORIES = [
  { id: "applied", label: "applied", rules: 35, predicted: true, gloss: "confirmation your application landed." },
  { id: "pending_application", label: "pending_application", rules: 21, predicted: true, gloss: "saved / in-progress, not yet submitted." },
  { id: "interview", label: "interview", rules: 40, predicted: true, gloss: "a recruiter wants to talk." },
  { id: "rejection", label: "rejection", rules: 47, predicted: true, gloss: "“we’ve decided to move forward with…”" },
  { id: "offer", label: "offer", rules: 31, predicted: true, gloss: "the email you were waiting for." },
  { id: "assessment", label: "assessment", rules: 27, predicted: true, gloss: "a take-home or coding screen." },
  { id: "follow_up", label: "follow_up", rules: 18, predicted: true, gloss: "nudges, scheduling, status pings." },
  { id: "other", label: "other", rules: 0, predicted: true, gloss: "not job-related — filtered out." },
  { id: "needs_review", label: "needs_review", rules: 0, predicted: false, gloss: "below the gate — routed to a human." },
] as const;

// NOTE 2026-08-19: only `total`, `predicted` and `ruleTotal` are read
// (ProofClassesPage). `note` and `source` are dereferenced NOWHERE and are
// dropped from the bundle — the same shape as the deleted MASTHEAD.colophonLines
// (#345). The rendered source note on that page is `PROOF.classes.source`.
// Correct THAT one; a fix here ships nothing.
export const CATEGORIES_META = {
  total: 9,
  predicted: 8,
  ruleTotal: 219,
  ruleCategories: 7,
  note: "8 categories are model-predicted; needs_review is a routing bucket, not a trained label — it is the confidence gate's output.",
  source: "source · database/models.py:126–138 · rules.json (219 scoring patterns / 7 categories)",
} as const;

// ---------------------------------------------------------------------------
// Section 01 — WHY
// ---------------------------------------------------------------------------

export const WHY = {
  divider: { subtitle: "the verdict is already sitting in your inbox" },

  inbox: {
    eyebrow: "§01 · THE INBOX",
    headline: "The inbox already holds the verdict.",
    pullQuote:
      "Every application ends in an email. The outcome already exists — it is just buried in a thousand unread threads.",
    body: [
      "A job search does not resolve on a career portal. It resolves in your inbox: a rejection at 6am, an interview invite from a recruiter, an assessment link with a 48-hour clock, an offer you almost missed. The verdict for every application you have ever sent is already written down — as email.",
      "The problem was never a missing signal. It is that the signal arrives unlabeled, interleaved with newsletters and receipts, across two accounts, faster than anyone keeps up with by hand.",
    ],
    coda:
      "So the tracker should not ask you to log anything. It should read what already arrived.",
    signals: [
      { label: "REJECTION", hue: "danger", quote: "“Unfortunately, we’ve decided…”" },
      { label: "INTERVIEW", hue: "rules", quote: "“Let’s schedule a time to talk.”" },
      { label: "OFFER", hue: "setfit", quote: "“We’d like to make you an offer.”" },
      { label: "ASSESSMENT", hue: "e5", quote: "“Complete this by Friday.”" },
    ],
  },

  lossy: {
    eyebrow: "§01 · THE COST",
    headline: "Doing it by hand is lossy.",
    lede:
      "The manual workflow is a spreadsheet you update from memory. It fails quietly, and it fails in exactly the moments that matter.",
    beforeTitle: "MANUAL TRACKING",
    withTitle: "CLASSIFY AT THE SOURCE",
    before: [
      "You copy each status into a spreadsheet from memory, days late.",
      "An assessment email scrolls past; the deadline passes unseen.",
      "Two accounts, one search — half the thread lives where you aren’t looking.",
      "“Did I hear back from them?” has no answer but a scroll.",
      "The row says “applied” three weeks after they said no.",
    ],
    with: [
      "Every email is labeled the moment it syncs — nothing to log.",
      "Assessments and interviews surface as their own categories.",
      "Gmail and iCloud fold into one classified pipeline.",
      "Status is a query, not a memory: it is already on the record.",
      "A rejection reclassifies the application the second it lands.",
    ],
    gate: "The manual tracker is only ever as fresh as your discipline. Classification never gets tired.",
  },

  source: {
    eyebrow: "§01 · THE REFRAME",
    headline: "The real problem is classification.",
    body: [
      "Reframe the product. “Tracking” is bookkeeping — a symptom. The underlying task is classification: given an email, which of a handful of job-search outcomes is this, and how sure are we?",
      "Solve that at the source and the tracker maintains itself. Applications link, statuses advance, and the pipeline view is just a projection over labeled email. The interface stops being a form you fill in and becomes a ledger that fills itself.",
    ],
    thesis:
      "If you can label the email, you never have to track the application.",
    reframe: [
      { from: "“log this application”", to: "classify this email" },
      { from: "“update the status”", to: "read the next verdict" },
      { from: "“remember to check”", to: "query the record" },
    ],
    handoff: "So: how do you classify an inbox reliably? Turn the page.",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 02 — HOW
// ---------------------------------------------------------------------------

export const HOW = {
  divider: { subtitle: "rules first · then similarity · then the learned head" },

  cascade: {
    eyebrow: "§02 · THE CASCADE",
    headline: "Three layers, cheapest first.",
    lede:
      "One email enters the top. Each layer tries to decide; if it clears its accept threshold, the cascade stops and files. If not, it falls through to a smarter, costlier layer — and finally to a gate.",
    body:
      "The order is deliberate: a free, deterministic regex is tried before a 384-dimension embedding lookup, which is tried before the trained SetFit head. Most email is decided by the cheap layers; only the genuinely ambiguous message reaches the model — and only a confident model auto-files. Scope: the hosted deployment runs layer 1 alone — the serverless entrypoint pins cloud mode, and cloud mode never constructs layers 2 and 3. The full cascade is the desktop and evaluation path.",
    steps: [
      { n: "1", label: "Rules", detail: "regex + ATS domains", accept: "≥ 0.90", accentKey: "02_HOW" },
      { n: "2", label: "e5 similarity", detail: "cosine 1-NN", accept: "≥ 0.85", accentKey: "03_INSIDE" },
      { n: "3", label: "SetFit head", detail: "few-shot learned", accept: "≥ 0.70", accentKey: "04_PROOF" },
      { n: "◇", label: "Gate", detail: "human review", accept: "< 0.85", accentKey: "01_WHY" },
    ],
    source: "source · classifier/hybrid.py:254–571 (classify order + thresholds) · :199–200 + api/index.py:35 (cloud ⇒ rules only)",
  },

  // Per-layer detail pages pull from LAYERS above (NOT from THRESHOLDS —
  // LayerDetailPages imports { HOW, LAYERS } only; see the note on THRESHOLDS).
  rules: {
    eyebrow: "§02 · LAYER 1",
    headline: "219 rules that never guess.",
    body: [
      "The first layer is 219 scoring regular expressions across seven outcome categories, plus 15 known applicant-tracking-system sender domains. It is free, instant, and completely auditable — you can read exactly why any email was filed.",
      "Rules only auto-accept above 0.90 confidence. A rule that is merely plausible defers to the layers below rather than risk a wrong, silent file.",
    ],
    stat: { value: "219", label: "regex patterns · 7 categories" },
    stat2: { value: "0.90", label: "auto-accept threshold" },
    note: "A regex is a promise you can inspect. That is why it goes first.",
  },
  embeddings: {
    eyebrow: "§02 · LAYER 2",
    headline: "Similarity, not exact words.",
    body: [
      "When no rule is sure, the email is embedded with a pretrained e5-small-v2 model (384 dimensions) and matched by cosine similarity to the nearest labeled example. It catches the rejection that never says “rejected”.",
      "The e5 weights are used off the shelf — not fine-tuned. Growing the neighbor set is how this layer would learn, and the code to do it exists — but nothing in the codebase calls it, so a correction adds no neighbor. The set is the labeled corpus as shipped.",
    ],
    stat: { value: "384-d", label: "e5-small-v2 embedding" },
    stat2: { value: "1-NN", label: "cosine nearest neighbor" },
    note: "Honest framing: pretrained e5 for similarity — the fine-tuning lives one layer down.",
  },
  setfit: {
    eyebrow: "§02 · LAYER 3",
    headline: "The one model that learns.",
    body: [
      "The last layer is a SetFit few-shot classifier — contrastively fine-tuned on a paraphrase-MiniLM-L6-v2 body from just 5–10 examples per category. SetFit needs no giant labeled set; it learns the shape of each outcome from a handful.",
      "It is the learned call for the genuinely ambiguous email, and the only trained model in the stack. This is the body that was exported to ONNX and shipped to a browser tab — a build withdrawn on 2026-08-15.",
    ],
    stat: { value: "5–10", label: "examples / category (few-shot)" },
    stat2: { value: "0.70", label: "accept threshold" },
    note: "MiniLM-L6, not e5 — verified against the model card, not the marketing.",
  },

  gate: {
    eyebrow: "§02 · THE GATE",
    headline: "Below 0.85, a human decides.",
    lede:
      "The cascade never auto-files a guess. A confidence gate at 0.85 is the first thing standing between “file it” and “ask a person” — and not the only one.",
    body:
      "Clearing the gate is necessary to file, not sufficient. Applied must also name the employer and place the mail against a single application; a verdict at 1.0 with no nameable employer is not filed — it joins the review queue alongside everything below 0.85. A human’s answer there is recorded on the email, and no later sync overwrites it.",
    bands: [
      { range: "≥ 0.85", verb: "AUTO-FILE", tone: "setfit", detail: "confident — filed, if the employer can be named." },
      { range: "0.70 – 0.84", verb: "FLAG", tone: "gate", detail: "uncertain — queued for a human." },
      { range: "< 0.70", verb: "FALL BACK", tone: "danger", detail: "no confident layer — needs_review." },
    ],
    recordNote:
      "Every correction is stored in training_data — every category, other included — and flags the email user_corrected, so a later sync leaves the human’s answer alone. Nothing retrains on it: the deployed classifier is rules-only, the row is scoped to the one account that made it, and it is never pooled with another user’s.",
    source: "source · cloud/pipeline.py · _qualifies_for_hard_row + unplaceable_message_ids · cloud/applications.py · _add_training_example",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 03 — INSIDE
// ---------------------------------------------------------------------------

export const INSIDE = {
  divider: { subtitle: "the engine room — and the model that fits in a browser tab" },

  architecture: {
    eyebrow: "§03 · ARCHITECTURE",
    headline: "One pipeline, and what it records.",
    body:
      "The classifier is a hybrid pipeline in backend/jobtracker/classifier: a content guard, then rules, then embedding similarity, then SetFit, then a fallback that is always safe (needs_review rather than a wrong guess). Corrections write to training_data and flag the email user_corrected; embeddings persist in email_embeddings. The hosted deployment runs the guard and the rules only; layers 2 and 3 are never constructed under cloud mode, so the drawing below is the desktop and evaluation path. Nothing retrains on corrections automatically — retraining is an operator command, not a loop, and it is default-deny: refused unless the corpus is entirely synthetic or its single owner is explicitly allowlisted. Your mail is never pooled with anyone else's. Every training entry point requires a user id, the corpus is filtered by it, and the loaded rows are re-checked, so a corpus spanning two users raises instead of training.",
    flow: [
      { stage: "guard", detail: "force non-job → other" },
      { stage: "rules", detail: "219 regex · ≥ 0.90" },
      { stage: "e5", detail: "cosine 1-NN · ≥ 0.85" },
      { stage: "setfit", detail: "few-shot · ≥ 0.70" },
      { stage: "gate", detail: "0.85 → auto / human" },
      { stage: "record", detail: "correction → training_data" },
    ],
    source: "source · classifier/hybrid.py:189–200, 254–571 · docs/ARCHITECTURE.md:80–90",
  },

  onnx: {
    eyebrow: "§03 · THE EXPORT",
    headline: "90 megabytes down to 23.",
    lede:
      "The fine-tuned SetFit body was exported to ONNX and dynamically quantized to int8 — the weights dropped from float32 to 8-bit integers with no accuracy floor breached.",
    body:
      "The full-precision ONNX graph was 90.4 MB. Dynamic int8 quantization compressed it roughly four-fold to 22.8 MB — small enough to download once and run on a laptop’s CPU, in a browser tab, with no GPU and no backend. The weights were withdrawn on 2026-08-15; the export script still produces them from a checkpoint.",
    before: { value: "90.4 MB", label: "float32 ONNX" },
    after: { value: "22.8 MB", label: "int8 quantized" },
    ratio: "≈ 4× smaller",
    exact: "22,843,695 bytes",
    source: "source · ml/browser/export_onnx.py · artifact sizes recorded in 1efb0b3, the commit that removed them",
  },

  browser: {
    eyebrow: "§03 · ZERO SERVERS",
    headline: "It ran in your browser.",
    body: [
      "The quantized model was loaded by Transformers.js (3.5.2) over onnxruntime-web, executing in WebAssembly on the client. allowRemoteModels was false and the model path local — the tab fetched the weights once and never phoned home.",
      "It ran in a Hugging Face Space, never on getapplied.vercel.app: this app’s strict CSP forbids the WASM eval Transformers.js needs. The Space went private and the weights left the repository on 2026-08-15.",
    ],
    facts: [
      { k: "RUNTIME", v: "Transformers.js 3.5.2 · onnxruntime-web (WASM)" },
      { k: "STATUS", v: "withdrawn 2026-08-15 · weights unpublished" },
      { k: "MODEL", v: "int8 ONNX · 22.8 MB · fetched once" },
      { k: "PRIVACY", v: "allowRemoteModels = false · nothing left the tab" },
    ],
    parity: {
      claim: "6 / 6",
      label: "output-agreement suite vs the Python pipeline",
      honest:
        "Stated on the model card and the Space’s landing page (app.js:12–13) as a code-verified claim; no automated parity test was ever committed, and the weights it refers to are no longer published — so we print it as documented history, not a benchmark we re-ran.",
    },
    source: "source · ml/browser/site/app.js:12–13, 16, 18–20 · site/README.md (Space private, weights withdrawn)",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 04 — PROOF
// ---------------------------------------------------------------------------

export const PROOF = {
  divider: { subtitle: "what we measured — and the gate that guards it" },

  f1: {
    eyebrow: "§04 · THE NUMBER",
    headline: "0.979 macro-F1.",
    hero: "0.979",
    heroLabel: "macro-F1 · rules stage",
    body:
      "Macro-F1 averages the per-class F1 so no category can hide behind the frequent ones. On the held-out evaluation the RULES stage scores 0.9791 — accuracy 0.9792, two emails misclassified. Not the full cascade, which scores 0.9583 on the same set: the evaluation runs under the `deterministic` hybrid profile, which disables SetFit and blanks the embedding examples, so the file named baseline_hybrid_v3.json measures the regexes alone. It is not a cherry-picked accuracy headline; it is the metric that punishes a weak class.",
    exact: "0.9791304 macro-F1 · 0.9792 accuracy · 2 misclassified",
    ciValue: "0.95",
    ciLabel: "CI floor — the merge blocks below it",
    ciBody:
      "The score is not a one-time screenshot. Two GitHub Actions gates re-run the evaluation on every backend change and fail the build if macro-F1 drops below 0.95. The number is load-bearing.",
    source: "source · baseline_hybrid_v3.json:114–115 · backend-ci.yml:143,155 (--min-macro-f1 0.95)",
  },

  classes: {
    eyebrow: "§04 · THE TAXONOMY",
    headline: "Nine categories, eight learned.",
    lede:
      "The classifier files into nine categories. Eight are model-predicted outcomes; the ninth, needs_review, is not a label the model emits — it is where the pipeline puts what it will not file unaided: everything below the gate, and confident mail whose employer it cannot name.",
    note: "needs_review is a routing decision, not a trained class — which is the whole safety story in one row.",
    source: "source · database/models.py:126–138",
  },

  trace: {
    eyebrow: "§04 · THE DECISION TRACE",
    headline: "Every verdict, traced.",
    lede:
      "The signature Applied visual: each email’s path through the three layers and the gate. The layer that fired lights in its own hue; earlier layers passed it on, later layers were never needed. Confidence is drawn against the 0.85 gate.",
    // Illustrative traces — demonstrate the mechanism (mirrors the app's
    // DEMO_REVIEW_QUEUE fixture); confidences illustrate behavior, not a benchmark.
    illustrativeNote: "Illustrative traces — the mechanism, not measured metrics.",
    rows: [
      { subject: "Unfortunately, we won’t be moving forward", from: "no-reply@greenhouse.io", fired: 0, category: "rejection", confidence: 0.97, needsReview: false },
      { subject: "Your Stripe application was received", from: "jobs@stripe.com", fired: 0, category: "applied", confidence: 0.95, needsReview: false },
      { subject: "Next steps for your candidacy", from: "recruiting@datadog.com", fired: 1, category: "interview", confidence: 0.88, needsReview: false },
      { subject: "A quick update on your process", from: "talent@notion.so", fired: 2, category: "follow_up", confidence: 0.79, needsReview: true },
      { subject: "Re: your profile", from: "hiring@earlystage.xyz", fired: 2, category: "assessment", confidence: 0.66, needsReview: true },
    ],
    legendGate: "below 0.85 → human",
  },

  tests: {
    eyebrow: "§04 · THE GUARANTEE",
    headline: "1,309 tests, and 14,540 messages written to break the classifier.",
    body:
      "Correctness is not asserted, it is enforced. The backend suite runs 1,309 tests, all passing — including the twenty-one Postgres row-level-security tests, which provision their own postgres:16 through testcontainers instead of skipping — and two CI gates re-run the classifier evaluation on every change, refusing to merge if macro-F1 falls below 0.95. A suite only checks what somebody thought to check, so there is a second instrument: 17,140 generated messages across 36 families over 7,960 companies — every employer and role invented, six of those families phrased in wordings transcribed from mail that actually arrived — 18% of them adversarial by construction, driven through the whole sync end to end — classify, roll up, upsert, persist the review queue, then read the board back out of the tables, replayed in day-sized batches because a real sync is a delta and not a whole mailbox. 15,816 come out correct (92.28%), 311 wrong, 1013 abstained. No message lands on another application's card: 9,192 cards, 0 merges, 0 misrouted review, 0 updates on a card that was not theirs. 0 applications are split across two cards; that number is kept separate from merges because a split is the milder failure, visible to the user rather than silent. Zero messages that should mint nothing do mint a card, and that is the exception rather than a rounding of it. What the corpus could not see until it ran the review path is that 11 messages about real applications reach no card, no queue and no counter at all.",
    stats: [
      { value: "1,309", label: "tests · backend suite", note: "0 failed · 2026-08-22" },
      { value: "17,140", label: "messages · adversarial corpus", note: "36 families · 7,960 companies" },
      { value: "92.28%", label: "correct · stress corpus", note: "311 wrong · 1013 abstained" },
    ],
    honest:
      "Provenance: 1,309 is what `PYTHONPATH=. pytest tests -q --ignore=tests/test_setfit_model.py --ignore=tests/test_evaluate_classifier.py` passes from backend/, run 2026-08-22 on Python 3.11.14 with a Docker daemon available — without Docker and without JOBTRACKER_TEST_PG_ADMIN_URL the twenty-one row-level-security tests skip, and database-level tenant isolation is then simply unverified on that run. The corpus figure carries the worse condition, and printing it is the whole point: 72 of the 311 wrong verdicts sit above the 0.85 auto-file gate and are stated to the reader as fact, while 200 fall below it and are held for a person to settle. That ratio is the number worth watching, not the total — 50 wrong verdicts all auto-filed would be a worse product than 311 with 72 auto-filed. It read 464 of 464 above the gate on the morning of 2026-08-22, before the classifier stopped scoring quoted history and a reply's copied subject as the message's own words. And 18% of that mail is adversarial by construction, so 92.28% is behaviour under stress, not the accuracy an inbox would produce. The figure a reader should weigh against it is the one the corpus could not measure until it began running the review path: 11 of those messages are about real applications and reach nothing at all, which no accuracy number expresses. The test figure was 305 on 2026-08-06; the suite has grown, it has not been re-scoped.",
    handoffQuote:
      "A classifier that knows when to stop is worth more than one that is always sure.",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 05 — SECURITY & PRIVACY
//
// Every claim on these pages is verified against the code on branch
// integration/web-migration and carries a SOURCE note. Two deliberate honesty
// calls, both grounded in the code rather than a marketing line:
//
//   · The on-device MAIL IMPORT classifies with the deterministic LAYER-1
//     rules live in the tab (lib/demo/rulesLayer.ts). That is the ONLY in-tab
//     classification Applied ships. The full three-layer int8 model (e5 +
//     SetFit) RAN in a Hugging Face Space — private since 2026-08-15, when
//     the weights were withdrawn — and never in apps/web's own tab, whose
//     strict CSP forbids the WASM eval it needs.
//   · Disconnect REVOKES at Google (POST oauth2.googleapis.com/revoke) and is
//     best-effort: confirmed when Google returns 2xx; the local encrypted row
//     is deleted either way. We print it as "revokes, and confirms on 2xx",
//     not as a guarantee.
// ---------------------------------------------------------------------------

export const SECURITY = {
  divider: { subtitle: "no LLM reads the inbox · it can run on-device · Gmail is read-only" },

  // Page 24 — no LLM in the classify path.
  noLlm: {
    eyebrow: "§05 · NO LLM",
    headline: "No LLM reads your mail.",
    lede:
      "The classifier is not a prompt to somebody else's model. It is a three-layer cascade you can read line by line — no third-party LLM ever sees the inbox.",
    body:
      "Classification runs entirely on code that ships in this repo: 219 regex rules, then cosine similarity against a pretrained e5 embedding, then the fine-tuned SetFit head — and the hosted deployment runs the rules alone. There is no OpenAI, Anthropic, or Gemini call anywhere in the classify path — the classifier module imports no LLM API at all.",
    path: [
      { n: "1", label: "regex rules", note: "deterministic · auditable", accentKey: "02_HOW" as SectionKey },
      { n: "2", label: "e5 similarity", note: "cosine 1-NN · pretrained", accentKey: "03_INSIDE" as SectionKey },
      { n: "3", label: "SetFit head", note: "few-shot · local weights", accentKey: "04_PROOF" as SectionKey },
    ],
    absent: "LLM / third-party inference API",
    absentNote: "never called in the classify path",
    honest:
      "The only “openai” / “anthropic” strings in the backend are an employer-name lookup — recognizing that a recruiter writing from openai.com works at “OpenAI”. It is a dictionary, not an API client, and the classifier never imports it.",
    facts: [
      { k: "CLASSIFY PATH", v: "rules → e5 cosine → SetFit — all in-repo" },
      { k: "LLM CALLS", v: "zero · no OpenAI / Anthropic / Gemini SDK" },
      { k: "EMBEDDING", v: "intfloat/e5-small-v2 · loaded locally" },
      { k: "AUDITABILITY", v: "every layer is code you can read" },
    ],
    source: "source · classifier/hybrid.py:292,384,424 · embeddings.py:78,99 · no LLM import in classifier/",
  },

  // Page 25 — on-device: in-browser model + on-device import.
  onDevice: {
    eyebrow: "§05 · ON-DEVICE",
    headline: "It can run with zero servers.",
    lede:
      "Two ways to classify without your mail ever leaving the machine — one needs no account at all and ships today; one ran the full model in a browser tab, and was withdrawn.",
    modes: [
      {
        tag: "IN-BROWSER MODEL · WITHDRAWN",
        title: "The int8 ONNX classifier ran in the tab.",
        body:
          "The 22.8 MB quantized model loaded over Transformers.js + onnxruntime-web (WASM) with allowRemoteModels = false and a local path. It fetched the weights once and never phoned home. The weights were withdrawn on 2026-08-15.",
        checks: ["allowRemoteModels = false", "22.8 MB · fetched once", "withdrawn · 2026-08-15"],
        accentKey: "03_INSIDE" as SectionKey,
      },
      {
        tag: "ON-DEVICE IMPORT",
        title: "Drop a mail export; classify it in the tab.",
        body:
          "Point it at a Google Takeout MBOX, an .eml, or a JSON batch. The file is parsed and classified entirely in the browser by the layer-1 rules — no upload, no server, no OAuth. The mail never leaves your device.",
        checks: ["MBOX · .eml · JSON", "no upload · no OAuth", "parsed + classified in-tab"],
        accentKey: "05_SECURITY" as SectionKey,
      },
    ],
    formats: ["Google Takeout MBOX", ".eml (RFC-822)", "JSON batch"],
    honest:
      "Honest scope: the import classifies with the deterministic rules layer live in your tab — the only in-tab classification Applied ships. The full three-layer int8 model ran in a Hugging Face Space, private since 2026-08-15 when the weights were withdrawn; apps/web's strict CSP always kept WASM/ONNX out of its own tab.",
    source: "source · ml/browser/site/app.js:18–20 · site/README.md · import/ImportMail.tsx:6,118–120 · parseMail.ts:41,63",
  },

  // Page 26 — Gmail: least-privilege, encrypted, revocable, invite-gated.
  gmail: {
    eyebrow: "§05 · GMAIL ACCESS",
    headline: "Read-only, encrypted, revocable.",
    lede:
      "When you do connect Gmail, the grant is the narrowest Google offers, the token is encrypted at rest, and disconnect revokes it at Google — not just locally.",
    scopeGranted: { label: "gmail.readonly", note: "read message metadata + bodies" },
    scopeWithheld: ["send", "delete", "modify", "compose", "settings"],
    scopeCaption: "one scope requested; everything that could change your mailbox is never asked for.",
    rows: [
      {
        k: "ENCRYPTED AT REST",
        v: "The refresh token is a Fernet-encrypted blob in the database; the key lives only in the backend env — the token is never in the browser, a URL, or a log.",
      },
      {
        k: "REVOKES AT GOOGLE",
        v: "Disconnect POSTs the token to oauth2.googleapis.com/revoke, then deletes the local row. The revoke is confirmed when Google returns 2xx; the row is deleted either way.",
      },
      {
        k: "CSRF-BOUND",
        v: "The OAuth round-trip carries a signed, short-lived state token bound to your user id; the callback returns only gmail=connected — never a token.",
      },
    ],
    beta: {
      label: "BETA · INVITE-ONLY",
      body:
        "Google caps an unverified app on a restricted scope at 100 test users, so direct Gmail connect is invite-only until the app clears verification. The sample inbox and the on-device import work for everyone, no account required.",
      seats: "100",
      seatsNote: "Google's test-user cap — the real limit, not a marketing number",
    },
    source: "source · gmail_oauth.py:126,527,695,1303 · config.py:293 · credentials/cloud.py:107,275 · DEPLOY.md:121 · beta/constants.ts:16",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 06 — BUILD
// ---------------------------------------------------------------------------

export const BUILD = {
  divider: { subtitle: "train · register · export · ship" },

  pipeline: {
    eyebrowLeft: "§05 · THE PIPELINE · LEFT",
    eyebrowRight: "§05 · THE PIPELINE · RIGHT",
    headlineLeft: "From a training run…",
    headlineRight: "…to a tab with no backend.",
    subLeft:
      "SetFit trains on the labeled corpus; the run logs to MLflow and the model is registered — promoted to the “production” alias only once it clears the 0.95 floor.",
    subRight:
      "The registered body was exported to int8 ONNX and published to a Hugging Face Space — inference on the client, until the Space went private in August 2026.",
    stages: [
      { n: "1", label: "TRAIN", detail: "SetFit · MiniLM-L6 body", accentKey: "04_PROOF" },
      { n: "2", label: "MLflow", detail: "log + register · gate 0.95", accentKey: "06_BUILD" },
      { n: "3", label: "ONNX", detail: "export · int8 · 22.8 MB", accentKey: "03_INSIDE" },
      { n: "4", label: "HF SPACE", detail: "static · withdrawn", accentKey: "02_HOW" },
      { n: "5", label: "WEB", detail: "Next.js 16 · Vercel", accentKey: "01_WHY" },
    ],
    registry:
      "MLflow model “jobtracker-hybrid-classifier” · alias “production” set only past the 0.95 macro-F1 floor.",
    // NOT RENDERED: SpreadPage reads only .registry/.stages/.headline*/.sub*, so
    // this note is dropped from the bundle (#345 shape). Kept correct anyway.
    source: "source · ml/track_run.py:30–31,124,131 · ml/browser/export_onnx.py",
  },

  stack: {
    eyebrow: "§05 · THE STACK",
    headline: "What it is built on.",
    lede:
      "A native macOS app and a FastAPI backend where the model was born; a Next.js 16 web app where it ships, and a portable ONNX model that once ran in a tab.",
    rows: [
      { area: "WEB", tech: "Next.js 16.3.0 · React 19 · Vercel", note: "the hosted product + live demo" },
      { area: "IN-BROWSER ML", tech: "Transformers.js 3.5.2 · onnxruntime-web", note: "int8 ONNX on the client — withdrawn 2026-08-15" },
      { area: "CLASSIFIER", tech: "e5-small-v2 · SetFit / MiniLM-L6 · 219 regex", note: "the 3-layer hybrid cascade — hosted runs layer 1" },
      { area: "TRAINING", tech: "MLflow registry · CI-gated ≥ 0.95", note: "log, register, promote to production" },
      { area: "BACKEND", tech: "FastAPI · SQLModel · Postgres", note: "sync, classify, review queue — SQLite on desktop" },
      { area: "DESKTOP", tech: "SwiftUI macOS app", note: "the original native client — de-scoped 2026-08-12" },
    ],
    source: "source · apps/web/package.json:27 · ml/browser/site/app.js:16 · ml/track_run.py · backend/pyproject.toml",
  },

  // Page 31 — Try it. The reader's exit into the live product: the QR lives
  // here now (the very last page is a quiet closing, not a CTA).
  closing: {
    eyebrow: "TRY IT",
    headline: "Run it yourself.",
    tagline: "Scan to open the live app — or drop a mail export and watch the rules layer classify it, past the gate, in your browser.",
    qrTarget: "https://getapplied.vercel.app",
    qrCaption: "scan to open the live web app",
    liveLabel: "LIVE WEB APP",
    liveUrl: "getapplied.vercel.app",
    spaceLabel: "IN-BROWSER CLASSIFIER",
    spaceUrl: "getapplied.vercel.app/import",
    spaceNote: "219 rules · zero servers · runs entirely in the tab",
    leftArrowLabel: "open it",
    rightArrowLabel: "classify",
    microNote: "three layers · one gate · zero servers",
  },
} as const;

// ---------------------------------------------------------------------------
// Back cover — a PURE CLOSING that mirrors the cover: the same wraparound
// envelope field, a quiet closing line, the colophon. No QR, no CTA — the
// Try-It page (31) sends the reader to the product; page 32 just closes.
// ---------------------------------------------------------------------------

export const BACK_COVER = {
  wordmark: "Applied",
  closingLine: "The verdict was always in the inbox.",
  coda: "Now it reads itself.",
  edgeNote: "end · vol. 01",
  signature: "System Card · Vol. 01",
  colophon: [
    "Applied · System Card · Vol. 01",
    "Ayush Yadav · 2026 · all rights reserved",
    "Applied is proprietary · classify at the source",
  ],
} as const;
