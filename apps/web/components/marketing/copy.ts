/**
 * The one source of copy for the three landing candidates (/landing-a, -b, -c).
 *
 * The variants differ in STAGING only — same claims, same sentences — so the
 * choice between them is about composition, not content. Keeping every shared
 * string here is what makes that literally true, and it gives
 * `tests/unit/landing-variants.test.mjs` one file to hold the honesty
 * constraints against.
 *
 * TWO GATES RUN OVER THIS FILE, and both are mechanical rather than trusted,
 * because the hand-built censuses that preceded them each missed strings
 * (`tests/unit/landing-voice.test.mjs` says how they are derived):
 *
 *   · NO DASHES in any rendered string. An em or en dash reads as unedited
 *     machine output, and the three reference landings measured on 2026-08-21
 *     carry 0, 1 and 2 respectively. The fabricated recruiter mails are
 *     EXEMPT and must stay exempt — they are props imitating how companies
 *     write, and stripping their dashes makes them read as written by the
 *     same hand as the page. Comments in this file are repo docs, not
 *     rendered prose, and keep theirs.
 *   · NO INTERNALS. No architecture, no model names, no training or
 *     evaluation numbers, no CI thresholds, no score-shaped digits. See the
 *     block on `DECISION` for why the benchmark left this file entirely.
 *
 * The surviving honesty constraint from the benchmark era, which still binds
 * every sentence here:
 *
 *   · The privacy claim is RETENTION, not request — the app fetches bodies as
 *     of 2026-08-14 and discards them, and
 *     backend/tests/test_body_is_never_persisted.py is the enforcement the
 *     copy names. See app/(app)/privacy/page.tsx for the full sourced version.
 *
 * THE VOICE IS THE CLERK, and which grammatical subject holds a sentence is
 * itself the information:
 *
 *   · THE WORLD ACTS. "An interview invite lands at 2am." "The preview ends
 *     before the verdict." "Cedar's note commits to nothing." The mail is the
 *     protagonist and the source of every problem.
 *   · APPLIED DOES CLERICAL VERBS, present tense, active: reads, files,
 *     moves, holds, waits, asks, discards, keeps. Never cognition, never
 *     affect. "Guess" appears only negated. Applied is never a mind, and the
 *     reason is structural rather than stylistic: the page's central promise
 *     is that no mind reads your mail, so personifying it collapses the
 *     privacy story into a paradox.
 *   · YOU OWN the possessions and the decisions. "Your board." "Your decision
 *     files it."
 *
 * Two consequences a later editor should not "fix":
 *
 *   1. IMPERATIVE SECTION HEADINGS ARE REJECTED, despite all three reference
 *      landings using them. Commanding this reader assigns them work, and the
 *      entire pitch is that the work is done for them. Imperatives address
 *      the reader only for actions ON the page: drag a card, replay, ask for
 *      a seat.
 *   2. OPENING WITH A CATEGORY ASSERTION IS REJECTED. The references are
 *      category incumbents. Applied's category, "job tracker", is a commodity
 *      with a graveyard behind it, and leading with it files Applied under
 *      every tool the reader already abandoned. The pain-first hero is the
 *      considered exception, not an oversight.
 *
 * No "we", anywhere. Agentless passive only where the absence IS the claim
 * ("is never stored", "nothing uploads"). The page's signature shape is the
 * two-beat reversal ("You don't lose the offer. You lose the email."), at
 * most one per phase.
 *
 * `payoff` FIELDS ARE NEW (2026-08-21) and they are the point of the rewrite.
 * Every phase used to end on apparatus — computed in your tab, recorded on
 * the demo page, the record keeps that it was your decision — so the page
 * proved a great deal and never once said what any of it does for the
 * reader. Each `payoff` restates a capability the phase has ALREADY proven,
 * in outcome form. None of them may introduce a claim the phase has not
 * earned; that is the whole discipline of the field.
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
 * here.
 *
 * Both privacy sentences are load-bearing and both are auditable:
 *   · "No AI reads your mail" — classification is the deterministic path; no
 *     message content reaches a language model.
 *   · "the message body is never stored" — RETENTION, not request. Bodies are
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
   *
   * THE 2026-08-21 DASH SWEEP CHANGED ONE CHARACTER HERE, deliberately: the
   * dash before "no AI reads your mail" became a full stop, which is one
   * character SHORTER, so the measured three-line fit is unchanged rather
   * than re-argued. Nothing else in this string moved. The page's missing
   * category statement was considered for this slot and REJECTED on the same
   * budget: naming the category costs a fourth line, and a fourth line costs
   * every board pixel above the fold.
   */
  subhead:
    "An interview invite lands at 2am, under sixty other things, and never surfaces again. Applied moves the row for you. No AI reads your mail, and the message body is never stored.",
} as const;

