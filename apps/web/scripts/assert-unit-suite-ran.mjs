#!/usr/bin/env node
/**
 * Run the unit suite and refuse to pass when it measured nothing.
 *
 * WHY THIS WRAPPER EXISTS. `node --test "tests/unit/**\/*.test.mjs"` exits 0
 * when the glob matches no files at all:
 *
 *     $ node --test "tests/unit/**\/*.nope.mjs"; echo "exit=$?"
 *     tests 0   pass 0   fail 0
 *     exit=0
 *
 * Reproduced the same way by renaming `tests/unit`. So a rename, a moved
 * directory, a changed extension, or a shell that does not expand the glob the
 * way this one does, all turn the largest gate in the web app into a green that
 * asserted nothing — and it looks identical to a real pass in CI logs.
 *
 * This repo already refuses that shape everywhere else. `backend-ci.yml` carries
 * two "Assert the suite actually ran" steps that exit non-zero on
 * `total == 0 or skipped`, and `vercel-ignore-build.yml` a third with an
 * explicit floor (`if total < 38`). The web unit suite was the only gate of its
 * size without one.
 *
 * THE FLOOR IS DELIBERATE AND IS MEANT TO BE RAISED. It is not a target and it
 * is not the current count: it is a tripwire far enough below the real number
 * that ordinary churn never touches it, and high enough that losing whole files
 * cannot slip through. Deleting tests on purpose is fine — lower it in the same
 * commit, and the diff then says out loud that coverage was removed, which is
 * the entire point.
 */
import { spawnSync } from "node:child_process";

/** Well under the real count, so this fires on lost FILES, not on churn. */
const MIN_TESTS = 400;

const child = spawnSync(
  process.execPath,
  ["--test", "tests/unit/**/*.test.mjs"],
  { encoding: "utf8", stdio: ["inherit", "pipe", "inherit"] },
);

// The suite's own output still goes to the terminal: this wrapper adds a
// check, it does not replace the reporter.
process.stdout.write(child.stdout ?? "");

if (child.error) {
  console.error(`\nassert-unit-suite-ran: could not start the runner: ${child.error.message}`);
  process.exit(1);
}

// `node --test`'s TAP-ish summary, e.g. "# tests 473" / "ℹ tests 473".
const read = (label) => {
  const m = (child.stdout ?? "").match(new RegExp(`^[#ℹ]\\s*${label}\\s+(\\d+)$`, "m"));
  return m ? Number(m[1]) : null;
};

const tests = read("tests");
const pass = read("pass");
const fail = read("fail");

// A missing summary is itself a failure: it means the output shape changed and
// every number below would silently read as null. Never treat that as a pass.
if (tests === null || pass === null || fail === null) {
  console.error(
    "\nassert-unit-suite-ran: could not read the run summary from `node --test`.\n" +
      "The reporter's output shape changed, so this gate can no longer see the counts.\n" +
      "Fix the parse rather than removing the check.",
  );
  process.exit(1);
}

if (child.status !== 0 || fail > 0) {
  console.error(`\nassert-unit-suite-ran: ${fail} failing test(s).`);
  process.exit(child.status === 0 ? 1 : child.status);
}

if (tests < MIN_TESTS || pass < MIN_TESTS) {
  console.error(
    `\nassert-unit-suite-ran: the suite reported ${tests} tests (${pass} passing), ` +
      `below the floor of ${MIN_TESTS}.\n` +
      "A zero or collapsed count is indistinguishable from a pass, which is why this " +
      "check exists. Either the glob stopped matching (a rename or a moved directory), " +
      "or test files were removed. If the removal was intended, lower MIN_TESTS in the " +
      "same commit so the diff records it.",
  );
  process.exit(1);
}

console.log(`assert-unit-suite-ran: ${pass}/${tests} passed, floor ${MIN_TESTS}. OK`);
