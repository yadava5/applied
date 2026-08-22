#!/usr/bin/env node
/**
 * Run the unit suite and refuse to pass when it measured nothing — and keep the
 * evidence when it fails.
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
 *
 * ---------------------------------------------------------------------------
 * WHY THIS SCRIPT NO LONGER REPLAYS THE RUNNER'S OUTPUT (#433).
 *
 * It used to capture the whole run with `spawnSync(..., stdio: "pipe")` and
 * replay it in one `process.stdout.write(child.stdout)` before calling
 * `process.exit()`. On CI that destroyed most of the log, including the names
 * of the tests that had just failed. #433 is the run where it cost us: the gate
 * correctly reported `1 failing test(s).` and the failing test's name was not
 * anywhere in the 2,017-line log, so the failure was unattributable and a
 * re-run went green.
 *
 * MEASURED CAUSE, not inferred. A write larger than the pipe buffer cannot
 * complete synchronously — the kernel accepts one buffer's worth and Node
 * queues the rest on the stream. `process.exit()` then tears the process down
 * with that queue still pending, so the remainder is discarded. Two one-liners
 * on CI's exact runtime (`node:22`, Linux), with the pipe on the same host so
 * no other layer is in the path:
 *
 *     node -e 'process.stdout.write("x".repeat(300000)); process.exit(0)' | wc -c
 *     -> 65536          # exactly one Linux pipe buffer
 *     node -e 'process.stdout.write("x".repeat(300000))'                  | wc -c
 *     -> 300000         # same write, no process.exit(), nothing lost
 *
 * And on the real suite, the whole gate under `node:22` on Linux: stdout cut at
 * exactly 65536 bytes, mid-word, on a run where the capture itself was intact
 * (`child.stdout.length` was 116,487 and did contain the failing test's name).
 * The bytes died on the way out, not on the way in.
 *
 * THE CONTROL THAT MISSED IT. #433 records an earlier attempt to reproduce this
 * that came back clean — `writeSync` and `process.stdout.write` both produced
 * 696 lines with the failing name intact — and the theory was dropped as
 * disproven. That control ran on macOS, where the pipe buffer is 131072, and it
 * emitted about 37 KB. It never crossed a buffer boundary, so it could not have
 * shown the defect on any platform. The size of the write IS the variable; a
 * control that holds it below the buffer measures nothing.
 *
 * THE FIX IS TO STOP MOVING THE BYTES THROUGH THIS PROCESS. The runner now
 * writes its human-readable output straight to our inherited stdout (`stdio:
 * "inherit"`), so there is no giant string for us to replay and nothing queued
 * on our streams. A second reporter writes machine-readable TAP to a temp file,
 * which is what we parse — a file cannot be truncated by a pipe buffer, so the
 * parse input is always complete however many subtests ran.
 *
 * Two further belts, because the cost of being wrong here is a blind failure:
 *
 *   1. Every failing test's name AND its error payload (the assertion diff,
 *      the location, the stack) are re-printed as a compact block at the very
 *      end, on stderr. stderr is the channel that empirically survived the
 *      truncation in #433 — the `assert-unit-suite-ran: 1 failing test(s).`
 *      line reached the log while the surrounding stdout did not — and the
 *      block is deliberately capped so it stays small enough to survive a
 *      buffer's worth on its own.
 *   2. This script sets `process.exitCode` and returns instead of calling
 *      `process.exit()`. Node then drains its streams before exiting, which is
 *      the actual root-cause fix rather than a workaround for it.
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Well under the real count, so this fires on lost FILES, not on churn. */
const MIN_TESTS = 400;

/**
 * Caps on the durable failure block. The whole point of that block is that it
 * survives whatever truncates the bulk output, so it must not itself grow into
 * something a pipe buffer can cut. A suite that fails 300 tests has a problem
 * the first 25 names already describe.
 */
const MAX_FAILURES_REPORTED = 25;
const MAX_PAYLOAD_LINES = 30;