/** The board embed's provenance line — shown with every live mount. */
export const BOARD = {
  /**
   * TRANSLATED, NOT DELETED, in the dash sweep. The first draft cut the
   * phrase disclosing that the board's data is fabricated, and the page's
   * honesty covenant hangs off exactly that distinction: the board is real
   * and the rows in it are not. "Sample data" carries it in two words.
   */
  live: "Sample data, the real board. Not a video: drag a card, open a row.",
  /** The window act's variant of the same honesty line: the take drives the
   *  board with a synthesized pointer, and that has to be declared in the
   *  same breath as "not a video" — while the visitor's own hand still wins
   *  (the components stay real and interactive under the take).
   *
   *  LENGTH IS A CONSTRAINT: this sits in a `truncate` span sharing a row
   *  with three transport controls, so a replacement that is longer than
   *  what it replaces gets clipped at 1024. This one is 48 characters
   *  against the old 58. */
  take: "Sample data, a synthetic pointer. Your hand wins.",
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
   * The 2026-08-21 recut plays at NATURAL SIZE throughout (the camera is a
   * scroll, never a zoom — `director.ts` says why), so no line here may
   * promise a composition only a zoom could make.
   *
   * TWO LINES USED TO BE ONE SENTENCE BROKEN OVER A DASH ("Press the heavy
   * evening —" / "— and the board narrows"). The sweep kept the
   * continuation and dropped the punctuation: a beat that opens on "And"
   * carries across the cut without a dash at either end. Do not restore the
   * dashes to "fix" the fragment; the fragment is the take's rhythm.
   */
  opening:
    "One continuous working session: filter to a day, open a row, read its history, clear.",
  narration: [
    "Monday. The whole search on one board. Ask it what happened.",
    "The pulse holds the answer: filings, day by day.",
    "Press the heavy evening.",
    "And the board narrows to the applications filed that day.",
    "Open one: the assessment, its deadline, and every mail that led here.",
    "Clear the day.",
    "And the whole board breathes back. One sitting, no tab-hopping.",
  ],
  /** A take that cannot find its target must say so, not half-play. */
  failed: "The take could not finish here. Replay to run it again.",
  /** The visitor's hand on the stage stands the take down (their events are
   *  trusted; the pointer's are synthesized) and the camera goes home, where
   *  the whole board — and anything they open on it — is in frame. */
  yours: "Your hand: the board is yours. Replay runs the take again.",
  /** The reduced-motion strip: the take stands down entirely and the resting
   *  board — still the live product — is the whole exhibit. */
  resting:
    "Motion is off, and the page respects that. The board below is the live product at rest.",
  pause: "Pause",
  play: "Play",
  replay: "Replay",
} as const;

/**
 * THE BENCHMARK LEFT THIS FILE ON 2026-08-21, and the deletion is the point
 * of the phase rather than damage to it. What used to stand here:
 *
 *   headline  "We benchmarked the neural cascade against the regexes. We
 *              shipped the regexes."
 *   body      "Three layers exist — deterministic rules, e5 embeddings, a
 *              fine-tuned SetFit head. …"
 *   rulesF1 / cascadeF1 / window / rulesLabel / cascadeLabel / gate
 *
 * That is an architecture, two model names, an evaluation method, a held-out
 * set size, two self-graded scores and a CI threshold, on the largest exhibit
 * of a product landing page.
 *
 * WHY IT WENT. Three landings were read on 2026-08-21 (vercel.com,
 * linear.app, claude.com) for how they actually handle numbers, and the rule
 * they follow is CHECKABLE-BY-OTHERS VERSUS GRADED-BY-SELF. Adoption,
 * customers and price are stated freely, including in the company's own voice
 * (Linear: "Linear powers over 40,000 product teams"). A figure grading the
 * product's own quality, in the company's own voice, appears on none of them;
 * Anthropic publishes hard benchmark numbers only inside attributed
 * third-party quotes. Applied has no customers to name, no adoption figure and
 * no third-party quotes, so it holds none of the sanctioned number types.
 *
 * The stronger argument does not need the comparison. Strip the supporting
 * cluster the trade-secret rule already bans — model names, the metric, the
 * set size, the threshold — and what is left is a bare 0.979 that cannot say
 * what it is a score OF. It either wears its lab coat, which is banned, or
 * stands naked as hype, which is also banned. And for this page's buyer the
 * figure reads NEGATIVE: a job seeker does not know what macro-F1 is, and
 * "96 held-out emails" reads as "they tested it on 96 emails".
 *
 * THE FIGURE IS NOT LOST. It keeps its home in the System Card, which the
 * privacy phase links from its own prose, and where the attribution that
 * makes it true has room to stand. Do not bring it back here without
 * bringing the attribution with it, and re-read this block first.
 *
 * WHAT REPLACES IT is a capability claim carrying no figure, and the
 * capability is the one the rail beside it records: Applied reads the whole
 * message and decides on what it says. `proof` points at the demo, where the
 * reader can hand it any mail they like and watch the verdict move. That is
 * a number the reader generates themselves, which is the only kind this page
 * is willing to show them.
 */
export const DECISION = {
  eyebrow: "How it decides",
  /** Not a two-beat reversal: the verdict phase above already spends the
   *  page's one-per-phase allowance on one, and two in adjacent phases turn
   *  a signature into a tic. Agentless passive, because the ABSENCE is the
   *  claim (nothing is filed on so little). */
  headline: "Nothing is filed on a subject line.",
  body:
    "A rejection can open like a thank you. An invitation can open like a formality. So Applied reads the whole message and decides on what it says, not on how it starts.",
  /** The phase's payoff. It restates what the phase has already proven, in
   *  the reader's terms: a board they can trust is a board whose moves they
   *  can account for. No new capability — the mail behind a row is the ROW
   *  phase's own exhibit, two phases down. */
  payoff: "So when a row moves on your board, you can see exactly what moved it.",
  /** Not an imperative: the reader is not commanded off the page. The demo is
   *  stated as a thing that exists and what it will do for them.
   *
   *  SCOPED TO THE SANDBOX, not to the demo page. "That same reading" is a
   *  sameness claim and it is true of exactly one component: the sandbox
   *  calls `classifyWithRules` (SampleInbox.tsx:277), the same module the
   *  landing's own `VerdictEmail` calls. The rest of the demo page shows
   *  precomputed verdicts and, further down, a layer visualiser. A draft of
   *  this line said "the demo page" and would have claimed sameness for all
   *  of it. */
  proof:
    "The sandbox on the demo page runs that same reading in your own browser, and you can hand it any mail you like.",
} as const;

export const PRIVACY = {
  eyebrow: "Privacy",
  headline: "Read in flight. Never kept.",
  scope:
    "Applied connects with one Google permission, gmail.readonly. It can read your mail; the grant carries no right to send, delete or change anything.",
  /** "Applied", not "the classifier". The page has one actor and it is the
   *  product; naming a component here is the same internals leak the
   *  DECISION block documents, in a quieter register. */
  retention:
    "Applied reads a message's body to decide, then discards it. No body is stored, sent back to your browser, or written to a log. What is kept: a subject line, a sender, a date, Gmail's own short preview, and the verdict.",
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
   *
   * THE 2026-08-21 SWEEP TRANSLATED THE JARGON AND KEPT THE SPECIFICITY,
   * which is the whole difficulty of this string: it is the page's
   * credibility core, and a version that reads more smoothly by naming less
   * is a downgrade, not an edit. "Any response the scan touches, the inbox
   * endpoint included" became "every response the app sends back, the one
   * that does the reading included" — same scope, no route names. "It runs
   * in CI on every change to the backend" became "every change to the part
   * of Applied that reads mail", which is the same path filter said in the
   * reader's vocabulary rather than the repository's.
   */
  mechanism:
    "That is a claim about code, so code enforces it. A test feeds Applied mail whose bodies carry a marker string, then hunts for that marker everywhere a body could have left a trace: every column of every table, every log record, and every response the app sends back, the one that does the reading included. If it turns up anywhere, the build fails. The check runs on every change to the part of Applied that reads mail.",
  /** The machine value the mechanism sentence names. Mono where rendered. */
  testPath: "backend/tests/test_body_is_never_persisted.py",
  /**
   * THESE TWO LEADS ARE CO-EDITED WITH THEIR JSX, and a string swap alone
   * will publish a broken sentence. Both `ClaimsDescent` (the landing) and
   * `sections.tsx` (/landing-a, /landing-c) render them as
   *
   *     {systemCardLead} <a>{systemCardLink}</a>. {policyLead} <a>{policyLink}</a>.
   *
   * The full stop after the first link lives in the JSX, which is why
   * `policyLead` is capitalised and why `systemCardLead` ends on a colon
   * rather than the dash it used to carry. Change one and change all four
   * sites, or the page ships a lowercase fragment after a full stop.
   */
  systemCardLead: "The System Card is the full walkthrough behind that promise:",
  systemCardLink: "read it",
  policyLead: "The privacy policy states what every sentence here describes:",
  policyLink: "what Applied reads, and what it keeps",
} as const;

export const ACCESS = {
  eyebrow: "Access",
  headline: "One hundred seats.",
  cap:
    "Google caps an app awaiting verification at 100 Gmail accounts. Those are Applied's seats while the review runs, and they are invited one at a time.",
  /** The ask's payoff, and the only one that may sit ABOVE its evidence:
   *  this phase's evidence is the whole page above it. Outcome form, no new
   *  claim — "the filing" is what every phase before this has just shown
   *  being done. */
  payoff: "A seat means the filing stops being your job.",
  /** Takeout is prepared asynchronously — Google mails the archive back, and
   *  that can take hours. The old line promised "today", which is the one
   *  sentence on the page a visitor could catch out at the moment of highest
   *  intent, so it states the wait instead of hiding it. */
  noSeat:
    "No seat? Run it on your own exported mail instead. Ask Google for a Takeout .mbox, and when the archive lands in your inbox, drop it in: it is read and filed in your browser. Nothing uploads.",
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
 *
 * `railShips` AND `railGhost` WERE DELETED ON 2026-08-21 with the benchmark
 * (see `DECISION`). They labelled the scene's two dashed ghost rails as
 * "benchmarked, not shipped" against the one solid rail's "what ships", and
 * composed `DECISION.rulesF1` / `cascadeF1` beside them — so the page's LAST
 * IMAGE was a restaging of the comparison the rest of the page had just
 * stopped making, with the two scores printed on it. The ghosts and the key
 * that named them are gone from the scene; the envelope now crosses one rail
 * and becomes the full stop, which is the arc the scene always drew and the
 * only one it needed.
 */
export const CLOSING = {
  thesis: "Your inbox already holds the verdict.",
  seatCta: "Ask for a seat",
  /** A colon, not the comma the first draft used: "or classify your exported
   *  mail, nothing uploads" is a comma splice, which is worse than the dash
   *  it was replacing. */
  importAside: "or classify your exported mail: nothing uploads",
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
    /**
     * Micro-beat one: the mail as Gmail hands it over. The exhibit is an
     * INTERVIEW INVITATION, not a rejection — the owner's call (2026-08-16):
     * the landing carries no rejection anywhere, and the invitation is the
     * larger loss anyway, because what the preview hides here is the
     * opportunity itself. The split is computed live and was verified to
     * reproduce against the post-#356 rules before this copy was written:
     * preview → applied, whole body → interview.
     *
     * THE CLAUSE "all most tools ever see" WAS RECAST in the sweep, and not
     * for the dash: it sets "all most" adjacent, which the eye reads as
     * "almost" and then has to re-parse. The replacement puts the same idea
     * at the end of the sentence where nothing collides with it.
     */
    raw:
      "An interview invitation spends its first two hundred characters being polite. Gmail's preview ends right where the inviting begins, and for most tools the preview is all there ever is.",
    /** Micro-beat two: the same body, run twice. "So" carries the cause across
     *  the screen break, because this paragraph has no headline of its own. */
    split:
      "So Applied reads it twice, live in your tab: once on the preview alone, once on the whole body. The preview reads as a routine acknowledgment. The body holds the invitation.",
    /**
     * THE PAGE'S MOST IMPORTANT PAYOFF LINE. It converts the page's best
     * proof — the live disagreement between preview and body, computed in
     * the reader's own tab — into the reader's own stakes, and it closes
     * back onto the hero's "under sixty other things". If only one payoff
     * line ever ships, it is this one.
     */
    payoff: "So the invitation surfaces on your board instead of under sixty other things.",
    /**
     * The words around `VerdictTally` — the figure that fills micro-beat two's
     * claim column with the arithmetic behind the two chips beside it. Words
     * only: every number in the figure is a score the engine computed in the
     * visitor's tab, from the same two calls the chips print, so nothing here
     * may state one.
     *
     * THESE SCORES SURVIVED THE BENCHMARK DELETION ON PURPOSE, and the
     * distinction is the one `DECISION` derives: a macro-F1 is the product
     * grading itself and the reader cannot check it, while these are worked
     * out from the mail in front of them, in their own browser, and change
     * if the mail changes. Checkable-by-others is the test, not
     * "is it a digit".
     */
    tallyLabel: "The tally behind each verdict",
    tallyPreview: "preview only",
    tallyBody: "whole body",
    tallyNote:
      "Two readings of one mail, and only the text differs. A phrase can only count toward a verdict if the reading can see it, which is why these two columns do not agree.",
  },
} as const;

/**
 * The words around the product recordings the page plays (`ProductClip`).
 *
 * TWO ARE PLACED, and the test each one had to pass is that the paragraph
 * beside it already says what the frames say, without the reader being told:
 *
 *   · `rules-read-the-body` against the decision claim — the reading that
 *     ships, answering a body on its own;
 *   · `board-syncs` against the retention claim's first sentence, "Applied
 *     reads a message's body to decide, then discards it". The clip is the
 *     READING — a pass of mail going in — and the exhibit beneath it is what
 *     comes out. Two halves of one sentence, in two media.
 *
 * THERE WERE THREE. `import-classifies` argued the access claim — the page's
 * second CTA, which promises "it is parsed and classified in your browser" —
 * and the owner retired it on 2026-08-20: the take never showed the file
 * being chosen, and what it did show went past too fast to read. Its words
 * came out of this file with it, because a caption for a clip nobody can
 * watch is a claim with nothing behind it. The access phase carries the ask
 * without an exhibit now (`AccessPhase`), and putting one back means
 * recording the import path properly, not re-cutting this take.
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
 * "the real board" and "not a video" (`BOARD.live`), so anything that IS one
 * has to say so in the page's own voice, or that distinction quietly dies.
 *
 * ONE CLIP WAS RE-RECORDED FOR THE COPY SWEEP, which is the only reason a
 * copy pass touched a video file. `rules-read-the-body` shows the demo
 * sandbox, and the sandbox's own status line read "below 0.90 — the full
 * pipeline would defer to e5 / SetFit". Two model names, a threshold and a
 * dash, rendered INSIDE the page's largest exhibit, where no edit to this
 * file could reach them: the whole sweep would have gone green with the
 * internals still on screen. `components/demo/SampleInbox.tsx` now states
 * what the product does instead of how it is built, and the clip was
 * re-captured against it.
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
     * what happens, in order, not what it is called. Accessible names are
     * Applied's voice too: this one used to speak "the rules layer" and "the
     * neural layers" to every screen reader user, which is the internals leak
     * again in the one register nobody proofreads.
     *
     * It describes the RE-RECORDED clip. The status line it names is the one
     * `SampleInbox` renders now; if that line changes, this name is wrong
     * until the clip is captured again.
     */
    name:
      "Screen recording: a rejection is typed into the classifier sandbox on Applied's demo page, and Applied re-reads the message as the text arrives. The verdict moves from Other to Rejection, and the note beneath it changes from holding the mail for a person to filing it.",
    /**
     * The caption does one job the label cannot: it scopes the number inside
     * the frame. The confidence in the recording is one email's, worked out
     * at read time from that email.
     *
     * IT USED TO END "not the benchmark above it", and that clause is gone
     * with the benchmark: there is no longer a figure above this clip for a
     * reader to confuse it with. A scoping sentence that scopes against
     * something no longer on the page is furniture.
     */
    caption:
      "The sandbox on the demo page, recorded there. The confidence beside the verdict is this one email's, worked out live as the words arrive.",
  },
  sync: {
    name:
      "Screen recording: one press of Sync on Applied's demo board. The counters at the head of the board rise as new mail is filed, the applied group's own count follows, and the status line beside them says how many messages the pass filed and how many it had already seen.",
    /**
     * Scoped, like the rules caption, and for the same reason: the counters in
     * the frame are the demo's sample mailbox, not a claim about anyone's real
     * volume. What the clip is evidence FOR is the paragraph beside it — that a
     * pass reads mail — and the exhibit below it is what a read message leaves
     * behind. No number here: the frame states its own.
     */
    caption:
      "The demo board's own Sync, recorded there. The strip counts the pass: what it filed, and what it had already seen.",
  },
  letter: {
    /**
     * The name has to carry a CAMERA MOVE, which none of the others do: this
     * recording's frame travels, so a reader who cannot see it needs to know
     * that the mail and the row are two places on one board rather than two
     * screens. Written as the shot happens, in order.
     *
     * NO DIGITS, anywhere in this block. `landing-variants.test.mjs` asserts
     * it, and the reason is not tidiness: a figure in a clip's own words
     * reads as a second measurement of what the frame already states. The
     * confidence and the date are IN THE FRAME, where they belong to one
     * email; naming them out here would lift them out of that scope. So this
     * says "the verdict the classifier reached for it" rather than the number
     * it reached.
     */
    name:
      "Screen recording: on Applied's board, a card is open on the mail behind it, an assessment invitation from Kestrel Dynamics, carrying the verdict Applied reached for it and the deadline the message stated. The card is closed and the board's rows expand into the space it held. The frame then travels to the row itself, past the same deadline drawn on the row, and comes to rest with the row sitting in the board's assessment group.",
    /**
     * Two scopes in two short sentences, and the length is a CONSTRAINT, not
     * a style: `ClaimsDescent`'s row rail (where this clip rides since the
     * five-rail restaging, 2026-08-20) centres itself against `--exhibit`, a
     * measured constant, and a caption that wraps to a third line grows the
     * exhibit ~21px and puts the pinned rail ~10px out against an approved
     * render. Two lines at the rail's 480px measure, checked on a production
     * build at 1024 and 1512.
     *
     * The second sentence is the storyboard's refusal turned into a sentence
     * rather than left to the staging: the pane is opened and its verdict
     * resolved before a frame is recorded, so no moment of this clip can be
     * read as the arrival deciding anything. The first names the provenance
     * the way the other captions do.
     */
    caption:
      "The board this page runs live, recorded off it: an assessment invitation, and the row it left behind. Nothing is classified on camera.",
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
    "Both verdicts, from the reading that ships",
    "The same email, as the database keeps it",
    /** The escalated exhibit's third beat (02b): the two honesty rails a
     *  dissolve needs, in one line — this happens to APPLIED'S copy (Gmail
     *  keeps the original), and what survives is the decision, not the
     *  correspondence. */
    "The mail dissolves. Applied's copy, never your Gmail's",
  ],
} as const;

