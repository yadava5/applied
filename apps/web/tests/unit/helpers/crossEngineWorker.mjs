/**
 * The TypeScript half of the cross-engine differential (#427 item 2).
 *
 * Reads a JSON array of cases on stdin, writes one JSON verdict per line on
 * stdout, and is driven by `scripts/cross_engine_differential.py`. It is not a
 * test and deliberately carries no assertions: the comparison lives in one
 * place, on the Python side, so there is exactly one definition of what
 * "diverged" means.
 *
 * WHY A WORKER AND NOT A `node --test` SUITE. `pnpm test:unit` runs under
 * `frontend-ci.yml`, which sets up node and nothing else. A differential
 * assertion there has two possible shapes and both are bad: it either fails
 * hard because there is no Python, reddening a required check for a reason
 * that is not a defect, or it detects the missing interpreter and skips — and
 * a skipped test is collected, reported, and green. So this carries no
 * assertions and is not collected: the suite glob at
 * `scripts/assert-unit-suite-ran.mjs` is `tests/unit/**\/*.test.mjs`, and this
 * file is a `.mjs` that is not a `.test.mjs`, exactly like `appModule.mjs`
 * beside it.
 *
 * WHY IT LIVES UNDER `tests/` AND NOT IN `apps/web/scripts/`, which is where it
 * was first written. `tests-dir-is-not-a-build-input.test.mjs` asserts that no
 * file the app SHIPS imports anything out of `apps/web/tests/`, and it caught
 * this: `vercel-ignore-build.sh` narrows its deploy-trigger path set with
 * `':!apps/web/tests'` and that exclusion is the file's only narrowing, so
 * `apps/web/scripts/` is inside the trigger set while `tests/` is outside it. A
 * shipped-path module importing `appModule.mjs` would have made the excluded
 * tree a build input in fact while the ignore script still treated it as not
 * one. The dependency is real and one-directional — this worker needs the
 * loader hooks — so the worker moves to the loader, not the reverse.
 *
 * ONE PROCESS FOR THE WHOLE CORPUS. Module load — the loader hooks, the
 * TypeScript type-strip, compiling 220 regexes out of `rules.json` — costs far
 * more than classifying a case, so spawning per case would measure startup.
 *
 * ERRORS ARE NOT VERDICTS. A case that throws aborts the process with a
 * non-zero status. It must never be reported as `other` / 0.5, because the
 * Python engine answers `other` / 0.5 for anything that does not score: an
 * error rendered as that value would read as agreement, and a dead worker
 * would print a clean bill of health for both engines at once.
 */
import { importApp } from "./appModule.mjs";

const { classifyWithRules } = await importApp("lib/demo/rulesLayer.ts");

if (typeof classifyWithRules !== "function") {
  console.error("crossEngineWorker: rulesLayer.ts did not export classifyWithRules");
  process.exit(2);
}

/** Read all of stdin. */
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

const raw = await readStdin();
if (!raw.trim()) {
  console.error("crossEngineWorker: stdin was empty — no cases to classify");
  process.exit(2);
}

let cases;
try {
  cases = JSON.parse(raw);
} catch (err) {
  console.error(`crossEngineWorker: stdin was not JSON: ${err.message}`);
  process.exit(2);
}

if (!Array.isArray(cases) || cases.length === 0) {
  console.error("crossEngineWorker: expected a non-empty JSON array of cases");
  process.exit(2);
}

const out = [];
for (const c of cases) {
  let verdict;
  try {
    // The engine's signature is (subject, body, sender). NOTHING IS COERCED
    // here, and nothing is coerced on the driver's side either: it asserts both
    // corpora are free of nulls in a scored field rather than mapping them to
    // "". A quiet coercion at this seam would answer #427 item 1's question
    // ("what does each engine do with a null?") on the engines' behalf, and the
    // sender is passed through as `null` because both engines accept one.
    verdict = classifyWithRules(c.subject, c.body, c.sender ?? null);
  } catch (err) {
    // Abort, do not substitute. See the header.
    console.error(
      `crossEngineWorker: case ${JSON.stringify(c.id)} threw: ${err && err.stack ? err.stack : err}`,
    );
    process.exit(3);
  }
  out.push(
    JSON.stringify({ id: c.id, category: verdict.category, confidence: verdict.confidence }),
  );
}

process.stdout.write(out.join("\n") + "\n");
