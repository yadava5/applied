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

/**
 * The register here is deliberate and it is NOT convenience. The previous
 * headline ("Never update a job tracker again.") sold tidiness to someone who
 * has not yet decided they have a problem. The person this page is for has
 * sent two hundred applications and is afraid of exactly one thing: that a
 * reply already landed and they missed it. Name that, or the page is a
 * to-do-list ad.
 *
 * The urgency has to come from the mechanism, never from a statistic. There is
 * no sourced number for "how many candidates miss a reply", so none appears
 * here — a fabricated one would fail the same honesty bar the DECISION block
 * is held to.
 *
 * Both privacy sentences are load-bearing and both are auditable:
 *   · "No AI reads your mail" — classification is the deterministic rules
 *     stage; no message content reaches a language model.
 *   · "never storing the message body" — RETENTION, not request. Bodies are
 *     fetched in flight and discarded; test_body_is_never_persisted.py is the
 *     gate, and production carries 0 populated `body_text`/`body_html` columns.
 *
 * Two weaker phrasings are FALSE and must not come back. Both were shipped
 * here once, so this note exists to stop the third derivation:
 *   · "Your emails are never stored" — metadata is stored.
 *   · "without ever storing its text" — a ~200-char excerpt IS stored.
 *     `emails.body_snippet` is Gmail's own snippet (`ref.snippet`, capped at
 *     500 in applications.py:1182/1205/2569; observed max 201, avg 189 over 54
 *     production rows), and a user correction copies it into
 *     `training_data.body_text` (11 of 11 populated). The word that carries the
 *     claim is BODY. "Text" silently widens it into a lie.
 * The honest long form is the privacy page's, and it is the house vocabulary:
 * "sender, subject, date, snippet and the classification" (lib/applications/
 * export.ts:211). Say body, never text.
 */
export const HERO = {
  /** 7 words. The loss, not the chore, is the subject. */
  headline: "You don't lose the offer. You lose the email.",
  /**
   * Length is a LAYOUT constraint here, not a taste one. Measured on a
   * production build: at 1024×600 the rewritten hero pushed `pipeline-board`
   * to 607.5px, 7.5px under the fold — zero board pixels visible, which kills
   * the page's whole argument. Subhead line-height is 28px; cutting one line
   * moved board top to 579.5px, i.e. 20.5px inside a 600px viewport.
   *
   * This string renders at THREE lines / 84px at 1024, measured on the
   * production build — not two, as an earlier version of this note claimed.
   * Do not budget headroom from that wrong number.
   *
   * 20.5px is a sliver: the summary strip's labels are clipped and NO
   * application row renders. Reaching the whole strip needs another 34px, and
   * one full row another 113.3px — the latter is not reachable by trimming
   * this subhead, so it is a layout change, not a copy change. Re-measure on
   * `next build && next start` if you touch this; `next dev` cannot measure it.
   */
  subhead:
    "An interview invite lands at 2am, under sixty other things, and never surfaces again. Applied moves the row for you — no AI reads your mail, and the message body is never stored.",
} as const;

/** The board embed's provenance line — shown with every live mount. */
export const BOARD = {
  live: "Live fixture data — the shipped board, not a video. Drag a card; open a row.",
  /** The window act's variant of the same honesty line: the take drives the
   *  board with a synthesized pointer, and that has to be declared in the
   *  same breath as "not a video" — while the visitor's own hand still wins
   *  (the components stay real and interactive under the take). */
  take: "Live fixture data — the shipped board, a synthesized pointer. Your hand wins: drag a card, open a row.",
  still: "A still of the board. The interactive board needs a wider screen.",
  open: "Open the full demo",
} as const;

/**
 * The window act's words — the narration strip pinned above the frame. The
 * principle survives from the scrubbed act these replaced: no beat of the
 * act is wordless, because a visitor who does not yet know the product's
 * grammar cannot see what the board is showing them until a line names it.
 * `landing-variants.test.mjs` holds every line non-empty and rendered.
 */