/**
 * The held exhibit's wall labels (`HeldExhibit`, the owner's 08c pick). The
 * same device as the verdict rail's: the exhibit changes state under the
 * reader, so the label names the state. The GATE itself is stated inside the
 * exhibit by the product's own review queue ("held because Applied wasn't
 * sure · your decision files them") — these lines stage it, they do not
 * restate it.
 */
export const HELD = {
  mail: "A mail the rules will not guess about",
  queue: "It waits in the review queue, filed by you and never guessed",
} as const;

/**
 * The rail takes' words (`RailTake` in `ClaimsDescent`) — the 02b and 08c
 * picks running AS TAKES, the way they ran in the lab the owner chose them
 * from: a pausable clock, narration per beat, autoplay once in view. The
 * narration lines are the lab's own where the lab had them; the two beats
 * the lab's 02b never staged (raw and split — its exhibit opened already
 * lit) restate `CLAIMS.verdict.raw` / `.split`, never a new claim.
 *
 * NO DIGITS in any string here, the FOOTAGE rule for the same reason: a
 * figure in an exhibit's own words reads as a second measurement of what the
 * exhibit already shows.
 *
 * `resting` is the reduced-motion line: each take's exhibit RESTS at its
 * most demonstrative state (the split verdicts; the settled queue), so the
 * line's job is to say the surface is at rest, not to apologise for it.
 */
