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

/**
 * The window act's narration — one line per scene, pinned above the frame and
 * swapped as the visitor's scroll advances the board beneath it (`WindowAct`).
 *
 * These exist because the act's first scene was WORDLESS: two thirds of a
 * viewport of a resting board, whose whole point (Larkspur, nineteen days
 * quiet, the amber age tag) is invisible to a visitor who does not yet know
 * the product's grammar. The scene the page bets on cannot be the one screen
 * with nothing to read on it, so `landing-variants.test.mjs` holds the count
 * at three non-empty lines against the act's three sentinels.
 *
 * State, event, consequence — the act's whole argument in three lines.
 */
export const ACT = {
  captions: [
    "The board, nineteen days after you stopped updating it.",
    "The reply lands, and the row moves without you.",
    "The row opens on the mail that moved it.",
  ],
  /**
   * Scene 0, revisited. The camera returns when the reader scrolls back up but
   * the verdict does not un-happen (see MarketingBoard), so the opening line
   * would be sitting over a board whose detail pane is showing Larkspur
   * already rejected — the one place the narration could contradict the thing
   * it narrates. This is what scene 0 says the second time.
   */
  settled: "The same board, with the verdict already filed.",
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
  /** Takeout is prepared asynchronously — Google mails the archive back, and
   *  that can take hours. The old line promised "today", which is the one
   *  sentence on the page a visitor could catch out at the moment of highest
   *  intent, so it states the wait instead of hiding it. */
  noSeat:
    "No seat? Run it on your own exported mail instead — ask Google for a Takeout .mbox, and when the archive lands in your inbox, drop it in: it is parsed and classified in your browser. Nothing uploads.",
  cta: "Classify your exported mail",
  aside: "or ask for a seat:",
  contact: "aesh.03.23@gmail.com",
} as const;

/**
 * Landing B's closing act (`ClosingAct.tsx`). The thesis is the brand
 * sentence the logo already encodes (components/brand/Logo.tsx); the CTAs
 * restate ACCESS with the seat ask made primary — the close is where the ask
 * carries weight — and "nothing uploads" is ACCESS.noSeat's own promise.
 * The rail label composes DECISION.rulesF1 in the component, so the number
 * stays single-sourced. No new claim.
 */
export const CLOSING = {
  thesis: "Your inbox already holds the verdict.",
  seatCta: "Ask for a seat",
  importAside: "or classify your exported mail — nothing uploads",
  replay: "Replay ↺",
} as const;

/**
 * The descent's claim screens. One claim per screen; the email artifact beside
 * them is `VerdictEmail`, whose classifications are computed live in the tab by
 * the shipped rules layer (`lib/demo/rulesLayer.ts`).
 *
 * `verdict` was two claims — "the verdict arrives buried" and "the whole body
 * gets read" — cause and effect, split across two screens. A reader who left
 * after the first took away the problem and none of the answer, so they are one
 * claim now. What they must NOT become is one static diagram: the exhibit's
 * power is sequential, and the reader has to feel the preview end before the
 * sentence that matters before the two verdicts disagree. So the merged claim
 * keeps TWO artifact micro-beats — `raw`, then `split` — under one headline,
 * the shape `WindowAct` already uses (see `ClaimsDescent`'s STAGES).
 */
export const CLAIMS = {
  verdict: {
    eyebrow: "What it reads",
    headline: "The preview ends before the verdict. Applied reads past it.",
    /** Micro-beat one: the mail as Gmail hands it over. */
    raw:
      "A rejection spends its first two hundred characters being polite. Gmail's preview — all most tools ever see — ends before the sentence that matters.",
    /** Micro-beat two: the same body, run twice. "So" carries the cause across
     *  the screen break, because this paragraph has no headline of its own. */
    split:
      "So the shipped rules layer runs on it twice, live in your tab: once on the preview alone, once on the whole body. The preview reads as a confirmation. The body tells the truth.",
  },
} as const;

/**
 * Wall labels for the descent's travelling exhibit — sentinel index → what the
 * artifact is showing right now. Parallel to `ClaimsDescent`'s STAGES, and the
 * same device as the window act's captions: an exhibit that changes state
 * under the reader deserves to say what state it is in.
 */
export const ARTIFACT = {
  labels: [
    "The email, as Gmail hands it over",
    "The same body, classified twice",
    "Both verdicts, from the rules layer that ships",
    "The same email, as the database keeps it",
  ],
} as const;
