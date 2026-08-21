/**
 * THE LANDING'S VOICE, held mechanically: no dashes, and no internals.
 *
 * Both rules predate this file and both were enforced by hand until
 * 2026-08-21, which is exactly why it exists. The hand-built census of dashed
 * strings that opened the sweep missed at least five of them, including the
 * privacy phase's enforcement sentence and two accessible names spoken to
 * every screen-reader user. A rule a person has to re-derive on every edit is
 * a rule that decays; these two are cheap to check and expensive to lose.
 *
 * ---------------------------------------------------------------------------
 * RULE 1 — NO DASHES IN ANYTHING THE LANDING RENDERS.
 *
 * The owner's standing rule is that an em or en dash reads as unedited machine
 * output. The three reference landings measured on 2026-08-21 carry 0
 * (vercel.com, nav and footer included), 1 (linear.app) and 2 (claude.com,
 * both inside FAQ answers). So the rule is not stricter than the field; for
 * two of the three it IS the field.
 *
 * A dash usually marks a construction that wants rewriting rather than
 * repunctuating. The two shapes the references reach for are full stop plus
 * fragment, and comma plus participle tail; the colon is legal and was badly
 * under-used before this sweep.
 *
 * THE FABRICATED RECRUITER MAILS ARE EXEMPT AND MUST STAY EXEMPT. They are
 * props imitating how companies write, and real recruiter mail is full of
 * dashes. Stripping theirs would make the props read as written by the same
 * hand as the page, which is a worse failure than the one this gate prevents:
 * the whole exhibit turns on those mails looking like mail.
 *
 * ---------------------------------------------------------------------------
 * RULE 2 — NO INTERNALS IN APPLIED'S VOICE.
 *
 * No architecture, no model names, no evaluation method, no self-graded
 * score, no CI threshold. `components/marketing/copy.ts` carries the long
 * argument in its DECISION block; the short version is that a figure grading
 * the product's own quality, in the product's own voice, appears on none of
 * the reference landings, and that for this page's reader "96 held-out
 * emails" reads as "they tested it on 96 emails".
 *
 * WHAT IS NOT BANNED, and the distinction matters more than the list: the
 * per-email scores in `VerdictTally`. Those are worked out from the mail in
 * front of the reader, in the reader's own browser, and they change if the
 * mail changes. The test is CHECKABLE-BY-OTHERS versus GRADED-BY-SELF, not
 * "is it a digit" — so this file bans the shape of a benchmark figure in
 * PROSE and leaves the exhibit's live arithmetic alone.
 *
 * ---------------------------------------------------------------------------
 * THE FILMED MODULE IS IN SCOPE, and it is the reason this gate is worth
 * more than the census it replaces.
 *
 * `components/demo/SampleInbox.tsx` is not a landing module and nothing on
 * the landing imports it. It is nonetheless ON the landing: the biggest
 * exhibit on the page, `rules-read-the-body`, is a screen recording OF that
 * component. Its status line read "below 0.90 — the full pipeline would defer
 * to e5 / SetFit" while every copy gate was green, because the words were in
 * a video and no scan of the import graph could reach them. A gate over the
 * import graph alone would have certified a page publishing two model names
 * and a threshold in its largest picture.
 *
 * So the scanned set is "modules whose TEXT reaches the landing", which is
 * the import graph plus what the camera points at. If another component is
 * filmed for this page, add it to FILMED or the gate quietly stops covering
 * the page again.
 *
 * A CAVEAT THIS GATE CANNOT CLOSE, stated rather than hidden: it proves the
 * SOURCE is clean, not that the SHIPPED CLIP is. Changing `SampleInbox` makes
 * the recording stale, and only re-running
 * `FOOTAGE_ONLY=rules-read-the-body pnpm footage` makes the pixels agree with
 * it. Nothing here can read a video.
 *
 * ---------------------------------------------------------------------------
 * MUTATION-TESTED AT INTRODUCTION (2026-08-21), against a 470-test baseline.
 * Each break was run, its failure count recorded, and the tree restored:
 *
 *   · an em dash back into `HERO.subhead`                   → 1 fail (rule 1)
 *   · an em dash into `ClosingAct`'s replay aria-label      → 1 fail (rule 1)
 *   · an em dash added to a fabricated recruiter mail       → 0 fails, which
 *     is the exemption working rather than a hole in it
 *   · "It scores 0.979 macro-F1." appended to a headline    → 2 fails: the
 *     score gate AND the internals gate, independently
 *   · "SetFit" into a clip's accessible name                → 1 fail (rule 2)
 *   · the old sandbox line restored in `SampleInbox`        → 3 fails: it
 *     carried a dash, two model names and a threshold, and this is the whole
 *     argument for FILMED — every one of those three was invisible to the
 *     import-graph scan
 *   · `FILMED = []`                                         → 1 fail, the
 *     coverage control, so a later edit cannot silently narrow the scan
 *   · the crop's `from` anchor pointed at a test id that does not exist
 *     → the region assertion throws at module load, naming the drift
 *
 * NOT INDEPENDENTLY REDDENED, and named rather than implied: the
 * `scanned.size >= 15` bound and the PROP_FILES negative check inside the
 * coverage control. The FILMED mutations prove that test fails when its
 * subject goes missing; they do not prove those two particular bounds bind.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { code, isLandingModule, rel, walkGraph, webRoot } from "./helpers/landingGraph.mjs";

const graph = walkGraph();

/**
 * Props, not prose. These four files hold fabricated recruiter mail and the
 * still board's fabricated signals; see rule 1 above for why their dashes are
 * correct and must not be swept.
 */
