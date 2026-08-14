#!/usr/bin/env node
/**
 * Count the tests that did not run for want of an authenticated Supabase
 * session, and say so where an operator will actually see it.
 *
 * WHY (#188). Four spec files hold 13 tests behind `requireSession()`
 * (`tests/e2e/session.ts`). Both e2e jobs boot the app against a placeholder
 * Supabase project, so all 13 skip on every run — and a skip is green. PR #184
 * merged with none of them having executed and every check passing. The harm
 * was never the skip itself (there is no seeded test account yet, and minting
 * one is the owner's decision); the harm was that the NUMBER was invisible.
 * This writes it into `$GITHUB_STEP_SUMMARY`, which renders in the PR checks UI
 * without anyone opening a log.
 *
 * WHY THE JSON AND NOT A GREP. Playwright's `list` reporter prints a skipped
 * test's title and nothing else, so grepping its output would mean counting
 * lines of prose written for humans and re-counting them differently the day
 * the reporter's formatting changes. The JSON reporter carries each test's
 * status AND the skip annotation's description, so the count is derived from
 * the run's own record. It also gets RETRIES right: under `E2E_REQUIRE_SESSION=1`
 * these tests FAIL, CI sets `retries: 2`, and each failing test therefore
 * produces three result entries — a grep would report 3n. This counts tests.
 *
 * THIS SCRIPT MUST NEVER FAIL THE JOB. It is a census, not a gate; the gate is
 * `E2E_REQUIRE_SESSION`. Every path exits 0, including a missing or malformed
 * results file — but a missing file is reported LOUDLY rather than counted as
 * zero, because "0 skips" and "the census never ran" look identical otherwise,
 * and this repo has shipped that exact defect more than once.
 *
 * IT COUNTS ONE GATE, ON PURPOSE. A dev-server run skips 25 tests, but only 13
 * of them are this class; the other 12 are `production.spec.ts` waiting on
 * `PLAYWRIGHT_PROD_BUILD`, which the production job sets, so those 12 run and
 * pass there. Matching on the prefix rather than on "status === skipped" is
 * what makes the published number 13 on BOTH jobs instead of 25 on one and 13
 * on the other. A total that changes meaning between jobs is worse than none.
 *
 * Usage: node scripts/no-session-census.mjs <results.json> [job label]
 */
import { appendFileSync, readFileSync } from "node:fs";

/**
 * Byte-identical to `NO_SESSION_SKIP_PREFIX` in `tests/e2e/session.ts`. If you
 * change it there, change it here in the same commit: a census that matches
 * nothing reports 0, and 0 reads like good news.
 */
const PREFIX = "E2E_NO_SESSION_SKIP (#188):";

const resultsPath = process.argv[2] ?? "test-results/results.json";
const label = process.argv[3] ?? "playwright";

/** Emit to the GitHub step summary when there is one, and always to stdout. */
function report(lines) {
  const text = `${lines.join("\n")}\n`;
  process.stdout.write(text);
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (!summary) return;
  try {
    appendFileSync(summary, text);
  } catch (err) {
    process.stdout.write(`(could not write the step summary: ${String(err)})\n`);
  }
}

/** Every `test` object in the report, flattened out of the suite tree. */
function collectTests(node, out) {
  for (const suite of node.suites ?? []) collectTests(suite, out);
  for (const spec of node.specs ?? []) {
    for (const test of spec.tests ?? []) out.push({ spec, test });
  }
  return out;
}

const carriesPrefix = (text) => typeof text === "string" && text.includes(PREFIX);

/**
 * The SECOND, prefix-independent signal — the guard on the guard.
 *
 * `PREFIX` above is a copy of a string that lives in another file, so it can
 * drift, and the failure mode of a drifted census is the worst kind: it matches
 * nothing, reports 0, and 0 reads as good news. So the census also counts the
 * same tests by WHERE the skip came from. Playwright records each annotation's
 * origin — `annotations[].location.file` is the module that called
 * `test.skip()`, which for this class is always `tests/e2e/session.ts` — and
 * that path cannot drift out of agreement with the prefix silently, because the
 * two counts are compared below and a mismatch is reported loudly instead of
 * quietly becoming a zero.
 */