/**
 * How much of the raw TAP to dump when we cannot attribute a failure to a named
 * test — a runner that died mid-suite, or a summary we could not read.
 *
 * WHY THIS EXISTS AT ALL. The TAP lives in a temp dir that this script deletes
 * on the way out, and on CI the whole runner is thrown away seconds later, so
 * printing the file's *path* preserves nothing. If the evidence is not on
 * stderr before we return, it is gone — which is #433's failure mode wearing a
 * different hat, and it is candidate (3) from that issue (a genuine crash
 * mid-suite) landing in the one branch that has no names to print.
 */
const MAX_TAIL_LINES = 40;

/**
 * Pull every failing test out of a TAP 13 stream, with its diagnostic payload.
 *
 * Shape we are reading, straight from `node --test --test-reporter=tap`:
 *
 *     not ok 490 - the canary that must be named in the output
 *       ---
 *       duration_ms: 1.036291
 *       location: '/w/tests/unit/zz-canary.test.mjs:7:1'
 *       failureType: 'testCodeFailure'
 *       error: |-
 *         Expected values to be strictly equal:
 *         + actual - expected
 *       ...
 *
 * A parent whose only sin is that something under it failed carries
 * `failureType: 'subtestsFailed'`. Those are dropped: they repeat a file or
 * describe-block name and push the actual leaf failures out of the cap.
 */
const parseFailures = (tap) => {
  const lines = tap.split("\n");
  const failures = [];

  for (let i = 0; i < lines.length; i++) {
    const header = /^(\s*)not ok (\d+) - (.*)$/.exec(lines[i]);
    if (!header) continue;

    const [, indent, number, name] = header;
    const payload = [];

    // The YAML diagnostic block is optional and is indented two spaces past
    // the `not ok` it belongs to, opening on `---` and closing on `...`.
    if (lines[i + 1] === `${indent}  ---`) {
      let j = i + 2;
      for (; j < lines.length && lines[j] !== `${indent}  ...`; j++) {
        payload.push(lines[j].slice(indent.length + 2));
      }
      i = j;
    }

    if (payload.some((line) => line.startsWith("failureType: 'subtestsFailed'"))) continue;
    failures.push({ number, name, payload });
  }

  return failures;
};

/**
 * Print the failing names and their diffs, last, on stderr. Anything that
 * truncates the run's bulk output leaves this readable.
 */
const reportFailures = (failures) => {
  if (failures.length === 0) return;

  const shown = failures.slice(0, MAX_FAILURES_REPORTED);
  const parts = [
    "",
    "=".repeat(72),
    `assert-unit-suite-ran: ${failures.length} failing test(s), named below.`,
    "=".repeat(72),
  ];

  for (const { number, name, payload } of shown) {
    parts.push("", `FAILED  #${number}  ${name}`);
    const body = payload.slice(0, MAX_PAYLOAD_LINES);
    for (const line of body) parts.push(`    ${line}`);
    if (payload.length > body.length) {
      parts.push(`    … ${payload.length - body.length} more line(s) of this payload above.`);
    }
  }

  if (failures.length > shown.length) {
    parts.push("", `… and ${failures.length - shown.length} further failing test(s).`);
  }
  parts.push("=".repeat(72));

  console.error(parts.join("\n"));
};

/**
 * Last resort: dump the tail of the raw TAP when no failing test could be
 * named. Where `reportFailures` answers "which test", this answers "how far did
 * it get before it stopped", which is the only question left when the runner
 * dies partway through and never writes a summary.
 */
const reportTapTail = (tap, why) => {
  const lines = tap.split("\n").filter((line) => line.length > 0);
  const tail = lines.slice(-MAX_TAIL_LINES);
  const parts = [
    "",
    "=".repeat(72),
    `assert-unit-suite-ran: ${why}`,
    `Last ${tail.length} line(s) of the run's TAP, which is all the evidence there is:`,
    "=".repeat(72),
  ];
  if (tail.length === 0) parts.push("(the runner wrote no TAP at all)");
  else for (const line of tail) parts.push(`    ${line}`);
  parts.push("=".repeat(72));

  console.error(parts.join("\n"));
};