export const ACT = {
  /**
   * The workday oner's narration — the owner's 01a pick (2026-08-19), ported
   * with the take from the motion lab it was chosen in. One continuous
   * working session: the pointer opens the pulse's momentum panel, presses a
   * real filed-on-a-date day bar, the board narrows with its own glide,
   * Kestrel's row opens, the pane docks with the mail trail, the filter
   * clears, the camera returns. Every line lands with the beat it narrates
   * (`WindowAct` hands them to the director's `say`), and the camera follows
   * the READING, not the pointer.
   *
   * This replaces the three scroll-scene captions of the scrubbed act: the
   * act plays on its own pausable clock now (the closing act's mechanism,
   * the owner's call in both places), so captions indexed to scroll
   * sentinels described a machine that no longer exists.
   */
  opening:
    "A continuous working session — filter to a day, open a row, read its history, clear.",
  narration: [
    "Monday. The whole search in one frame — ask it what happened.",
    "The pulse holds the answer: filings, day by day.",
    "Press the heavy evening —",
    "— and the board narrows to the applications filed that day.",
    "Open one: the assessment, its deadline, and every mail that led here.",
    "Clear the day —",
    "— and the whole board breathes back. One sitting, no tab-hopping.",
  ],
  /** A take that cannot find its target must say so, not half-play. */
  failed: "The take could not finish here — replay to run it again.",
  /** The visitor's hand on the stage stands the take down (their events are
   *  trusted; the pointer's are synthesized) and the camera goes home, where
   *  the whole board — and anything they open on it — is in frame. */
  yours: "Your hand — the board is yours. Replay runs the take again.",
  /** The reduced-motion strip: the take stands down entirely and the resting
   *  board — still the live product — is the whole exhibit. */
  resting:
    "Motion is off — your setting is respected, and the board below is the live product at rest.",
  pause: "Pause",
  play: "Play",
  replay: "Replay",
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
  /**
   * The enforcement sentence, and the one place on this page a visitor could
   * catch the product out — so it states the SCOPE of the check rather than
   * implying there is none.
   *
   * It used to end "— on every commit", which #338's own audit then documented
   * as false: the workflow that runs this test is path-filtered to `backend/`,
   * the repo has no branch protection, and editing the privacy copy runs
   * nothing. All three were true when the sentence was written; none of them
   * made it true. A claim about a gate is a claim about when the gate fires.
   *
   * The scan's reach is the widened one #338 shipped — every column of every
   * table, every log record, and every response it touches, `GET /gmail/inbox`
   * included, which was the one response the file never checked despite being
   * the handler that does the reading.
   */
  mechanism:
    "That is a claim about code, so code enforces it: a test runs a scan whose message bodies carry a marker string, and fails if the marker reaches any column of any table, any log record, or any response the scan touches — the inbox endpoint that does the reading included. It runs in CI on every change to the backend.",
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
  aside: "or",
  /** The seat ask is a product action, not a `mailto:`.
   *
   *  It used to be the owner's personal Gmail, rendered on all three landings
   *  and again as the closing act's PRIMARY call to action. A raw address on
   *  a public marketing page is a spam magnet, it does not scale past one
   *  inbox, and it is the single loudest "this is somebody's side project"
   *  signal a landing can carry — the same reason the footer's byline and
   *  address were cut on 2026-08-19.
   *
   *  `/signup` is the honest destination rather than a stand-in: `cap` above
   *  already states that the seats "are invited one at a time", so the
   *  account list IS the queue, and a new account reaches the beta-capacity
   *  notice on /settings which states the cap and offers the import path.
   *  Nothing new is stored to make this true and no claim is added.
   *
   *  This deliberately stays a single constant so the domain cutover is one
   *  edit: when getapplied.dev lands, a `seats@` address (or a real waitlist
   *  form) replaces this href in one place, not at three call sites.
   *
   *  NOT the only surface carrying the address — `app/(app)/privacy` keeps it
   *  because Google's OAuth verification reads a contact off the privacy
   *  policy, and `components/beta/constants.ts` still composes a beta request
   *  from the site-wide pill. Neither is this page's copy. */
  seatLink: "ask for a seat",
  seatHref: "/signup",
} as const;

/**
 * Landing B's closing act (`ClosingAct.tsx`). The thesis is the brand
 * sentence the logo already encodes (components/brand/Logo.tsx); the CTAs
 * restate ACCESS with the seat ask made primary — the close is where the ask
 * carries weight — and "nothing uploads" is ACCESS.noSeat's own promise.
 * The rail labels compose DECISION.rulesF1 / DECISION.cascadeF1 in the
 * component, so the numbers stay single-sourced. No new claim.
 *
 * `rail*` are the scene's key: the one cyan rail the envelope crosses and the
 * two dashed ghosts it passes through. They were literals inside the svg
 * until they were measured at 3.1–3.3px there (uniform viewBox scaling makes
 * every in-scene size a function of the viewport), and the words moved out to
 * real DOM text — so they are copy now, and copy lives here. Sentence case:
 * the caps are a CSS treatment, which DOM text can carry reliably.
 */
