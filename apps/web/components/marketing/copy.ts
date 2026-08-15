/**
 * The one source of copy for the three landing candidates (/landing-a, -b, -c).
 *
 * The variants differ in STAGING only — same claims, same numbers, same
 * sentences — so the choice between them is about composition, not content.
 * Keeping every shared string here is what makes that literally true, and it
 * gives `tests/unit/landing-variants.test.mjs` one file to hold the honesty
 * constraints against:
 *
 *   · 0.979 is the RULES stage, never the cascade. `baseline_hybrid_v3.json`
 *     is byte-identical to `baseline_rules_v3.json` (the deterministic profile
 *     disables SetFit), so the file named "hybrid" measured the regexes alone.
 *     The full cascade scored 0.958 on the same 96-email v3 set — and that
 *     comparison is the pitch, not a caveat: the benchmark chose what ships.
 *   · No pattern count appears anywhere. The repo currently holds three
 *     different numbers for that noun; a number that cannot be derived in a
 *     gate does not go on a marketing page.
 *   · The privacy claim is RETENTION, not request — the app fetches bodies as
 *     of 2026-08-14 and discards them, and
 *     backend/tests/test_body_is_never_persisted.py is the enforcement the
 *     copy names. See app/(app)/privacy/page.tsx for the full sourced version.
 */

export const HERO = {
  /** 6 words — the reference set's median. The reader is the subject. */
  headline: "Never update a job tracker again.",
  subhead:
    "Every application answers by email. Applied reads the verdict — interview, offer, rejection — and moves the board for you.",
} as const;

/** The board embed's provenance line — shown with every live mount. */
export const BOARD = {
  live: "Live fixture data — the shipped board, not a video. Drag a card; open a row.",
  still: "A still of the board. The interactive board needs a wider screen.",
  open: "Open the full demo",
} as const;

export const DECISION = {
  eyebrow: "How it decides",
  headline: "We benchmarked the neural cascade against the regexes. We shipped the regexes.",
  /** Attribution is load-bearing: rules stage, v3, 96 held-out emails. */
  rulesF1: "0.979",
  cascadeF1: "0.958",
  window: "macro-F1 · 96 held-out emails · v3 benchmark",
  rulesLabel: "rules stage — what ships",
  cascadeLabel: "full neural cascade",
  body:
    "Three layers exist — deterministic rules, e5 embeddings, a fine-tuned SetFit head. On the held-out set the rules alone beat the full cascade, so the rules are what classify your mail in the hosted app: inspectable, deterministic, fast. The neural layers run where they cost you nothing — in your own browser, on the demo and the import page.",
  gate:
    "The number is load-bearing: two CI gates re-run the benchmark on every backend change and fail the merge below 0.95 macro-F1.",
} as const;

export const PRIVACY = {
  eyebrow: "Privacy",
  headline: "Read in flight. Never kept.",
  scope:
    "Applied connects with one Google permission — gmail.readonly. It can read your mail; the grant carries no right to send, delete or change anything.",
  retention:
    "The classifier reads a message's body to decide, then discards it. No body is written to the database, returned by an endpoint, or logged. What is kept: a subject line, a sender, a date, Gmail's own short preview, and the verdict.",
  mechanism:
    "That is a claim about code, so code enforces it: a test runs a scan whose message bodies carry a marker string and fails if the marker reaches any stored column, the training table, or any response — on every commit.",
  /** The machine value the mechanism sentence names. Mono where rendered. */
  testPath: "backend/tests/test_body_is_never_persisted.py",
  systemCardLead: "The System Card is the full walkthrough behind that promise —",
  systemCardLink: "read it",
  policyLead: "and the privacy policy states what every sentence describes:",
  policyLink: "what Applied reads, and what it keeps",
} as const;

export const ACCESS = {
  eyebrow: "Access",
  headline: "One hundred seats.",
  cap:
    "Google caps an app awaiting verification at 100 Gmail accounts. Those are Applied's seats while the review runs, and they are invited one at a time.",
  noSeat:
    "No seat? Run it on your own exported mail today — drop a Google Takeout .mbox and it is parsed and classified in your browser. Nothing uploads.",
  cta: "Classify your exported mail",
  aside: "or ask for a seat:",
  contact: "aesh.03.23@gmail.com",
} as const;

/**
 * Variant C's claim screens — the descent. One claim per screen; the email
 * artifact beside them is `VerdictEmail`, whose classifications are computed
 * live in the tab by the shipped rules layer (`lib/demo/rulesLayer.ts`).
 */
export const CLAIMS = {
  arrives: {
    eyebrow: "What arrives",
    headline: "The verdict arrives buried.",
    body:
      "A rejection spends its first two hundred characters being polite. Gmail's preview — all most tools ever see — ends before the sentence that matters.",
  },
  reads: {
    eyebrow: "What reads it",
    headline: "The whole body gets read.",
    body:
      "The shipped rules layer classifies this email twice, live in your tab: once on the preview alone, once on the whole body. The preview reads as a confirmation. The body tells the truth.",
  },
} as const;
