/**
 * No landing page can ever touch a real account — and their claims stay
 * attributed.
 *
 * THE PAGES THIS COVERS ARE `/` AND THE TWO PRESERVED CANDIDATES. The pinned
 * composition was promoted out of `/landing-b` to the site root, so the
 * shipping landing is `app/page.tsx` now; `/landing-a` and `/landing-c` stay
 * where they are, noindex, as the comparison set. Everything below applies to
 * all three — the promoted page is the one a stranger actually reaches, so it
 * is held harder, not less.
 *
 * WHAT THE CONTRACT IS. `PipelineBoard`'s `transport` prop DEFAULTS to
 * `liveBoardTransport` (lib/dashboard/transport.ts), which PATCHes
 * /api/applications/*. A marketing embed that forgets to pass the demo
 * transport does not error — in a signed-in owner's browser (localhost serves
 * real production data) dragging a row on the landing page would mutate a
 * real account. So this test walks the real import graph from each landing
 * page and holds three lines:
 *
 *   1. no module under app/page.tsx / app/landing-* / components/marketing
 *      names `liveBoardTransport` at all;
 *   2. every `<PipelineBoard …>` reachable from a landing page passes an
 *      explicit `transport=` (or is `interactive={false}`, which performs no
 *      mutations) — in practice the one mount is `DemoDashboard`'s, whose
 *      in-memory transports are the reason the landing goes through it;
 *   3. the candidates never reach `DemoShell` — the shell mounts the LOCKED
 *      board variant, the nested-scroll trap a flowing page must not embed.
 *
 * WHY A SOURCE SCAN. Same boundary as page-header-contract.test.mjs: these
 * are components this harness cannot render, and the failure that actually
 * happens is one line — a board mounted without its transport prop.
 *
 * It also pins the copy honesty rules the variants were built under: 0.979
 * lives in copy.ts alone, attributed to the rules stage; 0.958 is the cascade;
 * no pattern count appears anywhere (the repo holds three conflicting values
 * for that noun); the privacy promise is RETENTION, not request, and the test
 * it names exists on disk; the two preserved candidates stay noindex while
 * `/` must NOT be; the footer keeps the /privacy link Google's OAuth
 * verification looks for.
 *
 * The closing act's key and the product clip's words joined that list once they
 * became rendered strings, and both are held on the same principle:
 *
 *   · the rail labels (`CLOSING.railShips` / `railGhost`) are WORDS. The
 *     figures beside them are composed in `ClosingAct` from `DECISION`, so a
 *     digit typed into a label — the drift where 0.979 acquires a second home
 *     and its attribution stops travelling with it — is a failure. Both
 *     figures are held: only 0.979 had a no-hardcoding scan, and 0.958 could
 *     be typed anywhere on the page with every gate green.
 *   · `FOOTAGE` states no number at all. It sits beside the benchmark, and a
 *     figure in the recording's own words reads as a second measurement; the
 *     one number the frames contain is scoped by the caption instead.
 *
 * Both read the STRIPPED source (`graph.get`, never `readFileSync`): the two
 * components' docblocks quote `DECISION.rulesF1` and `FOOTAGE.label` verbatim,
 * so a scan of raw source would stay green with the render deleted and the
 * comment left behind.
 *
 * MUTATION-TESTED AT INTRODUCTION (2026-08-15). Nine deliberate breaks, each
 * watched go red and green again on restore: an empty rail label; `0.979`
 * typed into a rail label; `0.958` typed into `ClosingAct` in place of the
 * composed value; the `{DECISION.rulesF1}` span deleted (its docblock mention
 * left behind); an empty `FOOTAGE.label`; a figure added to the clip's
 * caption; the label no longer naming a recording; the caption's scoping
 * clause dropped; `ClaimsDescent` inlining the clip's accessible name.
 * Companion bounds NOT independently reddened, and named as such rather than
 * claimed: the three graph-reachability guards, the key-present regexes (the
 * empty-string mutations prove the value, not the key), `act.includes(
 * "CLOSING.railShips")`, the `rulesF1: "0.979"` shape match, `lines.length >=
 * 5`, and the three "these words render" checks on ProductClip and
 * ClaimsDescent.
 *
 * And it holds the three STRUCTURAL bets the round-two edit made, each of
 * which is a copy claim in disguise:
 *
 *   · every scene of the window act carries a caption — the act's first scene
 *     used to be a wordless viewport of a resting board;
 *   · beat 0's sentinel zone stays long enough that the verdict cannot land
 *     on a window that has not finished pinning (the inequality is derived in
 *     WindowAct's docblock and asserted here in vh);
 *   · the split verdict stays TWO micro-beats under one headline. A single
 *     `split` screen would still render every word this file allows, and the
 *     page would still be wrong — the exhibit is a demonstration only because
 *     it happens in order.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** The shipping landing, first — `/landing-b` was promoted to `app/page.tsx`. */
