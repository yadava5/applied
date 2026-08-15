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
 * lives in copy.ts alone, attributed to the rules stage; no pattern count
 * appears anywhere (the repo holds three conflicting values for that noun);
 * every page is noindex; the footer keeps the /privacy link Google's OAuth
 * verification looks for.
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
  const copyPath = join(webRoot, "components", "marketing", "copy.ts");
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