export const CLOSING = {
  thesis: "Your inbox already holds the verdict.",
  seatCta: "Ask for a seat",
  importAside: "or classify your exported mail — nothing uploads",
  replay: "Replay ↺",
  railShips: "what ships",
  railGhost: "benchmarked, not shipped",
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
    /**
     * Micro-beat one: the mail as Gmail hands it over. The exhibit is an
     * INTERVIEW INVITATION, not a rejection — the owner's call (2026-08-16):
     * the landing carries no rejection anywhere, and the invitation is the
     * larger loss anyway, because what the preview hides here is the
     * opportunity itself. The split is computed live and was verified to
     * reproduce against the post-#356 rules before this copy was written:
     * preview → applied, whole body → interview.
     */
    raw:
      "An interview invitation spends its first two hundred characters being polite. Gmail's preview — all most tools ever see — ends right where the inviting begins.",
    /** Micro-beat two: the same body, run twice. "So" carries the cause across
     *  the screen break, because this paragraph has no headline of its own. */
    split:
      "So the shipped rules layer runs on it twice, live in your tab: once on the preview alone, once on the whole body. The preview reads as a routine acknowledgment. The body holds the invitation.",
    /**
     * The words around `VerdictTally` — the figure that fills micro-beat two's
     * claim column with the arithmetic behind the two chips beside it. Words
     * only: every number in the figure is a score the engine computed in the
     * visitor's tab, from the same two calls the chips print, so nothing here
     * may state one.
     */
    tallyLabel: "The tally behind each verdict",
    tallyPreview: "preview only",
    tallyBody: "whole body",
    tallyNote:
      "Same engine, same weights, both runs — only the text differs. A pattern can only score on text its run can see, and the winner's score with its margin over the runner-up sets the confidence.",
  },
} as const;

/**
 * The words around the product recordings the page plays (`ProductClip`).
 *
 * THREE ARE PLACED, and the test each one had to pass is that the paragraph
 * beside it already says what the frames say, without the reader being told:
 *
 *   · `rules-read-the-body` against the decision claim — the layer that ships,
 *     answering a body on its own;
 *   · `board-syncs` against the retention claim's first sentence, "the
 *     classifier reads a message's body to decide, then discards it". The clip
 *     is the READING — a pass of mail going in — and the exhibit beneath it is
 *     what comes out. Two halves of one sentence, in two media;
 *   · `import-classifies` against the access claim — the page's second CTA,
 *     which promised "it is parsed and classified in your browser" and had no
 *     evidence anywhere.
 *
 * A FOURTH EXISTS AND IS DELIBERATELY NOT ON THE PAGE. `gmail-connects` is the
 * best privacy exhibit in the repository — Google's own consent screen stating
 * the single permission — and Google's screen names `jobtracker-api-seven.vercel.app`,
 * the host from before the JobTracker → Applied rename. On a page selling
 * Applied that reads as consent being granted to a different product, and the
 * only honest fixes are outside this file: rename the Google Cloud OAuth
 * client, then re-record. Cropping the host line out would leave Google
 * stating a permission with the grantee removed, which is worse than not
 * showing it. Do not place it until it has been re-recorded.
 *
 * `label` is the wall label, the same device the travelling exhibit uses. It
 * is not decoration: the board embed on this same page advertises itself as
 * "the shipped board, not a video" (`BOARD.live`), so anything that IS one
 * has to say so in the page's own voice, or that distinction quietly dies.
 */