const ROOT_PAGE = join(webRoot, "app", "page.tsx");

/** The preserved comparison set, which stays noindex on its own routes. */
const CANDIDATE_PAGES = ["landing-a", "landing-c"].map((dir) =>
  join(webRoot, "app", dir, "page.tsx"),
);

const PAGES = [ROOT_PAGE, ...CANDIDATE_PAGES];

/** Comments out, code only — the comments here quote the very identifiers
 *  this test forbids. Same stripper the aria-current gate uses. */
function code(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/** `import x from "y"`, `export … from "y"`, and dynamic `import("y")`. */
function importSpecs(src) {
  return [...src.matchAll(/(?:from|import)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1]);
}

function resolveSpec(spec, fromDir) {
  const base = spec.startsWith("@/")
    ? join(webRoot, spec.slice(2))
    : spec.startsWith(".")
      ? join(fromDir, spec)
      : null;
  if (!base) return null; // a package — not ours to walk
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** Every repo module reachable from the candidate pages, path → code. */
function walkGraph() {
  const seen = new Map();
  const queue = [...PAGES];
  while (queue.length > 0) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    const src = readFileSync(file, "utf8");
    seen.set(file, code(src));
    if (!/\.(ts|tsx)$/.test(file)) continue; // json/css carry no imports
    for (const spec of importSpecs(src)) {
      const resolved = resolveSpec(spec, dirname(file));
      if (resolved && !seen.has(resolved)) queue.push(resolved);
    }
  }
  return seen;
}

const graph = walkGraph();
const rel = (file) => relative(webRoot, file);
/** `app/page.tsx` is named exactly: the promoted landing is a landing module,
 *  and the `app/landing-` prefix does not reach it. Miss this and the
 *  strongest assertion in this file — no landing module names the live
 *  transport — silently stops covering the page a stranger actually loads. */
const isLandingModule = (file) =>
  rel(file) === "app/page.tsx" ||
  rel(file).startsWith("app/landing-") ||
  rel(file).startsWith("components/marketing/");

const marketing = (name) => join(webRoot, "components", "marketing", name);
const copyPath = marketing("copy.ts");
const actPath = marketing("WindowAct.tsx");
const tempoPath = marketing("tempo.ts");

/**
 * The act's marks, read out of tempo.ts rather than restated here.
 *
 * By text, because this suite is a source gate and cannot import TypeScript —
 * and because restating the numbers would make the gate agree with itself
 * instead of with the component. Comments are stripped first: every mark in
 * that file carries a paragraph above it, and several of those paragraphs
 * contain numbers.
 */
function readMarks() {
  const src = (graph.get(tempoPath) ?? "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const block = /export const ACT_MARKS\s*=\s*\{([\s\S]*?)\}\s*as const;/.exec(src);
  assert.ok(block, "ACT_MARKS is gone from tempo.ts — the act has no marks to be in order");
  const scalar = (key) => {
    const m = new RegExp(`${key}:\\s*(-?[\\d.]+)`).exec(block[1]);
    assert.ok(m, `ACT_MARKS.${key} is gone`);
    return Number(m[1]);
  };
  const pair = (key) => {
    const m = new RegExp(`${key}:\\s*\\[\\s*(-?[\\d.]+)\\s*,\\s*(-?[\\d.]+)`).exec(block[1]);
    assert.ok(m, `ACT_MARKS.${key} is no longer a pair`);
    return [Number(m[1]), Number(m[2])];
  };
  const band = /export const ACT_DEADBAND\s*=\s*([\d.]+)/.exec(src);
  assert.ok(band, "ACT_DEADBAND is gone — the latches would chatter at every mark");
  return {
    ACT_MARKS: {
      scene: scalar("scene"),
      pan: pair("pan"),
      receipt: pair("receipt"),
      verdict: scalar("verdict"),
      docked: scalar("docked"),
      dockPan: pair("dockPan"),
    },
    ACT_DEADBAND: Number(band[1]),
  };
}
const descentPath = marketing("ClaimsDescent.tsx");
const closingPath = marketing("ClosingAct.tsx");
const clipPath = marketing("ProductClip.tsx");
/** Repo-relative (webRoot is apps/web), because the copy names it verbatim. */
const PRIVACY_TEST_PATH = "backend/tests/test_body_is_never_persisted.py";

test("candidate pages exist and the graph is non-trivial", () => {
  for (const page of PAGES) assert.ok(graph.has(page), `${rel(page)} missing`);
  // The board must actually be reachable — a green run over a graph that
  // never reaches PipelineBoard would be this gate testing nothing.
  const board = join(webRoot, "components", "dashboard", "PipelineBoard.tsx");
  assert.ok(graph.has(board), "PipelineBoard is not in the landing graph — the embed is gone");
});

test("no landing module names liveBoardTransport", () => {
  for (const [file, src] of graph) {
    if (!isLandingModule(file)) continue;
    assert.ok(
      !src.includes("liveBoardTransport"),
      `${rel(file)} references liveBoardTransport — a landing module must only ever see the demo transport`,
    );
  }
});

test("every reachable <PipelineBoard> passes an explicit transport", () => {
  let mounts = 0;
  for (const [file, src] of graph) {
    for (const tag of src.matchAll(/<PipelineBoard\b[\s\S]*?>/g)) {
      mounts += 1;
      assert.ok(
        /\btransport=/.test(tag[0]) || /\binteractive=\{false\}/.test(tag[0]),
        `${rel(file)} mounts <PipelineBoard> without an explicit transport — the default is the LIVE transport`,
      );
    }
  }
  assert.ok(mounts >= 1, "no <PipelineBoard> mount found in the landing graph");
});

test("the candidates never reach the locked shell", () => {
  const shell = join(webRoot, "components", "demo", "DemoShell.tsx");
  assert.ok(
    !graph.has(shell),
    "DemoShell is in the landing graph — it mounts the locked board, the nested-scroll trap",
  );
});

test("0.979 is stated once, in copy.ts, attributed to the rules stage", () => {
  const copySrc = graph.get(copyPath);
  assert.ok(copySrc, "components/marketing/copy.ts is not in the graph");
  assert.ok(copySrc.includes('rulesF1: "0.979"'), "rules figure moved or lost its attribution key");
  assert.ok(copySrc.includes('cascadeF1: "0.958"'), "cascade figure moved or lost its attribution key");
  assert.match(
    copySrc,
    /rulesLabel:\s*"rules stage/,
    "the 0.979 label no longer names the rules stage",
  );
  for (const [file, src] of graph) {
    if (!isLandingModule(file) || file === copyPath) continue;
    assert.ok(
      !src.includes("0.979"),
      `${rel(file)} hardcodes 0.979 — the figure lives in copy.ts so its attribution cannot drift`,
    );
  }
});

test("the closing act's rail labels are words, and compose the figures", () => {
  const copySrc = graph.get(copyPath);
  const act = graph.get(closingPath);
  assert.ok(act, "ClosingAct.tsx is not in the landing graph — the closing act is unmounted");

  // The scene's key is DOM text now: as svg `<text>` inside a 1200-unit
  // viewBox it measured 3.1–3.3px at 375 and 8.3–9.0px at 1024, so the page's
  // central comparison was under any legible floor at every width. Words that
  // render are copy, and copy lives in one file.
  const labels = new Map();
  for (const key of ["railShips", "railGhost"]) {
    const found = new RegExp(`${key}:\\s*"([^"]*)"`).exec(copySrc);
    assert.ok(
      found,
      `CLOSING.${key} is gone from copy.ts — the rail's words are back inside the drawing`,
    );
    assert.ok(
      found[1].trim().length > 0,
      `CLOSING.${key} is empty — the rail it names claims nothing`,
    );
    labels.set(key, found[1]);
    assert.ok(act.includes(`CLOSING.${key}`), `ClosingAct stopped rendering CLOSING.${key}`);
  }

  // COMPOSED, NOT TYPED. The label carries the attribution and `DECISION`
  // carries the figure; a digit in the label gives the number a second home,
  // and the attribution stops travelling with it. That drift is the whole
  // reason this file exists — 0.979 is the RULES stage, not the cascade.
  for (const [key, label] of labels) {
    assert.ok(
      !/\d/.test(label),
      `CLOSING.${key} ("${label}") types a figure into the rail label — the digits are DECISION.rulesF1 / DECISION.cascadeF1, composed beside it in ClosingAct`,
    );
  }

  for (const [key, figure] of [
    ["rulesF1", "0.979"],
    ["cascadeF1", "0.958"],
  ]) {
    const stated = copySrc.split(figure).length - 1;
    assert.equal(
      stated,
      1,
      `${figure} is written ${stated} times in copy.ts — it is stated once, as DECISION.${key}`,
    );
    assert.match(
      copySrc,
      new RegExp(`${key}:\\s*"${figure}"`),
      `DECISION.${key} is no longer ${figure}`,
    );
    assert.ok(
      act.includes(`DECISION.${key}`),
      `the closing act's key no longer composes DECISION.${key} — its figure is not the single-sourced one`,
    );
    // The 0.979 half restates the scan above; the 0.958 half is new. The
    // cascade figure had no no-hardcoding rule at all, so it could be typed
    // into any landing module — including the rail it labels — with every
    // gate green.
    for (const [file, src] of graph) {
      if (!isLandingModule(file) || file === copyPath) continue;
      assert.ok(
        !src.includes(figure),
        `${rel(file)} hardcodes ${figure} — the figure lives in copy.ts so its attribution cannot drift`,
      );
    }
  }
});

test("no pattern count appears on the candidates", () => {
  // Three different values exist in this repo for that one noun (201, 214,
  // 243). None of them is gate-derived, so none of them ships in copy.
  for (const [file, src] of graph) {
    if (!isLandingModule(file)) continue;
    assert.ok(
      !/\b\d+\s+(?:regex\s+)?patterns?\b/i.test(src),
      `${rel(file)} states a pattern count — that number is not gate-backed`,
    );
  }
});

test("the privacy claim is about RETENTION, not about what is requested", () => {
  const copySrc = graph.get(copyPath);
  // The app FETCHES bodies (as of 2026-08-14) and discards them. Softening
  // that to "never reads" or "only requests headers" would be the easy,
  // wrong copy edit — and the one this page must never make.
  assert.match(
    copySrc,
    /retention:[\s\S]*?discards it/,
    "PRIVACY.retention no longer says the body is read and then discarded",
  );
  for (const [file, src] of graph) {
    if (!isLandingModule(file)) continue;
    assert.ok(
      !/never (?:reads|fetches|requests|downloads)[^.]{0,40}\bbod(?:y|ies)\b/i.test(src),
      `${rel(file)} claims Applied never reads the body — the promise is retention, not request`,
    );
  }
  // The enforcement the copy names has to exist, or the sentence is a bluff.
  const enforcement = join(webRoot, "..", "..", PRIVACY_TEST_PATH);
  assert.ok(
    existsSync(enforcement),
    `${PRIVACY_TEST_PATH} does not exist at ${enforcement} — PRIVACY.mechanism names a test that is gone`,
  );
  assert.ok(
    copySrc.includes(`testPath: "${PRIVACY_TEST_PATH}"`),
    "PRIVACY.testPath drifted from the file this gate resolves",
  );
});

test("the window act captions every scene — and no scene is wordless", () => {
  const act = graph.get(actPath);
  assert.ok(act, "WindowAct.tsx is not in the landing graph");
  const block = /captions:\s*\[([\s\S]*?)\]/.exec(graph.get(copyPath));
  assert.ok(block, "ACT.captions is gone — the act's scenes have no words");
  const captions = [...block[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);

  // The count FIRST. It used to sit after a `deepEqual` on the sentinel
  // indices, so the moment those changed this property stopped being reachable
  // at all — the assertion was there, and could not run.
  assert.equal(
    captions.length,
    3,
    "the act has three scenes (rest, the verdict, the mail) — a scene without a caption is the dead dwell this fixed",
  );
  for (const [i, line] of captions.entries()) {
    assert.ok(line.trim().length > 0, `caption ${i} is empty`);
  }
  assert.ok(act.includes("ACT.captions"), "WindowAct stopped rendering the captions");

  // Scene 0 revisited is RETIRED, and this asserts the retirement rather than
  // the old line. The act is a function of scroll position now, so scrolling
  // back up un-does the verdict and closes the pane: scene 0 revisited IS
  // scene 0. A caption describing a permanently settled board would be the one
  // line on the page that could contradict the board it captions — so if a
  // latch ever comes back and brings that line with it, this goes red.
  assert.doesNotMatch(
    graph.get(copyPath),
    /^\s*settled:\s*"/m,
    "ACT.settled is back — a caption for a settled board means the act stopped reversing",
  );
  assert.ok(
    !act.includes("ACT.settled"),
    "WindowAct references a revisited-scene caption again — the act is meant to reverse instead",
  );
});

test("the act's marks keep the choreography in order", () => {
  // These used to be three `h-[N%]` sentinel zones and an inequality about a
  // -45% IntersectionObserver band. There are no sentinels now: the act reads
  // one scroll progress and the marks are shares of it (tempo.ts). What has to
  // hold is the ORDER, because the order is the product's honesty — the camera
  // arrives before the receipt announces, the receipt announces before the row
  // moves, and the pane never opens on a row that has not arrived.
  const { ACT_MARKS, ACT_DEADBAND } = readMarks();
  const [panFrom, panTo] = ACT_MARKS.pan;
  const [receiptFrom, receiptTo] = ACT_MARKS.receipt;

  for (const [name, value] of [
    ["scene", ACT_MARKS.scene],
    ["pan start", panFrom],
    ["pan end", panTo],
    ["receipt start", receiptFrom],
    ["receipt end", receiptTo],
    ["verdict", ACT_MARKS.verdict],
    ["docked", ACT_MARKS.docked],
  ]) {
    assert.ok(value > 0 && value < 1, `${name} (${value}) is outside the runway`);
  }

  assert.equal(ACT_MARKS.scene, panFrom, "the caption changes at a different point from the camera");
  assert.ok(panFrom < panTo, "the camera's pan does not advance");
  assert.ok(receiptFrom < receiptTo, "the receipt's rise does not advance");

  // The camera reaches the foot before the row commits, or the verdict lands
  // in a frame that is still moving. Deadbands on both sides, because the
  // latch fires at mark + deadband at the earliest.
  assert.ok(
    panTo < ACT_MARKS.verdict - ACT_DEADBAND,
    `the pan ends at ${panTo} but the row can commit from ${ACT_MARKS.verdict - ACT_DEADBAND}`,
  );
  // The receipt announces before the row moves — "announce, then move", the
  // whole reason there is something to watch — and the gap between them is the
  // BREATH that replaced VERDICT_BREATH_MS. A zero breath is the defect.
  const breath = ACT_MARKS.verdict - ACT_DEADBAND - receiptTo;
  assert.ok(
    breath > 0.05,
    `the announced breath is ${breath.toFixed(3)} of the runway — the receipt no longer lands before the row moves`,
  );
  // The pane docks after the row has committed, with room between them.
  assert.ok(
    ACT_MARKS.verdict + ACT_DEADBAND < ACT_MARKS.docked - ACT_DEADBAND,
    "the verdict and the pane's dock overlap — the pane can open on a row that has not moved",
  );
  // The camera's tilt to the pane's head starts only past the dock latch's
  // far edge — the pane has to EXIST before the camera moves toward it — and
  // finishes inside the runway with dwell left on the full-chrome frame. The
  // tilt is what put the pane's × back on screen (the owner's report:
  // "i don't see the icons to close the right pane"); a tilt that starts
  // before the dock would aim the camera at a pane that is not there.
  const [dockPanFrom, dockPanTo] = ACT_MARKS.dockPan;
  assert.ok(
    dockPanFrom > ACT_MARKS.docked + ACT_DEADBAND,
    `the dock tilt starts at ${dockPanFrom}, before the pane's latch can have fired (${ACT_MARKS.docked} + ${ACT_DEADBAND})`,
  );
  assert.ok(dockPanFrom < dockPanTo, "the dock tilt does not advance");
  assert.ok(
    dockPanTo < 0.95,
    `the dock tilt ends at ${dockPanTo} — the full-chrome frame gets no dwell before the pin releases`,
  );

  // And the runway is long enough that those shares are worth real pixels. The
  // act failed at 270vh: 1723px of pinned scroll for three scenes, ~574px each
  // against a 3s choreography. The gate is the SHORTEST supported viewport
  // (600px), where the runway is (H - 1) * 600.
  const runway = Number(/lg:h-\[(\d+)vh\]/.exec(graph.get(actPath))?.[1]);
  assert.ok(Number.isFinite(runway), "the act's runway height is no longer a literal vh");
  const shortest = ((runway - 100) / 100) * 600;
  const breathPx = breath * shortest;
  assert.ok(
    breathPx > 120,
    `the breath is ${Math.round(breathPx)}px at a 600-tall viewport — under ~120 nobody crosses it slowly enough to read the announcement`,
  );
});

test("the latch has hysteresis, and it is symmetric about the mark", () => {
  // `latch` is the one pure function the whole rework rests on: every piece of
  // board state is `latch(progress, mark, current, deadband)`, so a latch that
  // flips on the mark itself would chatter at the boundary and re-target a
  // layout animation on every frame of trackpad momentum. It had no test.
  //
  // Reimplemented from source rather than imported, for the same reason
  // `readMarks` parses: this suite cannot import TypeScript. The gate is that
  // the SOURCE still says this — if the implementation changes shape, this
  // goes red and someone has to look.
  const src = graph.get(marketing("scrub.ts")) ?? "";
  assert.match(
    src,
    /return current \? progress > mark - deadband : progress >= mark \+ deadband;/,
    "latch's hysteresis changed shape — the property below no longer describes it",
  );
  const latch = (progress, mark, current, deadband) =>
    current ? progress > mark - deadband : progress >= mark + deadband;

  const mark = 0.5;
  const band = 0.025;
  // Rising: nothing happens until the far side of the band.
  assert.equal(latch(0.49, mark, false, band), false);
  assert.equal(latch(0.5, mark, false, band), false, "the latch flips ON the mark — that chatters");
  assert.equal(latch(0.524, mark, false, band), false);
  assert.equal(latch(0.525, mark, false, band), true);
  // Falling: it stays on until the near side.
  assert.equal(latch(0.5, mark, true, band), true, "the latch flips back ON the mark");
  assert.equal(latch(0.476, mark, true, band), true);
  assert.equal(latch(0.475, mark, true, band), false);
  // Inside the band it is whatever it already was — that IS the hysteresis,
  // and it is why the e2e drives sample clear of every mark.
  for (const p of [0.48, 0.49, 0.5, 0.51, 0.52]) {
    assert.equal(latch(p, mark, true, band), true, `held state lost at ${p}`);
    assert.equal(latch(p, mark, false, band), false, `state gained early at ${p}`);
  }
});

test("the deadband absorbs a real oscillation, and cannot outlast the act", () => {
  // THE CONSTANT HAD NO GATE. `ACT_DEADBAND` could be set to 0 and every unit
  // test and every e2e stayed green: the latch test above hardcodes its own
  // band, the marks test only ever subtracts the deadband from a bound (so
  // zeroing it LOOSENS every assertion), and `landing.spec.ts` derives its
  // sample points from the constant, which makes the probes move with it.
  // A zero deadband is a real defect — tempo.ts says why — and it would have
  // shipped with everything passing.
  //
  // So this tests the BEHAVIOUR hysteresis exists for, driven by the constant
  // the product actually uses: cross a mark once, then wobble around it, and
  // the latch must flip exactly once.
  const { ACT_MARKS, ACT_DEADBAND } = readMarks();
  const latch = (progress, mark, current, deadband) =>
    current ? progress > mark - deadband : progress >= mark + deadband;

  const runway = Number(/lg:h-\[(\d+)vh\]/.exec(graph.get(actPath))?.[1]);
  assert.ok(Number.isFinite(runway), "the act's runway height is no longer a literal vh");
  /** The pinned runway in px at a given viewport height. */
  const runwayPx = (viewport) => ((runway - 100) / 100) * viewport;

  /**
   * The jitter this exists to absorb, in px. Scroll anchoring, a trackpad's
   * momentum settling and a resize each move the reported position by tens of
   * pixels; 24 is the small end of that, so a deadband that cannot hold it
   * cannot hold any of them. Every toggle it fails to absorb re-targets a
   * shared-layout animation.
   */
  const JITTER_PX = 24;

  for (const [name, mark] of [
    ["the caption", ACT_MARKS.scene],
    ["the verdict", ACT_MARKS.verdict],
    ["the pane's dock", ACT_MARKS.docked],
  ]) {
    // Both ends of the supported range: the band is a share of the runway, so
    // the px it is worth changes with the viewport and the short one is where
    // it is thinnest.
    for (const viewport of [600, 949]) {
      const jitter = JITTER_PX / runwayPx(viewport);
      // Approach, cross well clear of the band, then wobble on the spot.
      const walk = [mark - 4 * jitter, mark + 4 * jitter];
      for (let i = 0; i < 8; i++) walk.push(mark + (i % 2 ? jitter : -jitter));

      let state = false;
      let flips = 0;
      for (const progress of walk) {
        const next = latch(progress, mark, state, ACT_DEADBAND);
        if (next !== state) flips += 1;
        state = next;
      }
      assert.equal(
        flips,
        1,
        `${name} latched ${flips} times across one crossing and ${JITTER_PX}px of jitter at a ${viewport}-tall viewport — ` +
          `ACT_DEADBAND (${ACT_DEADBAND}) is worth ${Math.round(ACT_DEADBAND * runwayPx(viewport))}px there, and the state chatters`,
      );
      assert.equal(state, true, `${name} did not stay latched after the reader crossed it`);
    }
  }

  // And the other way. The band is deliberately NOT wide enough to outlast the
  // row's travel (tempo.ts: 1.4s at a slow 400px/s is 560px of scroll), because
  // a reader who scrolls a screen-tenth back up SHOULD see the row go home —
  // that reversibility is what the act was rebuilt for. Measured at the tall
  // end, where the band is worth the most px.
  const TRAVEL_PX = 560;
  const widest = ACT_DEADBAND * runwayPx(1080);
  assert.ok(
    widest < TRAVEL_PX,
    `ACT_DEADBAND is worth ${Math.round(widest)}px at a 1080-tall viewport, past the ${TRAVEL_PX}px the row's own travel covers — ` +
      "the act stops reversing and the move can no longer be replayed",
  );
});

test("the camera holds the foot, and re-measures it from the board's box", () => {
  // Measured: the verdict row lands in the offered group at 679-735 of a 783px
  // board, while a head-anchored stage shows 0-552 at a 768-tall viewport and
  // 0-384 at 600. A camera that returns to the head once the pane docks argues
  // "the row opens on the mail that moved it" with the row off-stage at every
  // height, so only the resting scene sits at the head.
  const board = graph.get(marketing("LandingBoard.tsx"));
  assert.ok(board, "LandingBoard.tsx is not in the landing graph");

  // The camera is a continuous mapping now, not a per-beat branch: `engaged`
  // is the scrubbed progress folded with the release latch, computed ONCE and
  // read by the pan, both crop edges and the receipt. One source, so they
  // cannot disagree about where the camera is.
  assert.match(
    board,
    /const engaged = released\.current \? 0 : pan\.current;/,
    "the camera is no longer one continuous value — the pan and the crop fades can now disagree",
  );
  assert.equal(
    (board.match(/const engaged\b/g) ?? []).length,
    1,
    "the camera's fold is computed in more than one place — they will drift",
  );

  // It must re-measure: the board GROWS when the pane docks open (743 to 769),
  // so a height read once would pan to a foot that has since moved.
  assert.ok(
    board.includes("new ResizeObserver"),
    "the camera measures the board once again — the docked pane moves the foot under it",
  );

  // REGRESSION GATE (2026-08-19). It measured `scrollHeight`, and inside the
  // ResizeObserver callback that fires when the pane un-docks the box already
  // reads 743 while the overflow extent still reads 768 — the departing pane
  // is laid out but no longer in the box. The box then stops changing, so
  // nothing ever corrected it: the camera stayed 25px low for the rest of the
  // visit, forward path included, clipping the row the caption points at. At
  // 1512x949 the whole pan is 54px, so that is a 48% error.
  assert.ok(
    !/\.scrollHeight/.test(board),
    "the camera measures `scrollHeight` again — that reads the departing pane and goes stale permanently",
  );
  assert.match(
    board,
    /dolly\.getBoundingClientRect\(\)\.height - stage\.clientHeight \+ OVERLAY_ROOM/,
    "the camera's reach is no longer measured from the board's own box",
  );
});

test("the split verdict stays TWO micro-beats under ONE headline", () => {
  const descent = graph.get(descentPath);
  assert.ok(descent, "ClaimsDescent.tsx is not in the landing graph");
  // The exhibit is sequential or it is nothing: raw first, so the reader feels
  // the preview end, and only then the two verdicts disagreeing. A single
  // `split` screen would turn the page's best moment into an illustration.
  // The exhibit advances raw → split, and it is driven by a LATCH over scroll
  // progress rather than by the enter-only observer this replaced (which could
  // never revert, because `if (!entry.isIntersecting) continue` has no exit
  // branch). Both stages have to be reachable from that one boolean.
  assert.match(
    descent,
    /stage=\{split \? "split" : "raw"\}/,
    "the descent's exhibit no longer advances raw → split under one headline",
  );
  assert.ok(
    descent.includes("latch(") && descent.includes("STAGE_DEADBAND"),
    "the descent's exhibit is no longer driven by a hysteretic latch over scroll progress",
  );
  assert.ok(
    !/isIntersecting\) continue/.test(descent),
    "the enter-only observer is back — it cannot revert, so the last stage would persist forever",
  );
  assert.ok(
    descent.includes("CLAIMS.verdict.raw") && descent.includes("CLAIMS.verdict.split"),
    "the merged claim dropped one of its two micro-beats",
  );
  assert.equal(
    descent.split("CLAIMS.verdict.headline").length - 1,
    1,
    "the merged claim states its headline more than once — that is two claims again",
  );
  // The best sentence on the page, and the reason the first micro-beat exists.
  assert.ok(
    graph.get(copyPath).includes("first two hundred characters being polite"),
    "the polite-preamble sentence is gone from copy.ts",
  );
});

test("the product clip's words add no number, and no claim the page does not make", () => {
  const copySrc = graph.get(copyPath);
  const clip = graph.get(clipPath);
  const descent = graph.get(descentPath);
  assert.ok(clip, "ProductClip.tsx is not in the landing graph — the recording is unmounted");
  assert.ok(descent, "ClaimsDescent.tsx is not in the landing graph");

  // Sliced to the next export rather than to a closing brace: FOOTAGE nests a
  // `rules` block, so `} as const` is not the first `}` in it.
  const start = copySrc.indexOf("export const FOOTAGE");
  assert.ok(start >= 0, "FOOTAGE is gone from copy.ts — the recording's words left the copy file");
  const after = copySrc.slice(start + 1);
  const stop = after.indexOf("\nexport const");
  const block = stop === -1 ? after : after.slice(0, stop);

  const lines = [...block.matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  // Five: the wall label, the clip's two control words, its accessible name
  // and its caption. Fewer means one is gone — or that this slice stopped
  // finding any of them, which would make everything below vacuous.
  assert.ok(lines.length >= 5, `FOOTAGE holds ${lines.length} strings — one of the five is gone`);
  for (const [i, line] of lines.entries()) {
    assert.ok(line.trim().length > 0, `FOOTAGE string ${i} is empty`);
  }

  // NO NEW NUMBER. The clip is placed against the decision claim, one screen
  // from the benchmark: any figure in its own words reads as a second
  // measurement of the same thing. The one number inside the FRAME is this
  // email's confidence, and the caption is what scopes it — so the caption has
  // to keep saying it is not the benchmark above it.
  for (const line of lines) {
    assert.ok(
      !/\d/.test(line),
      `FOOTAGE states a figure ("${line}") — the recording sits beside the benchmark and a number in its words reads as a second measurement`,
    );
  }
  const caption = /caption:\s*"([^"]*)"/.exec(block);
  assert.ok(caption, "FOOTAGE.rules.caption is gone — the clip's numbers are unscoped");
  assert.match(
    caption[1],
    /not the benchmark/,
    "the caption no longer separates the confidence in the frame from the macro-F1 above it — two different quantities, one staging that invites the confusion",
  );

  // AND IT SAYS WHAT IT IS. The board embed on this same page advertises
  // itself as "the shipped board, not a video" (BOARD.live). A thing that IS
  // one has to say so in the page's own voice or that distinction dies.
  const label = /label:\s*"([^"]*)"/.exec(block);
  assert.ok(label, "FOOTAGE.label is gone — the recording no longer declares itself");
  assert.match(
    label[1],
    /record/i,
    `FOOTAGE.label ("${label[1]}") stopped naming the clip a recording — BOARD.live calls the board "not a video", and that contrast is the claim`,
  );

  // The words this test holds are the words that render.
  assert.ok(clip.includes("FOOTAGE.label"), "ProductClip stopped rendering the wall label");
  assert.ok(clip.includes("aria-label={name}"), "the recording lost its text equivalent");
  for (const key of ["FOOTAGE.rules.name", "FOOTAGE.rules.caption"]) {
    assert.ok(descent.includes(key), `ClaimsDescent no longer passes ${key} — the clip's words are elsewhere`);
  }
});

