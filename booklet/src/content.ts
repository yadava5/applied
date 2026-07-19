/**
 * JobTracker System Card — copy + verified data (self-contained).
 *
 * Every number here is verified against the jobtracker repo
 * (branch integration/web-migration) and carries a SOURCE note where it is a
 * measured/enforced fact. Nothing is invented. Two deliberate honesty calls,
 * both grounded in the code rather than the README's marketing line:
 *
 *   · Layer 2 is PRETRAINED `intfloat/e5-small-v2` used for cosine
 *     nearest-neighbor similarity — NOT "fine-tuned e5". (embeddings.py:57
 *     loads it off-the-shelf; the app's own DecisionTrace.tsx:8 labels it
 *     plainly "e5 embedding similarity — semantic match".)
 *   · The ONLY fine-tuned model is the SetFit head, contrastively trained on
 *     `paraphrase-MiniLM-L6-v2` (6-layer MiniLM) — that fine-tuned body is
 *     what is exported to int8 ONNX for the browser. (training_metadata.json)
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
  name: "JobTracker",
  subtitle: "The inbox already holds the verdict. Classify it at the source.",
  author: "Ayush Yadav",
  year: "2026",
  liveUrl: "jobtracker-web-five.vercel.app",
  qrTarget: "https://jobtracker-web-five.vercel.app",
  spaceUrl: "huggingface.co/spaces/yadava5/jobtracker-classifier",
} as const;

export const MASTHEAD = {
  volume: "Vol. 01 · System Card",
  kicker: "A 3-layer email classifier, its confidence gate, and the model that runs in your browser.",
  colophonLines: [
    "© 2026 · Ayush Yadav",
    "3-layer email classifier · macOS + web",
    "Model: MIT · runs in-browser via ONNX",
  ],
} as const;

// ---------------------------------------------------------------------------
// Welcome / endpaper — ≤ 80 words.
// ---------------------------------------------------------------------------

export const ABSTRACT = {
  greeting: "Welcome.",
  body:
    "Every job application resolves in your inbox — a rejection, an interview, an offer, an assessment link. The verdict already exists; it is just buried. JobTracker reads it at the source with a three-layer cascade — 201 regex rules, e5 embedding similarity, a SetFit few-shot head — behind a 0.85 confidence gate. Below the gate, a human decides. The learned head ships as int8 ONNX and runs entirely in your browser.",
} as const;

// ---------------------------------------------------------------------------
// Chapter TOC
// ---------------------------------------------------------------------------

export const CHAPTERS = [
  { num: "01", name: "WHY", pages: "04 – 07", sectionKey: "01_WHY" as const },
  { num: "02", name: "HOW", pages: "08 – 13", sectionKey: "02_HOW" as const },
  { num: "03", name: "INSIDE", pages: "14 – 17", sectionKey: "03_INSIDE" as const },
  { num: "04", name: "PROOF", pages: "18 – 22", sectionKey: "04_PROOF" as const },
  { num: "05", name: "BUILD", pages: "23 – 27", sectionKey: "05_BUILD" as const },
] as const;

// TOC editorial bands ----------------------------------------------------------

export const TOC = {
  chapterTaglines: {
    WHY: "the verdict is already in the inbox",
    HOW: "rules → e5 → SetFit → the gate",
    INSIDE: "int8 ONNX, zero servers",
    PROOF: "0.979 macro-F1, CI-gated",
    BUILD: "train · register · export · ship",
  } as Record<string, string>,
  chapterGlyphs: {
    WHY: "✉",
    HOW: "⌁",
    INSIDE: "◈",
    PROOF: "✓",
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
    { key: "3 layers", val: "201 rules · e5 similarity · SetFit head." },
    { key: "0.85 gate", val: "below it, a human decides — not the model." },
    { key: "22.8 MB", val: "int8 ONNX, running entirely in the browser." },
  ],
  glossary: [
    { term: "Cascade", def: "cheap-certain layers first, learned last." },
    { term: "e5", def: "pretrained embedding model for similarity." },
    { term: "SetFit", def: "few-shot text classifier, contrastive." },
    { term: "Gate", def: "0.85 confidence cutoff to auto-file." },
    { term: "macro-F1", def: "per-class F1, averaged — no class hides." },
    { term: "ONNX", def: "portable model format; runs via WASM." },
  ],
  colophon: [
    "© 2026 · Ayush Yadav",
    "JobTracker · System Card Vol. 01",
    "Model licensed MIT",
  ],
  teaser:
    "A printed walkthrough of a live classifier — the why, the cascade, and the receipts. Read it with the demo open.",
} as const;

// ---------------------------------------------------------------------------
// The four layer identities — reused across HOW / INSIDE / PROOF.
// Thresholds from hybrid.py / config.py. Accents map to apps/web globals.css.
// ---------------------------------------------------------------------------

export const LAYERS = [
  {
    id: "rules",
    n: "1",
    label: "Rules",
    accentKey: "02_HOW" as SectionKey, // cyan
    model: "201 regex patterns · 14 ATS domains",
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
      "When no rule is sure, the email is embedded with a pretrained e5-small-v2 model and matched by cosine similarity to the nearest labeled example. It generalizes past the exact wording the rules require — and every human correction is stored as a new neighbor.",
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
      "The only trained model in the stack: a SetFit few-shot classifier, contrastively fine-tuned on paraphrase-MiniLM-L6-v2 from 5–10 examples per category. It is the learned call for the genuinely ambiguous email — and the model that ships to the browser.",
  },
] as const;

/** Per-layer accept thresholds — the cascade's fallthrough rule. */
export const THRESHOLDS = {
  rules: "0.90",
  embeddings: "0.85",
  setfit: "0.70",
  gate: "0.85",
  source: "source · hybrid.py:123–124, 248, 333 · config.py:208–212",
} as const;