const PROP_FILES = new Set([
  "components/marketing/heldMail.ts",
  "components/marketing/verdictEmailData.ts",
  "components/marketing/showcase.ts",
  "components/marketing/BoardStill.tsx",
]);

/**
 * The document's own head, which the import graph cannot reach.
 *
 * `app/layout.tsx` is not imported by `app/page.tsx` — Next composes them —
 * so a walk from the landing page never sees it. Its `metadata` export
 * nonetheless renders into the head of the landing, into every search
 * result, and into every link preview anyone shares. It is the most public
 * copy Applied has.
 *
 * It survived the whole #394 sweep with the architecture, two model names, a
 * self-graded score, a CI threshold and two em dashes intact:
 *
 *   "A 3-layer classifier — rules, e5 embeddings, SetFit — reads your
 *    applications out of your inbox; the rules stage alone scores 0.9791
 *    macro-F1, CI-gated at 0.95."
 *
 * THAT IS THE THIRD TIME THIS SHAPE HAS BITTEN, and the shape is worth
 * naming: text that reaches the landing from outside the landing's module
 * set. First the filmed component, whose words were inside a video. Then
 * this. A gate scoped to "what the landing imports" is scoped to the wrong
 * thing; the scope is "what a reader ends up seeing", and every time that
 * gap is found it gets added here rather than argued about.
 */
const DOCUMENT_HEAD = ["app/layout.tsx"];

/**
 * Modules the landing does not import but DOES film, and THE REGION OF EACH
 * ONE THE CAMERA ACTUALLY SEES.
 *
 * The region is not fussiness, it is the difference between a gate and an
 * opinion. `SampleInbox` renders a three-layer architecture visualiser
 * further down the page ("rules · e5 · SetFit", "e5 embedding similarity",
 * "SetFit few-shot head"), and a file-level scan flags all of it. None of it
 * is on the landing: `scripts/footage/scenes.mjs` crops this clip to
 * `boxOf([playground-subject's parent, playground-verdict's parent])` and
 * says in its own words that it "deliberately stops ABOVE the score chips",
 * because those appear only once something scores and would make the frame
 * breathe.
 *
 * So the anchors below are THE CROP'S OWN, in source form: the same two test
 * ids the capture resolves, plus the score-chips block the capture stops
 * above. If the component is restructured the anchors stop matching and the
 * coverage control reds, which is the failure mode to want — a scan that
 * silently stops covering its subject is the defect this whole file exists
 * to prevent.
 *
 * WHAT THIS DELIBERATELY DOES NOT CLAIM: that the demo page as a whole is
 * free of internals. It is not, and that is a separate decision about a
 * different surface. This gate covers the landing.
 */
const FILMED = [
  {
    path: "components/demo/SampleInbox.tsx",
    from: /data-testid="playground-subject"/,
    to: /topScores\.length > 0/,
  },
];

/** Every module whose text reaches the landing, path → stripped source. */
function scannedModules() {
  const out = new Map();
  for (const [file, src] of graph) {
    if (!isLandingModule(file)) continue;
    if (PROP_FILES.has(rel(file))) continue;
    out.set(rel(file), src);
  }
  for (const path of DOCUMENT_HEAD) {
    out.set(path, code(readFileSync(join(webRoot, path), "utf8")));
  }
  for (const { path, from, to } of FILMED) {
    const lines = code(readFileSync(join(webRoot, path), "utf8")).split("\n");
    const start = lines.findIndex((l) => from.test(l));
    const end = lines.findIndex((l) => to.test(l));
    assert.ok(
      start >= 0 && end > start,
      `the filmed region of ${path} could not be located (from=${start}, to=${end}) — the crop anchors in scenes.mjs and the ones here have drifted apart, so this module is unscanned`,
    );
    out.set(`${path} (filmed region)`, lines.slice(start, end).join("\n"));
  }
  return out;
}

