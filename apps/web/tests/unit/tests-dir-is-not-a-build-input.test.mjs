/**
 * `apps/web/tests/` MUST NOT BE REACHABLE FROM THE APP — it is excluded from
 * the Vercel build allowlist, and this is what keeps that exclusion true.
 *
 * WHY THIS FILE EXISTS (#569).
 *
 * `vercel-ignore-build.sh`'s web allowlist is `apps/web` minus
 * `apps/web/tests`, so a commit whose whole diff sits under this directory
 * deploys nothing. That is the file's only narrowing, and narrowing is its
 * dangerous direction: a wrong SKIP is silent — the site keeps serving the
 * previous build and nothing reports an error — while a wrong BUILD costs one
 * deployment.
 *
 * The exclusion is correct exactly as long as nothing the app ships imports
 * anything from here. Nothing in bash can check that, and nothing in the repo
 * stopped it: a single `import { COMPANIES } from "@/tests/fixtures/…"` in a
 * component would turn this directory into a real build input, and the guard
 * would then skip the deployment of a commit that genuinely changed the
 * bundle. So the invariant is gated here rather than assumed there.
 *
 * IF THIS GATE FIRES, MOVE THE SHARED CODE OUT OF `tests/` — into `lib/` or
 * wherever it belongs. Do not delete the exclusion from the guard, and do not
 * loosen the walk. The whole point is that the answer is not a judgement call.
 *
 * WHAT IS CHECKED, AND THE SHAPE OF THE CONVERSE.
 *
 * Every `.ts` / `.tsx` / `.mjs` / `.js` file under `apps/web` that is NOT under
 * `tests/`, read for static import and re-export specifiers, resolved by the
 * same rules the demo-reachability gate uses (`helpers/importGraph.mjs` owns
 * both the regex and the resolver, so the two gates cannot drift apart). This
 * is stricter than reachability: it does not start from route entrypoints, so
 * a dead module importing a fixture still fires. That is deliberate — the
 * guard's pathspec does not know about reachability either.
 *
 * `await import("@/tests/…")` is NOT followed, for the reason
 * `helpers/importGraph.mjs` documents at length. It is a real hole here and it
 * is worth naming: a dynamic import out of `tests/` would defeat this gate AND
 * make the exclusion wrong. Nobody has a reason to write one; if you find
 * yourself wanting to, that is the signal to move the module.
 *
 * The scan's own ability to see a violation is checked against a synthetic tree
 * below, not assumed from a green run over a repository that has none. A
 * walker that resolved nothing would satisfy the real assertion perfectly.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { resolveSpecifier, staticSpecifiers } from "./helpers/importGraph.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = resolve(HERE, "..", "..");

/** The directory the Vercel guard excludes, as a repo-root-relative path and as
 *  the prefix this gate compares against. Written once so the two readings
 *  cannot disagree. */
const EXCLUDED = "tests";

const SOURCE_EXTENSIONS = [".ts", ".tsx", ".mjs", ".js"];
const NEVER_WALK = new Set(["node_modules", ".next", ".turbo", ".vercel"]);

/** Every source file under `root`, excluding `skip` (a top-level directory name)
 *  and the build/dependency trees. Absolute paths. */
function sourceFiles(root, skip) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (NEVER_WALK.has(entry.name)) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (dir === root && entry.name === skip) continue;
        walk(path);
      } else if (SOURCE_EXTENSIONS.some((ext) => entry.name.endsWith(ext))) {
        out.push(path);
      }
    }
  };
  walk(root);
  return out;
}

/**
 * Every static import in `root` (minus `EXCLUDED`) that resolves to a file
 * inside `EXCLUDED`.
 *
 * @returns {{from: string, spec: string, to: string}[]} repo-relative, sorted.
 */
function importsIntoExcluded(root) {
  const prefix = EXCLUDED + "/";
  const hits = [];
  for (const file of sourceFiles(root, EXCLUDED)) {
    for (const spec of staticSpecifiers(readFileSync(file, "utf8"))) {
      const resolved = resolveSpecifier(spec, file, root);
      if (resolved === null) continue;
      const rel = relative(root, resolved).split("\\").join("/");
      if (rel === EXCLUDED || rel.startsWith(prefix)) {
        hits.push({ from: relative(root, file).split("\\").join("/"), spec, to: rel });
      }
    }
  }
  hits.sort((a, b) => `${a.from} ${a.spec}`.localeCompare(`${b.from} ${b.spec}`));
  return hits;
}