// ---------------------------------------------------------------------------
// The 9 categories — 8 model-predicted + needs_review (human-review bucket).
// Rule counts from ml/browser/site/rules.json (sum = 201).
// ---------------------------------------------------------------------------

export const CATEGORIES = [
  { id: "applied", label: "applied", rules: 36, predicted: true, gloss: "confirmation your application landed." },
  { id: "pending_application", label: "pending_application", rules: 21, predicted: true, gloss: "saved / in-progress, not yet submitted." },
  { id: "interview", label: "interview", rules: 39, predicted: true, gloss: "a recruiter wants to talk." },
  { id: "rejection", label: "rejection", rules: 34, predicted: true, gloss: "“we’ve decided to move forward with…”" },
  { id: "offer", label: "offer", rules: 32, predicted: true, gloss: "the email you were waiting for." },
  { id: "assessment", label: "assessment", rules: 21, predicted: true, gloss: "a take-home or coding screen." },
  { id: "follow_up", label: "follow_up", rules: 18, predicted: true, gloss: "nudges, scheduling, status pings." },
  { id: "other", label: "other", rules: 0, predicted: true, gloss: "not job-related — filtered out." },
  { id: "needs_review", label: "needs_review", rules: 0, predicted: false, gloss: "below the gate — routed to a human." },
] as const;

