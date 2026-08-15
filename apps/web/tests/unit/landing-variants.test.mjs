/**
 * The landing candidates can never touch a real account — and their claims
 * stay attributed.
 *
 * WHAT THE CONTRACT IS. `PipelineBoard`'s `transport` prop DEFAULTS to
 * `liveBoardTransport` (lib/dashboard/transport.ts), which PATCHes
 * /api/applications/*. A marketing embed that forgets to pass the demo
 * transport does not error — in a signed-in owner's browser (localhost serves
 * real production data) dragging a row on the landing page would mutate a
 * real account. So this test walks the real import graph from each candidate
 * page and holds three lines:
 *
 *   1. no module under app/landing-* / components/marketing names
 *      `liveBoardTransport` at all;
 *   2. every `<PipelineBoard …>` reachable from a candidate passes an
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
 * it names exists on disk; every page is noindex; the footer keeps the
 * /privacy link Google's OAuth verification looks for.
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

const PAGES = ["landing-a", "landing-b", "landing-c"].map((dir) =>
  join(webRoot, "app", dir, "page.tsx"),
);

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
const isLandingModule = (file) =>
  rel(file).startsWith("app/landing-") || rel(file).startsWith("components/marketing/");

const marketing = (name) => join(webRoot, "components", "marketing", name);
const copyPath = marketing("copy.ts");
const actPath = marketing("WindowAct.tsx");
const descentPath = marketing("ClaimsDescent.tsx");
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

test("the window act captions every beat — beat 0 is never wordless", () => {
  const act = graph.get(actPath);
  assert.ok(act, "WindowAct.tsx is not in the landing graph");
  const block = /captions:\s*\[([\s\S]*?)\]/.exec(graph.get(copyPath));
  assert.ok(block, "ACT.captions is gone — the act's scenes have no words");
  const captions = [...block[1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  const beats = [...act.matchAll(/data-beat=\{(\d+)\}/g)].map((m) => Number(m[1]));
  assert.deepEqual(beats, [0, 1, 2], "the act's sentinel beats changed");
  assert.equal(
    captions.length,
    beats.length,
    "every beat needs its own caption — an uncaptioned beat is the dead dwell this fixed",
  );
  for (const [i, line] of captions.entries()) {
    assert.ok(line.trim().length > 0, `caption ${i} is empty`);
  }
  assert.ok(act.includes("ACT.captions"), "WindowAct stopped rendering the captions");
  // Scene 0 revisited: the camera comes back when the reader scrolls up, the
  // verdict does not, and the opening line would then be describing a board
  // that has already moved.
  assert.match(
    graph.get(copyPath),
    /settled:\s*"[^"]+"/,
    "ACT.settled is gone — scene 0's opening line would sit over a moved board",
  );
  assert.ok(act.includes("ACT.settled"), "WindowAct stopped using scene 0's revisited line");
  // The revisit line has to be addressed by the scene COUNT. Indexed off the
  // rendered array's length instead, a fourth scene would silently retarget
  // the revisit at that scene's caption and this whole test would stay green.
  assert.match(
    act,
    /SETTLED\s*=\s*ACT\.captions\.length/,
    "the revisited line is no longer addressed by the scene count — a fourth scene would hide it",
  );
});

test("beat 0's zone outlasts the pin", () => {
  // Derived in WindowAct's docblock: beat 1 fires when the sentinel band
  // (rootMargin -45%/-45%, so at 0.55vh) reaches zone 1's top, and the window
  // pins at 4.5rem. If h0·H is not greater than 0.55vh − 4.5rem, the verdict
  // lands while the window is still travelling. 4.5rem is smallest as a share
  // of the tallest viewport this is designed for (72/900 ≈ 0.08), so 47vh is
  // the floor that holds everywhere.
  const act = graph.get(actPath);
  const runway = Number(/lg:h-\[(\d+)vh\]/.exec(act)?.[1]);
  assert.ok(Number.isFinite(runway), "the act's runway height is no longer a literal vh");
  const shares = [...act.matchAll(/data-beat=\{\d+\}\s+className="h-\[(\d+)%\]"/g)].map((m) =>
    Number(m[1]),
  );
  assert.equal(shares.length, 3, "the act no longer has three percentage sentinel zones");
  assert.equal(
    shares.reduce((a, b) => a + b, 0),
    100,
    "the sentinel zones no longer tile the runway",
  );
  assert.ok(
    (shares[0] * runway) / 100 > 47,
    `beat 0 owns ${(shares[0] * runway) / 100}vh — under 47vh the verdict lands on an unpinned window`,
  );
});

test("the split verdict stays TWO micro-beats under ONE headline", () => {
  const descent = graph.get(descentPath);
  assert.ok(descent, "ClaimsDescent.tsx is not in the landing graph");
  // The exhibit is sequential or it is nothing: raw first, so the reader feels
  // the preview end, and only then the two verdicts disagreeing. A single
  // `split` screen would turn the page's best moment into an illustration.
  assert.match(
    descent,
    /const STAGES[^=]*=\s*\[\s*"raw",\s*"split",/,
    "the descent's first two sentinels no longer run raw → split",
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

test("the page has a persistent path to its one conversion surface", () => {
  const chrome = graph.get(join(webRoot, "components", "marketing", "chrome.tsx"));
  const sections = graph.get(join(webRoot, "components", "marketing", "sections.tsx"));
  assert.match(chrome, /href=\{ACCESS_ANCHOR\}/, "the nav lost its in-page access anchor");
  assert.match(chrome, /ACCESS_ANCHOR\s*=\s*"#access"/, "the access anchor moved");
  assert.match(
    sections,
    /<SectionShell id="access">/,
    "AccessSection lost the id the nav anchors to — the anchor is dangling",
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

test("every candidate is noindex and keeps the /privacy footer link", () => {
  const chrome = graph.get(join(webRoot, "components", "marketing", "chrome.tsx"));
  assert.ok(chrome, "shared chrome missing from graph");
  assert.ok(
    chrome.includes('href="/privacy"'),
    "the footer lost /privacy — the link Google's OAuth verification checks the homepage for",
  );
  for (const page of PAGES) {
    const src = graph.get(page);
    assert.match(src, /index:\s*false/, `${rel(page)} is not noindex`);
    assert.ok(src.includes("MarketingFooter"), `${rel(page)} dropped the shared footer`);
  }
});