test("no file the app ships imports anything out of apps/web/tests", () => {
  const hits = importsIntoExcluded(WEB_ROOT);
  assert.deepEqual(
    hits,
    [],
    "apps/web/tests is excluded from the Vercel web build allowlist in " +
      "vercel-ignore-build.sh, so a commit touching only that directory does not " +
      "deploy. These imports make that exclusion wrong — the guard would skip a " +
      "deployment of a commit that really did change the bundle, silently. Move " +
      "the shared module out of tests/ rather than removing the exclusion:\n  " +
      hits.map((h) => `${h.from} imports ${JSON.stringify(h.spec)} -> ${h.to}`).join("\n  "),
  );
});

test("the scan looked at the app, not at an empty tree", () => {
  // The assertion above is satisfied by a walk that visits nothing. A floor,
  // not a target: the app is ~400 source files, and this trips long before
  // ordinary churn could reach it.
  const files = sourceFiles(WEB_ROOT, EXCLUDED);
  assert.ok(
    files.length >= 150,
    `only ${files.length} source files under apps/web outside ${EXCLUDED}/. ` +
      "The walk found almost nothing, so its empty result means nothing. A " +
      "renamed directory or a changed extension set is the usual cause.",
  );
  assert.ok(
    files.every((f) => !relative(WEB_ROOT, f).startsWith(EXCLUDED)),
    `the walk reached into ${EXCLUDED}/, which it is supposed to skip`,
  );
});

test("the scan can see a violation when there is one", () => {
  // The directional control. Two synthetic trees, identical except for one
  // import specifier, so the difference in the verdict can only come from the
  // thing being measured.
  const root = mkdtempSync(join(tmpdir(), "tests-not-a-build-input-"));
  try {
    mkdirSync(join(root, "tests", "fixtures"), { recursive: true });
    mkdirSync(join(root, "lib"), { recursive: true });
    mkdirSync(join(root, "components"), { recursive: true });
    writeFileSync(join(root, "tests", "fixtures", "companies.ts"), "export const COMPANIES = [];\n");
    writeFileSync(join(root, "lib", "safe.ts"), "export const SAFE = 1;\n");

    // Clean: the component reads a lib module, and the fixture is imported only
    // from inside tests/ — which is allowed and must not be reported.
    writeFileSync(
      join(root, "components", "Board.tsx"),
      'import { SAFE } from "@/lib/safe";\nexport const Board = () => SAFE;\n',
    );
    writeFileSync(
      join(root, "tests", "board.test.mjs"),
      'import { COMPANIES } from "./fixtures/companies.ts";\nvoid COMPANIES;\n',
    );
    assert.deepEqual(importsIntoExcluded(root), [], "the clean tree must report nothing");

    // Dirty: one alias import out of tests/, and one relative one, which
    // resolve differently and are worth covering separately.
    writeFileSync(
      join(root, "components", "Board.tsx"),
      'import { SAFE } from "@/lib/safe";\nimport { COMPANIES } from "@/tests/fixtures/companies";\n' +
        "export const Board = () => [SAFE, COMPANIES];\n",
    );
    writeFileSync(
      join(root, "lib", "safe.ts"),
      'export { COMPANIES } from "../tests/fixtures/companies.ts";\nexport const SAFE = 1;\n',
    );
    assert.deepEqual(
      importsIntoExcluded(root).map((h) => `${h.from} -> ${h.to}`),
      [
        "components/Board.tsx -> tests/fixtures/companies.ts",
        "lib/safe.ts -> tests/fixtures/companies.ts",
      ],
      "the scan missed an import out of tests/, so its verdict on the real tree is worthless",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the exclusion this gate defends is still spelled the way the guard spells it", () => {
  // If the pathspec is ever renamed or re-scoped, this file is defending a
  // directory nothing excludes any more — green, and pointless. The guard is
  // the owner of the string; this only refuses to drift away from it silently.
  const guard = readFileSync(resolve(WEB_ROOT, "..", "..", "vercel-ignore-build.sh"), "utf8");
  assert.ok(
    guard.includes(`':!apps/web/${EXCLUDED}'`),
    `vercel-ignore-build.sh no longer excludes apps/web/${EXCLUDED} from the web ` +
      "allowlist. Either the exclusion moved — point this gate at the new one — " +
      "or it was removed, in which case this file has nothing left to defend and " +
      "should go in the same commit.",
  );
});