const scanned = scannedModules();

/**
 * A positive control on the scan itself, and it is not ceremony: every
 * assertion below is of the form "X does not appear". A scan over an empty
 * set, or one that stopped reaching `copy.ts`, passes all of them while
 * measuring nothing. This is the same hole that let a blinded camera watcher
 * pass three assertions green earlier in the same week.
 */
test("the voice scan actually reaches the landing's words", () => {
  assert.ok(
    scanned.size >= 15,
    `the scan covers only ${scanned.size} module(s) — it is not reaching the landing, so its clean result is not evidence`,
  );
  assert.ok(
    scanned.has("components/marketing/copy.ts"),
    "copy.ts is not in the scanned set — the file holding every rendered string is unscanned",
  );
  for (const { path } of FILMED) {
    const key = `${path} (filmed region)`;
    assert.ok(scanned.has(key), `${path} is listed as filmed but was not scanned`);
    // A region that located itself but came back nearly empty would pass
    // every "X does not appear" assertion below without reading the words.
    assert.ok(
      scanned.get(key).split("\n").length >= 8,
      `the filmed region of ${path} is ${scanned.get(key).split("\n").length} lines — too small to contain the verdict row it is supposed to cover`,
    );
  }
  for (const path of DOCUMENT_HEAD) {
    assert.ok(scanned.has(path), `${path} is listed as document head but was not scanned`);
  }
  assert.ok(
    DOCUMENT_HEAD.length >= 1,
    "DOCUMENT_HEAD is empty — the head renders on the landing and in every search result, and it is where the internals last survived a sweep",
  );
  assert.ok(
    FILMED.length >= 1,
    "FILMED is empty — the recorded surfaces are unscanned, and the internals leak this gate was built for was in exactly one of them",
  );
  // And the exemption must be an exemption, not a typo that exempts nothing.
  for (const path of PROP_FILES) {
    assert.ok(
      !scanned.has(path),
      `${path} is in PROP_FILES but was scanned anyway — the exemption is not matching`,
    );
  }
});

test("nothing the landing renders contains an em or en dash", () => {
  const offenders = [];
  for (const [path, src] of scanned) {
    src.split("\n").forEach((line, i) => {
      if (/[—–]/.test(line)) offenders.push(`${path}:${i + 1}  ${line.trim().slice(0, 120)}`);
    });
  }
  assert.deepEqual(
    offenders,
    [],
    `dashes in rendered copy (${offenders.length}):\n${offenders.join("\n")}\n\nRewrite the sentence around the dash — full stop plus fragment, a comma plus a participle tail, or a colon. Do not just delete it. If the string is a fabricated recruiter mail, it belongs in PROP_FILES instead.`,
  );
});

/**
 * The architecture, the models, the evaluation method and the thresholds.
 * Matched case-insensitively on word boundaries against STRING LITERALS
 * only — `rulesLayer` is an identifier a landing module legitimately
 * imports, and banning the word everywhere would ban the import too.
 */
const BANNED_TERMS = [
  "e5",
  "setfit",
  "cascade",
  "regex",
  "regexes",
  "macro-f1",
  "held-out",
  "fine-tuned",
  "embedding",
  "embeddings",
  "neural",
  "accept bar",
  "layer-1",
  "benchmark",
  "benchmarked",
];

/** Double-quoted literals, which is how every rendered string in this family
 *  is written. Backticks and single quotes are checked too so a future edit
 *  cannot slip a claim through by changing its quoting. */
