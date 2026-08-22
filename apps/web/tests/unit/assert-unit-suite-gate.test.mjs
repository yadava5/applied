/**
 * The unit gate's own failure reporting.
 *
 * WHY THIS FILE EXISTS. #433 is a CI run where the unit gate correctly reported
 * `1 failing test(s).` and the failing test's name was nowhere in the log — the
 * gate replayed 116 KB of captured output in one `process.stdout.write` and
 * then called `process.exit()`, so everything past the 64 KiB pipe buffer was
 * discarded. The verdict survived; the evidence did not. The failure was
 * unattributable, a re-run went green, and the flaky test is still unnamed.
 *
 * The fix in `scripts/assert-unit-suite-ran.mjs` is to parse the run's TAP out
 * of a temp file and re-print each failing test's name and payload as a short
 * block on stderr. That parser is now the single thing standing between a red
 * build and another unattributable one, so it gets asserted rather than
 * assumed — a gate whose reporting has never been exercised is exactly the
 * shape #433 was made of.
 *
 * The fixtures below are real `node --test --test-reporter=tap` output on Node
 * 22, copied verbatim rather than hand-written, because the whole risk here is
 * that the parser is written against a shape the runner does not actually emit.
 *
 * Run:  pnpm test:unit
 */
import test from "node:test";
import assert from "node:assert/strict";

import { parseFailures } from "../../scripts/assert-unit-suite-ran.mjs";

/** Verbatim from `node --test --test-reporter=tap` on Node 22, one failure. */
const LEAF_FAILURE = `TAP version 13
# Subtest: the canary that must be named in the output
not ok 1 - the canary that must be named in the output
  ---
  duration_ms: 1.036291
  type: 'test'
  location: '/w/tests/unit/zz-canary.test.mjs:7:1'
  failureType: 'testCodeFailure'
  error: |-
    Expected values to be strictly equal:
    + actual - expected

    + 'canary-actual'
    - 'canary-expected'
              ^

  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  expected: 'canary-expected'
  actual: 'canary-actual'
  operator: 'strictEqual'
  ...
1..1
# tests 1
# pass 0
# fail 1
`;

test("a failing test is reported by name — the thing #433 lost", () => {
  const failures = parseFailures(LEAF_FAILURE);

  assert.equal(failures.length, 1);
  assert.equal(failures[0].name, "the canary that must be named in the output");
  assert.equal(failures[0].number, "1");
});

test("the assertion diff travels with the name, not just the name", () => {
  const [failure] = parseFailures(LEAF_FAILURE);
  const payload = failure.payload.join("\n");

  // A name alone still leaves you running the test locally to see why. The
  // expected/actual pair is what makes a CI log actionable on its own.
  assert.match(payload, /Expected values to be strictly equal/);
  assert.match(payload, /\+ 'canary-actual'/);
  assert.match(payload, /- 'canary-expected'/);
  assert.match(payload, /location: '\/w\/tests\/unit\/zz-canary\.test\.mjs:7:1'/);
});

test("a green run reports nothing, so the block never fires on a pass", () => {
  const passing = "TAP version 13\nok 1 - fine\n  ---\n  duration_ms: 0.1\n  ...\n1..1\n# fail 0\n";
  assert.deepEqual(parseFailures(passing), []);
});

test("a parent that only failed because a child did is not reported as a failure", () => {
  // `node --test` marks the enclosing test `not ok` too, with
  // failureType: 'subtestsFailed'. Reporting those repeats a file or
  // describe-block name and pushes the real leaf failures out of the cap.
  const nested = `TAP version 13
    not ok 1 - the leaf that actually broke
      ---
      failureType: 'testCodeFailure'
      error: 'boom'
      ...
not ok 1 - tests/unit/some-file.test.mjs
  ---
  failureType: 'subtestsFailed'
  error: '1 subtest failed'
  ...
1..1
# fail 1
`;
  const failures = parseFailures(nested);

  assert.equal(failures.length, 1);
  assert.equal(failures[0].name, "the leaf that actually broke");
});

test("a TAP stream cut off mid-run still yields the failures it did contain", () => {
  // The defence-in-depth case: if anything ever truncates the stream again,
  // the parser must degrade to "fewer failures" and never to a throw, because
  // throwing here would once more turn a red build into an unattributable one.
  const truncated = LEAF_FAILURE.slice(0, LEAF_FAILURE.indexOf("code: 'ERR_ASSERTION'"));
  const failures = parseFailures(truncated);

  assert.equal(failures.length, 1);
  assert.equal(failures[0].name, "the canary that must be named in the output");
  assert.match(failures[0].payload.join("\n"), /Expected values to be strictly equal/);
});

test("importing the gate does not run the suite — otherwise this file recurses", () => {
  // `scripts/assert-unit-suite-ran.mjs` guards its main() on being invoked
  // directly. If that guard regresses, importing it here spawns the whole unit
  // suite from inside the unit suite; this asserts the guard by the fact that
  // the import above returned at all, and pins the export it depends on.
  assert.equal(typeof parseFailures, "function");
});