const main = () => {
  const tapDir = mkdtempSync(join(tmpdir(), "assert-unit-suite-"));
  const tapPath = join(tapDir, "run.tap");

  try {
    // `stdio: "inherit"` is load-bearing: the runner writes to the real stdout
    // and stderr directly, so nothing is buffered in this process and nothing
    // can be lost when it exits. `spec` is named explicitly rather than left to
    // default so the output shape is the same locally and on CI — the default
    // is TTY-dependent (`spec` on a terminal, `tap` on a pipe), which is how a
    // failure-parse can be written against one shape and meet the other in CI.
    const child = spawnSync(
      process.execPath,
      [
        "--test",
        "--test-reporter=spec",
        "--test-reporter-destination=stdout",
        "--test-reporter=tap",
        `--test-reporter-destination=${tapPath}`,
        "tests/unit/**/*.test.mjs",
      ],
      { encoding: "utf8", stdio: "inherit" },
    );

    if (child.error) {
      console.error(`\nassert-unit-suite-ran: could not start the runner: ${child.error.message}`);
      return 1;
    }

    let tap = "";
    try {
      tap = readFileSync(tapPath, "utf8");
    } catch (err) {
      console.error(
        `\nassert-unit-suite-ran: the runner wrote no TAP to ${tapPath} (${err.code ?? err.message}).\n` +
          "This gate asks `node --test` for two reporters at once; if this Node does not\n" +
          "support the paired --test-reporter / --test-reporter-destination flags, that is\n" +
          "the first thing to check. Fix the invocation rather than removing the check.",
      );
      return 1;
    }

    // `node --test`'s TAP summary, e.g. "# tests 489" (the `ℹ` variant is what
    // the spec reporter emits; accepted too so this survives a reporter swap).
    const read = (label) => {
      const m = tap.match(new RegExp(`^[#ℹ]\\s*${label}\\s+(\\d+)$`, "m"));
      return m ? Number(m[1]) : null;
    };

    const tests = read("tests");
    const pass = read("pass");
    const fail = read("fail");

    // A missing summary is itself a failure: it means the output shape changed
    // and every number below would silently read as null. Never treat that as a
    // pass.
    // A missing summary has two causes and both need their evidence kept: the
    // reporter's shape changed (so the regexes above read null), or the runner
    // died before it could write a summary at all. Print whatever failures the
    // partial stream does contain, then the tail of it, BEFORE returning —
    // `finally` deletes the file and CI deletes the machine.
    if (tests === null || pass === null || fail === null) {
      reportFailures(parseFailures(tap));
      reportTapTail(tap, "could not read the run summary from `node --test`.");
      console.error(
        "\nassert-unit-suite-ran: could not read the run summary from `node --test`.\n" +
          "Either the reporter's output shape changed, so this gate can no longer see the\n" +
          "counts, or the runner exited before writing a summary — the tail above says\n" +
          "which. Fix the parse rather than removing the check.",
      );
      return 1;
    }

    if (child.status !== 0 || fail > 0) {
      const failures = parseFailures(tap);

      // The runner can exit non-zero while reporting `fail 0` — an uncaught
      // exception after the last test, a worker that died. That combination
      // used to print `0 failing test(s).` and nothing else, which is exactly
      // the unattributable red #433 was about.
      if (failures.length === 0) {
        reportTapTail(
          tap,
          `the runner exited ${child.status} but named no failing test (summary says fail ${fail}).`,
        );
      } else {
        reportFailures(failures);
      }

      console.error(`\nassert-unit-suite-ran: ${fail} failing test(s).`);
      return child.status === 0 ? 1 : child.status;
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
      return 1;
    }

    console.log(`assert-unit-suite-ran: ${pass}/${tests} passed, floor ${MIN_TESTS}. OK`);
    return 0;
  } finally {
    rmSync(tapDir, { recursive: true, force: true });
  }
};

// Exported so the failure-report parser can be tested by the very suite this
// script guards — see tests/unit/assert-unit-suite-gate.test.mjs. A gate whose
// reporting has never been exercised is the shape #433 was made of, and the
// only way to know this one still names a failing test is to assert it.
export { parseFailures };

// Run only when invoked as a script, so importing it for those tests does not
// launch the whole suite recursively. `import.meta.main` would say this in one
// word but landed after Node 22, which is the version CI pins.
const invokedDirectly =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  // Deliberately NOT process.exit(): see the #433 note above. Setting the code
  // and falling off the end lets Node flush stdout and stderr first, which is
  // the difference between a reported failure and an unattributable one.
  process.exitCode = main();
}