function stringLiterals(src) {
  return [
    ...src.matchAll(/"((?:[^"\\\n]|\\.)*)"/g),
    ...src.matchAll(/'((?:[^'\\\n]|\\.)*)'/g),
    ...src.matchAll(/`((?:[^`\\]|\\.)*)`/g),
  ].map((m) => m[1]);
}

/**
 * A string literal that is CODE, not copy, and therefore not this file's
 * business. Three shapes, each one a real false positive this gate produced
 * on its first run:
 *
 *   · a CSS custom property or a function call — `var(--viz-setfit)`,
 *     `transform ${ms}ms cubic-bezier(0.22, 1, 0.36, 1)`;
 *   · a Tailwind class list — `border-viz-embeddings/50 text-viz-embeddings`;
 *   · anything carrying `--`, which in this codebase is always a custom
 *     property or a Tailwind arbitrary value.
 *
 * The design-token names DO carry two of the banned words (`--viz-setfit`,
 * `--viz-embeddings`), and that is a real if faint leak: a visitor with
 * devtools open can read them. Renaming design tokens across the whole app is
 * a different change from a copy sweep, and a token name is not the product
 * speaking. Recorded here so the exemption is a decision rather than an
 * oversight.
 */
function isCodeLiteral(literal) {
  if (/^var\(/.test(literal)) return true;
  if (literal.includes("--")) return true;
  if (/\b(cubic-bezier|calc|translate[A-Z3]?|scaleX?|rgba?|oklch|oklab|matrix)\(/.test(literal)) {
    return true;
  }
  // A class list. THE TOKEN RATIO IS THE POINT, and the first version of this
  // branch got it wrong in a way worth recording, because the wrong version
  // looks obviously right: it accepted any all-lowercase string carrying a
  // single hyphen anywhere. Four of the highest-risk banned terms are exactly
  // that shape, so
  //
  //     "scored on a held-out set of ninety six emails"
  //
  // was classified as CSS and skipped, and the mutation proving it stayed
  // green while the ban list contained the very word in the sentence. The
  // eight mutations run at introduction all missed it: each one carried a
  // capital or a full stop, so none of them had this shape.
  //
  // What actually separates Tailwind from prose is not "contains a hyphen",
  // it is that ALMOST EVERY token carries a separator. `mt-4 text-muted` is
  // 2 of 2; a sentence with a compound adjective in it is 1 of 9.
  if (/^[a-z0-9\s:/[\]._-]+$/.test(literal)) {
    const tokens = literal.trim().split(/\s+/);
    const cssish = tokens.filter((t) => /[-:/[\]]/.test(t)).length;
    if (cssish >= Math.max(1, Math.ceil(tokens.length * 0.6))) return true;
  }
  return false;
}

/**
 * Every regex metacharacter, not just the hyphen.
 *
 * This escaped `-` alone, which CodeQL flagged as an incomplete sanitization
 * (js/incomplete-sanitization, high). Today's BANNED_TERMS are plain words
 * and one hyphenated pair, so nothing is currently mis-escaped, and that is
 * exactly the trap: the list is meant to be appended to, and the first term
 * carrying a `.` or a `+` would silently widen into a pattern that matches
 * more than the word. A copy gate that quietly starts matching the wrong
 * strings is worse than no gate, because its greens still get believed.
 */
function escapeForRegExp(term) {
  return term.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");
}

test("no landing string names the architecture, a model, or a threshold", () => {
  const offenders = [];
  for (const [path, src] of scanned) {
    for (const literal of stringLiterals(src)) {
      if (isCodeLiteral(literal)) continue;
      for (const term of BANNED_TERMS) {
        if (new RegExp(`\\b${escapeForRegExp(term)}\\b`, "i").test(literal)) {
          offenders.push(`${path}  "${literal.slice(0, 100)}"  →  ${term}`);
        }
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `internals in rendered copy (${offenders.length}):\n${offenders.join("\n")}\n\nThe landing states what the product does, never how it is built. The System Card is where the architecture and the benchmark live.`,
  );
});

test("no landing string states a self-graded score", () => {
  // The two the page used to publish, named exactly. Cheap, unambiguous, and
  // the first thing a well-meaning edit would put back.
  const RETIRED_FIGURES = ["0.979", "0.958"];
  const offenders = [];

  for (const [path, src] of scanned) {
    for (const figure of RETIRED_FIGURES) {
      if (src.includes(figure)) offenders.push(`${path} states the retired figure ${figure}`);
    }

    for (const literal of stringLiterals(src)) {
      // PROSE ONLY. A Tailwind arbitrary value (`text-[0.8125rem]`, a `calc()`
      // in an `--exhibit` expression) is a string literal full of decimals and
      // is not a claim. The discriminator is the DECIMAL'S TAIL: a length or a
      // ratio is followed by a unit, a bracket or a word character, and a
      // score is followed by a space, a full stop, or the end of the string.
      if (isCodeLiteral(literal)) continue;
      if (!/[A-Za-z]{4,}\s/.test(literal)) continue;
      const score = /\b\d+\.\d{2,}(?![\w\]%)_-])/.exec(literal);
      if (score) {
        offenders.push(`${path}  "${literal.slice(0, 100)}"  →  ${score[0]}`);
      }
    }
  }

  assert.deepEqual(
    offenders,
    [],
    `a score-shaped figure in rendered copy (${offenders.length}):\n${offenders.join("\n")}\n\nA number the reader cannot check, in the product's own voice, is the thing this page stopped doing. Live per-email arithmetic computed in their tab is fine and is not what this matches.`,
  );
});