export const KEPT = {
  /** A WALL LABEL NAMES THE THING, then says where it comes from. The first
   *  draft of the sweep cut this to "Computed in your tab", which names a
   *  provenance with no subject: the reader is told where something happens
   *  and never what it is. The comma does the work the dash did. */
  label: "Live verdict, computed in your tab",
  opening: "One mail, read past its preview, then reduced to the record.",
  narration: [
    "The mail as Gmail hands it over. The preview ends where the inviting begins.",
    "Read twice, live in your tab. The preview alone looks routine; the whole body holds the invitation.",
    "Now the mail dissolves. This is Applied's copy, and your Gmail keeps the original.",
    "Even the lit phrases go: read and used, never stored. What remains is the record.",
  ],
  resting: "Motion is off, and the two verdicts are still computed live in your tab.",
} as const;

export const HELD_TAKE = {
  /** "The shipped component" was page anatomy in a wall label: it told the
   *  reader about the repository, not about the queue. What the label owes
   *  them is that this is the real one, the one they will get. */
  label: "The real review queue, the one on your board",
  opening: "A held mail doesn't disappear; watch where it goes.",
  narration: [
    "The mail Applied wouldn't guess about.",
    "It isn't filed and it doesn't vanish. It takes its place in the review queue, question still open.",
    "Nothing moves until you decide: the mail keeps its place, the board keeps its truth.",
  ],
  resting: "Motion is off, and the mail rests where Applied holds it: in the review queue.",
} as const;