export const CATEGORIES_META = {
  total: 9,
  predicted: 8,
  ruleTotal: 201,
  ruleCategories: 7,
  note: "8 categories are model-predicted; needs_review is a routing bucket, not a trained label — it is the confidence gate's output.",
  source: "source · database/models.py:94–105 · rules.json (201 patterns / 7 categories)",
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
      "The order is deliberate: a free, deterministic regex is tried before a 384-dimension embedding lookup, which is tried before the trained SetFit head. Most email is decided by the cheap layers; only the genuinely ambiguous message reaches the model — and only a confident model auto-files.",
    steps: [
      { n: "1", label: "Rules", detail: "regex + ATS domains", accept: "≥ 0.90", accentKey: "02_HOW" },
      { n: "2", label: "e5 similarity", detail: "cosine 1-NN", accept: "≥ 0.85", accentKey: "03_INSIDE" },
      { n: "3", label: "SetFit head", detail: "few-shot learned", accept: "≥ 0.70", accentKey: "04_PROOF" },
      { n: "◇", label: "Gate", detail: "human review", accept: "< 0.85", accentKey: "01_WHY" },
    ],
    source: "source · classifier/hybrid.py:210–474 (classify order + thresholds)",
  },

  // Per-layer detail pages pull from LAYERS + THRESHOLDS above.
  rules: {
    eyebrow: "§02 · LAYER 1",
    headline: "201 rules that never guess.",
    body: [
      "The first layer is 201 regular expressions across seven outcome categories, plus 14 known applicant-tracking-system sender domains. It is free, instant, and completely auditable — you can read exactly why any email was filed.",
      "Rules only auto-accept above 0.90 confidence. A rule that is merely plausible defers to the layers below rather than risk a wrong, silent file.",
    ],
    stat: { value: "201", label: "regex patterns · 7 categories" },
    stat2: { value: "0.90", label: "auto-accept threshold" },
    note: "A regex is a promise you can inspect. That is why it goes first.",
  },
  embeddings: {
    eyebrow: "§02 · LAYER 2",
    headline: "Similarity, not exact words.",
    body: [
      "When no rule is sure, the email is embedded with a pretrained e5-small-v2 model (384 dimensions) and matched by cosine similarity to the nearest labeled example. It catches the rejection that never says “rejected”.",
      "The e5 weights are used off the shelf — not fine-tuned. The layer “learns” by growing its neighbor set: every human correction becomes a new labeled example the next lookup can match against.",
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
      "It is the learned call for the genuinely ambiguous email, and the only trained model in the stack. This is the body that gets exported to ONNX and shipped to the browser.",
    ],
    stat: { value: "5–10", label: "examples / category (few-shot)" },
    stat2: { value: "0.70", label: "accept threshold" },
    note: "MiniLM-L6, not e5 — verified against the model card, not the marketing.",
  },

  gate: {
    eyebrow: "§02 · THE GATE",
    headline: "Below 0.85, a human decides.",
    lede:
      "The cascade never auto-files a guess. A single confidence gate at 0.85 separates “file it” from “ask a person”.",
    body:
      "Clear the gate and JobTracker files the email under its predicted category. Fall short and it lands in a review queue as needs_review — nothing is written, and the human’s correction becomes new SetFit training data. The gate is why a wrong label is rare and a silent wrong label is rarer.",
    bands: [
      { range: "≥ 0.85", verb: "AUTO-FILE", tone: "setfit", detail: "confident — filed under its category." },
      { range: "0.70 – 0.84", verb: "FLAG", tone: "gate", detail: "uncertain — queued for a human." },
      { range: "< 0.70", verb: "FALL BACK", tone: "danger", detail: "no confident layer — needs_review." },
    ],
    loopNote:
      "Every correction below the gate is captured as training data → the SetFit head retrains → the gate is crossed unaided next time.",
    source: "source · classification.py:25, 512–559 (review queue) · hybrid.py:301–474",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 03 — INSIDE
// ---------------------------------------------------------------------------

export const INSIDE = {
  divider: { subtitle: "the engine room — and the model that fits in a browser tab" },

  architecture: {
    eyebrow: "§03 · ARCHITECTURE",
    headline: "One pipeline, one feedback loop.",
    body:
      "The classifier is a hybrid pipeline in backend/jobtracker/classifier: a content guard, then rules, then embedding similarity, then SetFit, then a fallback that is always safe (needs_review rather than a wrong guess). Corrections write to training_data; embeddings persist in email_embeddings; SetFit retrains once enough data accrues.",
    flow: [
      { stage: "guard", detail: "force non-job → other" },
      { stage: "rules", detail: "201 regex · ≥ 0.90" },
      { stage: "e5", detail: "cosine 1-NN · ≥ 0.85" },
      { stage: "setfit", detail: "few-shot · ≥ 0.70" },
      { stage: "gate", detail: "0.85 → auto / human" },
      { stage: "learn", detail: "correction → retrain" },
    ],
    source: "source · classifier/hybrid.py · docs/ARCHITECTURE.md:36–60",
  },

  onnx: {
    eyebrow: "§03 · THE EXPORT",
    headline: "90 megabytes down to 23.",
    lede:
      "The fine-tuned SetFit body is exported to ONNX and dynamically quantized to int8 — the weights drop from float32 to 8-bit integers with no accuracy floor breached.",
    body:
      "The full-precision ONNX graph is 90.4 MB. Dynamic int8 quantization compresses it roughly four-fold to 22.8 MB — small enough to download once and run on a laptop’s CPU, in a browser tab, with no GPU and no backend.",
    before: { value: "90.4 MB", label: "float32 ONNX" },
    after: { value: "22.8 MB", label: "int8 quantized" },
    ratio: "≈ 4× smaller",
    exact: "22,843,695 bytes",
    source: "source · ml/browser/export_onnx.py · ls -la model_quantized.onnx",
  },

  browser: {
    eyebrow: "§03 · ZERO SERVERS",
    headline: "It runs in your browser.",
    body: [
      "The quantized model is loaded by Transformers.js (3.5.2) over onnxruntime-web, executing in WebAssembly on the client. allowRemoteModels is false and the model path is local — the tab fetches the weights once and never phones home.",
      "There is no inference server, no per-request cost, and no data leaving the page. The classifier the desktop app runs in Python, the web app runs on your own CPU.",
    ],
    facts: [
      { k: "RUNTIME", v: "Transformers.js 3.5.2 · onnxruntime-web (WASM)" },
      { k: "SERVERS", v: "zero · client-side inference only" },
      { k: "MODEL", v: "int8 ONNX · 22.8 MB · fetched once" },
      { k: "PRIVACY", v: "allowRemoteModels = false · nothing leaves the tab" },
    ],
    parity: {
      claim: "6 / 6",
      label: "output-agreement suite vs the Python pipeline",
      honest:
        "Stated on the model card and landing page (app.js:12) as a code-verified claim; there is no committed automated parity test in the repo — so we print it as documented, not as a benchmark we re-ran.",
    },
    source: "source · ml/browser/site/app.js:12–19 · index.html",
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
    heroLabel: "macro-F1 · hybrid classifier v3",
    body:
      "Macro-F1 averages the per-class F1 so no category can hide behind the frequent ones. On the held-out evaluation the hybrid classifier scores 0.9791 — accuracy 0.9792, two emails misclassified. It is not a cherry-picked accuracy headline; it is the metric that punishes a weak class.",
    exact: "0.9791304 macro-F1 · 0.9792 accuracy · 2 misclassified",
    ciValue: "0.95",
    ciLabel: "CI floor — the merge blocks below it",
    ciBody:
      "The score is not a one-time screenshot. Two GitHub Actions gates re-run the evaluation on every backend change and fail the build if macro-F1 drops below 0.95. The number is load-bearing.",
    source: "source · baseline_hybrid_v3.json:115 · backend-ci.yml:72,84 (--min-macro-f1 0.95)",
  },

  classes: {
    eyebrow: "§04 · THE TAXONOMY",
    headline: "Nine categories, eight learned.",
    lede:
      "The classifier files into nine categories. Eight are model-predicted outcomes; the ninth, needs_review, is not a label the model emits — it is where the confidence gate sends everything it is not sure about.",
    note: "needs_review is the gate’s output, not a trained class — which is the whole safety story in one row.",
    source: "source · database/models.py:94–105",
  },

  trace: {
    eyebrow: "§04 · THE DECISION TRACE",
    headline: "Every verdict, traced.",
    lede:
      "The signature JobTracker visual: each email’s path through the three layers and the gate. The layer that fired lights in its own hue; earlier layers passed it on, later layers were never needed. Confidence is drawn against the 0.85 gate.",
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
    headline: "182 tests and a gate that blocks merges.",
    body:
      "Correctness is not asserted, it is enforced. The backend ships a 182-test suite; two CI gates re-run the classifier evaluation on every change and refuse to merge if macro-F1 falls below 0.95. Below the confidence gate at runtime, the same conservatism applies — the model hands off to a human rather than file a guess.",
    stats: [
      { value: "182", label: "tests · backend suite", note: "README.md:7" },
      { value: "2", label: "CI gates · rules + hybrid", note: "backend-ci.yml" },
      { value: "0.95", label: "macro-F1 merge floor", note: "--min-macro-f1" },
    ],
    honest:
      "Honesty note: the repo README states 182 tests; a static count of the current tree is ~186 backend test functions. We print the documented figure.",
    handoffQuote:
      "A classifier that knows when to stop is worth more than one that is always sure.",
  },
} as const;

// ---------------------------------------------------------------------------
// Section 05 — BUILD
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
      "The registered body is exported to int8 ONNX, published to a Hugging Face Space, and served by the Next.js 16 web app on Vercel — inference on the client.",
    stages: [
      { n: "1", label: "TRAIN", detail: "SetFit · MiniLM-L6 body", accentKey: "04_PROOF" },
      { n: "2", label: "MLflow", detail: "log + register · gate 0.95", accentKey: "05_BUILD" },
      { n: "3", label: "ONNX", detail: "export · int8 · 22.8 MB", accentKey: "03_INSIDE" },
      { n: "4", label: "HF SPACE", detail: "static · in-browser", accentKey: "02_HOW" },
      { n: "5", label: "WEB", detail: "Next.js 16 · Vercel", accentKey: "01_WHY" },
    ],
    registry:
      "MLflow model “jobtracker-hybrid-classifier” · alias “production” set only past the 0.95 macro-F1 floor.",
    source: "source · ml/track_run.py:31,111–120 · ml/browser/export_onnx.py",
  },

  stack: {
    eyebrow: "§05 · THE STACK",
    headline: "What it is built on.",
    lede:
      "A native macOS app and a FastAPI backend where the model was born; a Next.js 16 web app and a portable ONNX model where it ships.",
    rows: [
      { area: "WEB", tech: "Next.js 16.2.4 · React 19 · Vercel", note: "the hosted product + live demo" },
      { area: "IN-BROWSER ML", tech: "Transformers.js 3.5.2 · onnxruntime-web", note: "int8 ONNX on the client, no server" },
      { area: "CLASSIFIER", tech: "e5-small-v2 · SetFit / MiniLM-L6 · 201 regex", note: "the 3-layer hybrid cascade" },
      { area: "TRAINING", tech: "MLflow registry · CI-gated ≥ 0.95", note: "log, register, promote to production" },
      { area: "BACKEND", tech: "FastAPI · SQLModel · SQLite", note: "sync, classify, review queue" },
      { area: "DESKTOP", tech: "SwiftUI macOS app", note: "the original native client" },
    ],
    source: "source · apps/web/package.json:24 · ml/track_run.py · pyproject.toml",
  },

  closing: {
    eyebrow: "END",
    headline: "Try it.",
    tagline: "Run a real email through all three layers, past the gate, in your browser.",
    liveLabel: "LIVE WEB APP",
    liveUrl: "jobtracker-web-five.vercel.app",
    spaceLabel: "IN-BROWSER CLASSIFIER",
    spaceUrl: "hf.co/spaces/yadava5/jobtracker-classifier",
    leftArrowLabel: "open it",
    rightArrowLabel: "classify",
    microNote: "three layers · one gate · zero servers",
  },
} as const;

// ---------------------------------------------------------------------------
// Back cover
// ---------------------------------------------------------------------------

export const BACK_COVER = {
  qrTarget: "https://jobtracker-web-five.vercel.app",
  qrCaption: "scan to open the live web app",
  spaceNote: "In-browser classifier (int8 ONNX, zero servers): hf.co/spaces/yadava5/jobtracker-classifier",
  colophon: ["JobTracker", "System Card · Vol. 01", "Ayush Yadav · 2026"],
  closingLine: "— The verdict was always in the inbox.",
} as const;