test("the page has a persistent path to its one conversion surface", () => {
  const chrome = graph.get(join(webRoot, "components", "marketing", "chrome.tsx"));
  const sections = graph.get(join(webRoot, "components", "marketing", "sections.tsx"));
  assert.match(chrome, /href=\{ACCESS_ANCHOR\}/, "the nav lost its in-page access anchor");
  assert.match(chrome, /ACCESS_ANCHOR\s*=\s*"#access"/, "the access anchor moved");
  assert.match(
    sections,
    /<SectionShell id="access">/,
    "AccessSection lost the id the nav anchors to — the anchor is dangling on A and C",
  );

  // `/` restages the same ACCESS copy in its spine language (`AccessPhase`),
  // which therefore carries the id there — and must be the ONLY carrier on
  // that page, or the anchor becomes ambiguous. The copy itself still comes
  // from `ACCESS`, so the honesty scans above keep covering it.
  const phase = graph.get(marketing("AccessPhase.tsx"));
  assert.ok(
    phase,
    "AccessPhase.tsx is not in the landing graph — the landing's conversion surface is gone",
  );
  assert.match(phase, /id="access"/, "AccessPhase lost the id the nav anchors to");
  for (const key of ["ACCESS.headline", "ACCESS.cap", "ACCESS.noSeat", "ACCESS.cta"]) {
    assert.ok(phase.includes(key), `AccessPhase stopped rendering ${key} — the restaging rewrote copy`);
  }
  const rootPage = graph.get(ROOT_PAGE);
  assert.ok(rootPage.includes("AccessPhase"), "the landing no longer mounts AccessPhase");
  assert.ok(
    !rootPage.includes("AccessSection"),
    "the landing mounts AccessSection alongside AccessPhase — two #access targets on one page",
  );
});