/**
 * The decision phase's second half, split into its own beat (2026-08-20).
 * One phase was carrying two ideas — what the rules do, and what they do
 * when they cannot — and the held exhibit's claim column was the benchmark's
 * leftovers. Nothing here is a new claim: the gate is the review queue's own
 * chrome ("held because Applied wasn't sure · your decision files them"),
 * and "the record keeps that it was your decision" is what the correction
 * store actually writes.
 *
 * THE ACCEPT BAR IS NO LONGER NAMED. `body` used to say the rules "come back
 * under their own accept bar, and a score under the bar is not a verdict",
 * which is a threshold with a component attached to it. What the reader
 * needs is that Applied came back unsure, and that unsure is not a verdict —
 * the same fact, in the vocabulary of somebody who is not going to read the
 * source.
 */
export const REVIEW = {
  eyebrow: "When it isn't sure",
  headline: "Not every mail gets a verdict. That's the point.",
  body:
    "Cedar's note commits to nothing: no next step, no decision, just patience requested. Applied reads it whole and comes back unsure, and unsure is not a verdict.",
  gate:
    "So the mail is held, not filed: it joins the review queue on your board, question still open. Your decision files it, and the record keeps that it was your decision and not a guess.",
  /** The payoff, and the one that turns a limitation into the feature it
   *  actually is: a queue of one ambiguous mail is a reading list, not a
   *  backlog. No new claim — the exhibit beside it is the queue. */
  payoff: "The one mail it holds is the one you would want to read yourself.",
} as const;

/**
 * The tracked clip's claim beat. This is the hero's own sentence — "Applied
 * moves the row for you" — promoted from a passing clause to the beat the
 * recording evidences: the storyboarded "ride the letter" take ends on the
 * row sitting in its group with the mail's deadline drawn on it. No number,
 * no new capability: everything stated here is inside the frame beside it.
 *
 * "THAT IS THE HERO'S WHOLE PROMISE" IS GONE from `body`. "The hero" is page
 * anatomy: a visitor does not know the page has one, and being told that a
 * sentence they read four screens ago was structurally important is a note
 * from the author to themselves.
 */
export const ROW = {
  eyebrow: "What you see",
  headline: "The mail becomes the move.",
  body:
    "An assessment invitation, already read, and the row it left behind: already sitting in the board's assessment group, carrying the deadline the message named. Applied moves the row for you, and this is what that looks like.",
  aside:
    "The mail that moved it stays one click away, behind the row it moved. That is the trail the take opens on.",
  /** The payoff, in the reader's own arithmetic. "Sixty threads" is the
   *  hero's "sixty other things" collected back up, which is what makes it a
   *  close rather than a new claim. */
  payoff: "You check one board, not sixty threads.",
} as const;
