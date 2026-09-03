/**
 * Run Playwright, then refuse a run that selected tests and executed none.
 *
 * WHY (#402). This reports success and tests nothing:
 *
 *     $ npx playwright test tests/e2e/landing.spec.ts --reporter=line
 *     24 skipped
 *     $ echo $?
 *     0
 *
 * Twenty-four tests skipped, exit 0. The same command with
 * PLAYWRIGHT_PROD_BUILD=1 does 24 tests of real work. The switch is
 * documented in exactly one place, `.github/workflows/e2e-ci.yml`, and
 * nowhere a person looks first.
 *
 * CI IS NOT THE HOLE and this must not be filed as if it were. The
 * `playwright (production build)` job sets the variable, so the landing, boot
 * and production specs all run there. The gate is also right in intent:
 * `next dev` has produced false reds on this page's geometry, and the skip
 * exists to stop anyone measuring the wrong build.
 *
 * The defect is the LOCAL failure mode. Someone verifying a landing change
 * runs the obvious command, sees green, and concludes the geometry gates held.
 * They did not run. That is this estate's signature defect shape, and the
 * answer that has worked before is a wrapper that refuses a collapsed count:
 * `assert-unit-suite-ran.mjs` does the same job for `node --test`.
 *
 * WHAT IT DOES NOT DO, so nobody expects more of it: it does not object to
 * SOME tests skipping. The 13 session-gated tests skip by design until a
 * seeded account exists (`tests/e2e/session.ts` explains at length), and the
 * prod-build specs skip correctly in the dev-server job. Only a run where
 * EVERY selected test skipped is a run that proved nothing, and that is the
 * only thing asserted here.
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const jsonPath = join(tmpdir(), `playwright-run-${process.pid}.json`);

const child = spawnSync(
  "npx",
  ["playwright", "test", ...args, "--reporter=line,json"],
  {
    stdio: "inherit",
    env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_NAME: jsonPath },
  },
);

if (!existsSync(jsonPath)) {
  // No report to read. Say so rather than inventing a verdict from the exit
  // code: a wrapper that silently passes through when its own evidence is
  // missing is the failure it exists to prevent.
  console.error(
    "\nassert-e2e-ran: playwright wrote no JSON report, so this wrapper cannot\n" +
      "tell a real run from a run that skipped everything. Passing the exit code\n" +
      `through unchecked (${child.status}).\n`,
  );
  process.exit(child.status ?? 1);
}

const report = JSON.parse(readFileSync(jsonPath, "utf8"));
rmSync(jsonPath, { force: true });

const counts = { expected: 0, unexpected: 0, flaky: 0, skipped: 0 };
const skippedTitles = [];

function visit(suite) {
  for (const spec of suite.specs ?? []) {
    for (const test of spec.tests ?? []) {
      const status = test.status ?? "skipped";
      if (status in counts) counts[status] += 1;
      if (status === "skipped") skippedTitles.push(spec.title);
    }
  }
  for (const child of suite.suites ?? []) visit(child);
}
for (const suite of report.suites ?? []) visit(suite);

const ran = counts.expected + counts.unexpected + counts.flaky;
const total = ran + counts.skipped;

if (total > 0 && ran === 0) {
  const prodBuildSkips = (report.suites ?? []).length > 0 && needsProdBuild(report);
  console.error(
    `\nassert-e2e-ran: ${counts.skipped} test(s) selected, 0 executed. This run is not\n` +
      "evidence of anything, and it was about to exit 0.\n" +
      (prodBuildSkips
        ? "\nEvery skip names PLAYWRIGHT_PROD_BUILD. These specs measure geometry and\n" +
          "boot behaviour that `next dev` gets wrong, so they only run against a real\n" +
          "build. Do this:\n\n" +
          "    pnpm build && PORT=3210 pnpm start &\n" +
          "    PLAYWRIGHT_BASE_URL=http://localhost:3210 pnpm e2e:prod <files>\n"
        : "\nFirst few skipped:\n  " + skippedTitles.slice(0, 5).join("\n  ") + "\n") +
      "\nIf skipping really is correct here, run playwright directly rather than\n" +
      "through this wrapper.\n",
  );
  process.exit(1);
}

// The verdict is only ever about whether the run HAPPENED. Playwright owns
// whether it passed, and saying "OK" beside "1 failed" would read as this
// wrapper overruling it.
const verdict = counts.unexpected > 0 ? "the run is real; playwright failed it" : "OK";
console.log(
  `assert-e2e-ran: ${ran} executed (${counts.unexpected} failed, ${counts.flaky} flaky), ` +
    `${counts.skipped} skipped. ${verdict}`,
);
// WHY THE SKIPS ARE ITEMISED (#599). A bare "29 skipped" sitting next to "OK"
// reads as a passing suite, and 29 of these are the entire signed-in half —
// they skip for want of credentials and have never run in CI. The count alone
// has already been misread as coverage. Naming the reason costs one line and
// makes the green say what it actually covers.
if (counts.skipped > 0) {
  const byReason = skipReasons();
  for (const [reason, n] of byReason) {
    console.log(`  skipped: ${n} — ${reason}`);
  }
}
process.exit(child.status ?? 0);

/** True when every skip in the report carries the prod-build reason. */
function needsProdBuild(report) {
  const reasons = [];
  const collect = (suite) => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests ?? []) {
        if ((test.status ?? "skipped") !== "skipped") continue;
        for (const annotation of test.annotations ?? []) {
          reasons.push(String(annotation.description ?? ""));
        }
      }
    }
    for (const child of suite.suites ?? []) collect(child);
  };
  for (const suite of report.suites ?? []) collect(suite);
  return reasons.length > 0 && reasons.every((r) => r.includes("PLAYWRIGHT_PROD_BUILD"));
}

/** Skip counts grouped by their annotation reason, most common first. */
function skipReasons() {
  const tally = new Map();
  const note = (reason) => tally.set(reason, (tally.get(reason) ?? 0) + 1);
  const collect = (suite) => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests ?? []) {
        if ((test.status ?? "skipped") !== "skipped") continue;
        const described = (test.annotations ?? [])
          .map((a) => String(a.description ?? "").trim())
          .filter(Boolean);
        // An unannotated skip is the one worth surfacing loudest: nothing says
        // why it did not run, so it cannot be told from a test that was quietly
        // disabled.
        note(described.length > 0 ? described.join("; ") : "no reason recorded");
      }
    }
    for (const child of suite.suites ?? []) collect(child);
  };
  for (const suite of report.suites ?? []) collect(suite);
  return [...tally.entries()].sort((a, b) => b[1] - a[1]);
}