test("the marketing board sets no prose in mono", () => {
  // The honesty pill ("simulated account · nothing is read") is prose and gets
  // the product's own caps label. Mono means machine value: a path, a hash, a
  // flag, a figure read out of source. This module renders none of those.
  const board = graph.get(join(webRoot, "components", "marketing", "MarketingBoard.tsx"));
  assert.ok(board, "MarketingBoard.tsx is not in the landing graph");
  assert.ok(
    !board.includes("font-mono"),
    "MarketingBoard sets mono — nothing it renders is a machine value",
  );
});

test("every landing keeps the /privacy footer link", () => {
  const chrome = graph.get(join(webRoot, "components", "marketing", "chrome.tsx"));
  assert.ok(chrome, "shared chrome missing from graph");
  assert.ok(
    chrome.includes('href="/privacy"'),
    "the footer lost /privacy — the link Google's OAuth verification checks the homepage for",
  );
  for (const page of PAGES) {
    const src = graph.get(page);
    assert.ok(src.includes("MarketingFooter"), `${rel(page)} dropped the shared footer`);
  }
});

/**
 * Indexing is now a two-sided contract, and both sides can regress silently.
 *
 * The candidates carried `robots: { index: false }` while the choice was open
 * and must keep it: they are near-duplicates of the shipping landing, and a
 * crawlable duplicate of `/` is the one thing this preservation must not cost.
 * The promoted page must carry the opposite — it was `/landing-b`, the
 * `noindex` came with it, and a promotion that forgets to strip it publishes a
 * landing no search engine may list.
 */
test("the candidates stay noindex and the shipping landing does not", () => {
  for (const page of CANDIDATE_PAGES) {
    assert.match(graph.get(page), /index:\s*false/, `${rel(page)} is not noindex`);
  }
  assert.ok(
    !/index:\s*false/.test(graph.get(ROOT_PAGE)),
    "app/page.tsx is noindex — the site's own landing is hidden from search",
  );
});