export const FOOTAGE = {
  label: "Recorded in the app",
  /** The clip's own controls. Clips LOOP now, so the pair is play/pause — the
   *  action a reader actually has — rather than the old "Replay", which is the
   *  control for a recording that has stopped, and none of these stop. Pause is
   *  also the whole of the reduced-motion path, where nothing autoplays. */
  play: "Play",
  pause: "Pause",
  rules: {
    /**
     * The accessible name. A silent screen recording carries all of its
     * meaning in pixels, so it needs the same text equivalent an image does —
     * what happens, in order, not what it is called.
     */
    name:
      "Screen recording: a rejection body is typed into the classifier sandbox on Applied's demo page, and the rules layer re-scores it as the text arrives — the verdict moves from Other to Rejection, and the line beneath it changes from deferring to the neural layers to answering on its own.",
    /**
     * The caption does one job the label cannot: it scopes the numbers inside
     * the frame. The confidence in the recording is one email's, from the
     * accept bar the layer uses at read time; the figure directly above it is
     * a macro-F1 over a held-out set. A visitor who reads them as the same
     * quantity has been misled by the staging, not by the copy.
     */
    caption:
      "The classifier sandbox on the demo page, recorded there. The confidence beside the verdict is this one email's, scored live by the rules layer — not the benchmark above it.",
  },
  sync: {
    name:
      "Screen recording: one press of Sync on Applied's demo board. The counters at the head of the board rise as new mail is filed, the applied group's own count follows, and the status line beside them says how many messages the pass filed and how many it had already seen.",
    /**
     * Scoped, like the rules caption, and for the same reason: the counters in
     * the frame are the demo's fixture mailbox, not a claim about anyone's real
     * volume. What the clip is evidence FOR is the paragraph beside it — that a
     * pass reads mail — and the exhibit below it is what a read message leaves
     * behind. No number here: the frame states its own.
     */
    caption:
      "The demo board's own Sync, recorded there. The strip counts the pass — what it filed, and what it had already seen.",
  },
  import: {
    /** Re-recorded 2026-08-19 (the owner's call: the button take showed no
     *  process). The take is now the CTA's own sentence enacted — the export
     *  arrives over the drop zone as a real file, the zone answers, it
     *  lands, and the counters follow — so the words describe that arc. */
    name:
      "Screen recording: a sample mail export is dragged onto Applied's import page. The drop zone answers as the file arrives, the file lands, and under the on-device notice the counters appear — how many messages were scanned, how many were filed automatically and at what share, how many are held for review, and the format the file was read as.",
    /**
     * The caption's job is still the one thing a viewer might read as a
     * fault — there is no progress bar between the drop and the counters —
     * and it states that as the claim it is: the work happens in the tab the
     * moment the file lands, so there is no wait to watch. The old caption
     * apologised for a take that showed no arrival at all; the take shows
     * the arrival now, and the caption scopes what happens after it.
     */
    caption:
      "The import page, recorded on its public route. The export lands as a file and is read and classified the moment it arrives — in the tab, nothing uploaded, so there is no wait to watch.",
  },
} as const;

/**
 * Wall labels for the descent's travelling exhibit — sentinel index → what the
 * artifact is showing right now. Parallel to `ClaimsDescent`'s STAGES, and the
 * same device as the window act's captions: an exhibit that changes state
 * under the reader deserves to say what state it is in.
 */
export const ARTIFACT = {
  /** Index 2 is currently unrendered: the decision claim used to repeat the
   *  previous screen's `split` exhibit in a sticky column, and that column is
   *  gone (see `ClaimsDescent` — it was the measured dead space). The label is
   *  kept rather than deleted because the copy is right and the staging is
   *  what changed; nothing else in this file is indexed against it. */
  labels: [
    "The email, as Gmail hands it over",
    "The same body, classified twice",
    "Both verdicts, from the rules layer that ships",
    "The same email, as the database keeps it",
    /** The escalated exhibit's third beat (02b): the two honesty rails a
     *  dissolve needs, in one line — this happens to APPLIED'S copy (Gmail
     *  keeps the original), and what survives is the decision, not the
     *  correspondence. */
    "The mail dissolves — Applied's copy, never your Gmail's",
  ],
} as const;

/**
 * The held exhibit's wall labels (`HeldExhibit`, the decision rail — the
 * owner's 08c pick). The same device as the verdict rail's: the exhibit
 * changes state under the reader, so the label names the state. The GATE
 * itself is stated inside the exhibit by the product's own review queue
 * ("held because Applied wasn't sure · your decision files them") — these
 * lines stage it, they do not restate it.
 */
export const HELD = {
  mail: "A mail the rules will not guess about",
  queue: "It waits in the review queue — filed by you, never guessed",
} as const;