const HELPER = "tests/e2e/session.ts";
const fromHelper = (loc) => typeof loc?.file === "string" && loc.file.endsWith(HELPER);

function main() {
  let report_;
  try {
    report_ = JSON.parse(readFileSync(resultsPath, "utf8"));
  } catch (err) {
    // NOT counted as zero. A census that could not run is a different fact
    // from a census that found nothing, and conflating them is how a check
    // stops being able to fail.
    report([
      `### ⚠️ no-session census (${label}) could not run`,
      "",
      `Could not read \`${resultsPath}\`: ${String(err)}`,
      "",
      "The JSON reporter is configured in `apps/web/playwright.config.ts` and only",
      "under `CI`. If Playwright crashed before writing a report this is expected;",
      "otherwise the census is blind and the count below is missing, not zero.",
      "See issue #188.",
    ]);
    return;
  }

  const all = collectTests(report_, []);
  let skipped = 0;
  let failed = 0;
  // The cross-check: the same tests, counted by where the skip was raised
  // rather than by what it said.
  let skippedByOrigin = 0;

  for (const { test } of all) {
    const annotations = test.annotations ?? [];
    const results = test.results ?? [];
    const wasSkipped = results.some((r) => r.status === "skipped");

    if (wasSkipped && annotations.some((a) => fromHelper(a.location))) skippedByOrigin += 1;

    if (wasSkipped && annotations.some((a) => carriesPrefix(a.description))) {
      skipped += 1;
      continue;
    }
    const erroredOnSession = results.some((r) =>
      [...(r.errors ?? []), ...(r.error ? [r.error] : [])].some(
        (e) => carriesPrefix(e.message) || carriesPrefix(e.value),
      ),
    );
    if (erroredOnSession) failed += 1;
  }

  const enforcing = process.env.E2E_REQUIRE_SESSION === "1";
  const lines = [`### Session-gated e2e coverage (${label})`, ""];

  // The token drifted: `${HELPER}` skipped tests the prefix could not see. Say
  // so instead of publishing a number that is wrong in the reassuring direction.
  if (skippedByOrigin !== skipped) {
    report([
      `### ⚠️ no-session census (${label}) is out of sync — do not trust the count`,
      "",
      `Counted by the reason prefix: **${skipped}**.`,
      `Counted by the skip's origin (\`${HELPER}\`): **${skippedByOrigin}**.`,
      "",
      "These must agree. They do not, which means `NO_SESSION_SKIP_PREFIX` in",
      `\`apps/web/${HELPER}\` no longer matches the copy in this script, or a skip is`,
      "being raised from that file by some other path. Reconcile the two before reading",
      "any number here — a prefix that matches nothing reports 0, and 0 looks like good",
      "news. See issue #188.",
    ]);
    return;
  }

  if (all.length === 0) {
    // Zero TESTS is not a legitimate outcome of a run that produced a report;
    // it means the report was empty and the count below means nothing.
    lines.push(
      `⚠️ The report at \`${resultsPath}\` contains no tests, so the count below is`,
      "vacuous rather than good news. See issue #188.",
      "",
    );
  }

  lines.push(
    `- **${skipped}** of ${all.length} tests did not run: no authenticated Supabase session.`,
    `- **${failed}** tests FAILED for the same reason (enforcement is ${
      enforcing ? "**on**" : "off"
    }).`,
  );

  if (skipped > 0 && !enforcing) {
    lines.push(
      "",
      `Those ${skipped} tests are green because they were skipped, not because they passed.`,
      "They cover the signed-in app shell, Settings, the dashboard and filing an",
      "application — the half of the product CI has never exercised (issue #188). Closing",
      "the gap needs a seeded test account; until one exists, set the repository variable",
      "`E2E_REQUIRE_SESSION` to `1` to turn every one of these skips into a hard failure.",
    );
  } else if (skipped === 0 && failed === 0 && all.length > 0) {
    lines.push(
      "",
      "No test was blocked by a missing session in this run — either a session was",
      "reachable, or no session-gated test was selected.",
    );
  }

  report(lines);
}

try {
  main();
} catch (err) {
  // Belt and braces: nothing this script can do is worth a red job.
  report([`### ⚠️ no-session census (${label}) crashed`, "", String(err)]);
}
