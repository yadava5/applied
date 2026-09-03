/**
 * THE ANGLE-ADDRESS MATCHER IS A SCAN NOW, NOT A BACKTRACKING REGEX.
 *
 * `/^(.*?)<([^>]+)>\s*$/` is quadratic in the length of its input: a lazy `.*?`
 * in front of a literal that never satisfies the anchor makes the engine
 * restart at every position. Measured on this machine, the regex alone, on
 * `"<"×N + "a"×N`:
 *
 *     N =  2000     18 ms        N = 16000   1,144 ms
 *     N =  4000     71 ms        N = 32000   4,569 ms
 *     N =  8000    285 ms        N = 64000  18,176 ms
 *
 * WHY THIS FILE EXISTS BESIDE `parse-mail-bounds.test.mjs`, which already times
 * `parseFrom` on the same input. That file measures the 1024-character
 * MAX_FROM_CHARS cap, and the cap alone holds `parseFrom` to about 2 ms — so
 * every assertion in it passes identically with the quadratic regex put back.
 * It is a true test of the cap and it cannot see this fix at all.
 *
 * So the timing here goes through `parseAngleAddress`, which is the scan
 * WITHOUT the cap in front of it. Reverting `parseFrom` to the regex reds
 * nothing; reverting `parseAngleAddress` to it reds this file at 18 seconds
 * against a 500 ms bound.
 *
 * AND THE SPEED IS WORTH NOTHING IF THE ANSWER CHANGED. `/import` is a public
 * page and the display name it draws on every row comes out of this function,
 * so the equivalence half below is the more important half: a table taken from
 * the old regex, plus a fuzz that runs both implementations over 20,000 random
 * strings built from the characters that decide the parse.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parseAngleAddress, parseFrom } from "../../lib/import/parseMail.ts";

/** The implementation being replaced. The reference, not the shipped path. */
const OLD = /^(.*?)<([^>]+)>\s*$/;

/** What `parseAngleAddress` returns, expressed through the old regex. */
function oldAngleAddress(value) {
  const m = value.match(OLD);
  return m ? { name: m[1], email: m[2] } : null;
}

/**
 * THE INPUT #406 FILED COSTS ALMOST NOTHING, AND THE FLOOR THEN DID THE WORK.
 *
 * `"<"×N + "a"×N` does not end in `>`, so `parseAngleAddress` fails the anchor
 * test and returns without running either interior walk. What is left is the
 * one indexed read of the last character, which forces V8 to flatten the rope
 * that `repeat` and `+` built — genuinely O(n), and genuinely tiny. A fresh
 * string per call, min of nine, idle M-series laptop:
 *
 *     N =    16,000   0.0049 ms
 *     N =   250,000   0.0855 ms
 *     N = 1,000,000   0.2308 ms
 *
 * CORRECTED. An earlier version of this comment said the cost was "flat across
 * a 64x range, there is no growth in it to find", and printed 0.0002 ms at
 * every size. That was an artefact of the measurement, not a property of the
 * input: those numbers came from timing ONE string repeatedly, and after the
 * first read it is already flat, so every later trial measured a walk that had
 * nothing left to do. It also called 16,000 -> 1,000,000 a 64x range; it is
 * 62.5x. The growth is real. It is simply far below the 0.05 ms floor the old
 * assertion clamped to, which is the actual reason that assertion stopped being
 * a ratio. Reported by a blind cross-check of the commit that wrote it.
 *
 * The input stays, because it is the shape the issue was filed about and it
 * still reds a reverted `parseAngleAddress` — the REGEX is quadratic on it,
 * which is the entire reason #406 exists. What it is not is a measurement of
 * the scan's own walks, and the growth test below used to treat it as one.
 *
 * `hostileDeep` is the shape that makes the scan work for its answer. It ends
 * in `>`, so the anchor passes and both interior walks run: `lastIndexOf(">",
 * gt - 1)` back across the middle run, then `indexOf("<", prevGt + 1)` forward
 * across the tail, finding nothing and returning null. Both implementations
 * answer null on it, so the equivalence half of this file is untouched.
 *
 *     scan   N =    62,500   0.0404 ms      regex   N = 1,000     4.4 ms
 *            N =   250,000   0.1608 ms              N = 2,000    17.2 ms
 *            N = 1,000,000   0.6423 ms              N = 4,000    68.1 ms
 *                                                   N = 8,000   272.7 ms
 *
 * 4x per 4x of input on the left, 4x per 2x on the right. Linear against
 * quadratic, on an input that reaches the code being defended.
 */
const hostile = (n) => "<".repeat(n) + "a".repeat(n);
const hostileDeep = (n) => "<".repeat(n) + "a".repeat(n) + ">" + "a".repeat(n) + ">";

test("the scan is not quadratic in the length of the header", () => {
  // 64000 is the size at which the regex takes 18 seconds on either shape.
  for (const [shape, input] of [
    ["the shape #406 filed", hostile(64000)],
    ["the shape that reaches the interior walks", hostileDeep(64000)],
  ]) {
    const started = performance.now();
    parseAngleAddress(input);
    const elapsed = performance.now() - started;

    assert.ok(
      elapsed < 500,
      `parseAngleAddress took ${elapsed.toFixed(0)}ms on ${shape} at ${input.length} characters. The backtracking matcher is back: MAX_FROM_CHARS hides it from parseFrom, but every other caller pays O(n²) again.`,
    );
  }
});

/**
 * A quadratic is slow on every trial, so there is nothing to learn from the
 * eight after the first. Without this, a restored regex costs nine trials at
 * 1.1 s plus nine at 17.4 s — three minutes of a runner to reach a verdict that
 * was available immediately. With it, measured: 18.5 s to red.
 */
const ABSURD_MS = 100;

/**
 * Timing noise is additive and one-signed — a scheduler slice or a GC pause can
 * only make a measurement larger — so the minimum of several trials is the
 * estimator it cannot inflate. The string is built outside the clock, and after
 * the first trial it is flat, so the later trials time the walk rather than
 * V8's rope.
 */
function bestOf(input, trials) {
  let min = Infinity;
  for (let i = 0; i < trials; i++) {
    const started = performance.now();
    parseAngleAddress(input);
    const elapsed = performance.now() - started;
    if (elapsed > ABSURD_MS) return elapsed;
    if (elapsed < min) min = elapsed;
  }
  return min;
}

/**
 * WHAT THIS REPLACES, AND WHY THE OLD FORM COULD NOT DO ITS JOB.
 *
 * It was `Math.max(time(16000), 0.05)` against a single `time(64000)`, bounded
 * at 4. On the flat input both sides measure 0.0002 ms, so 199 of 200 rounds
 * put the smaller measurement on the 0.05 floor: the assertion was never a
 * ratio, it was an absolute 0.2 ms deadline on a shared CI runner. Measured
 * noise on an idle laptop reached 0.524 ms — 2 of 200 rounds red — and it took
 * the #716 + #717 train red on a diff that does not touch this file. One of the
 * last forty Frontend CI runs died on it.
 *
 * The bound was the second half of the problem. 4x the input is 4x the walk, so
 * 4 sat exactly on the linear expectation with no room either side of it.
 * Quadratic is 16. 8 is the midpoint on the only scale that matters, a clear
 * factor of two from both.
 *
 * Min-of-nine over 100 rounds on the deep input: ratio p50 3.95, p99 3.98, max
 * 3.98, zero reds. Single-shot on the same input reaches 5.08.
 *
 * The flat input above is this test's control for the worry that an unused
 * return value gets optimised away: an eliminated call is what 0.0002 ms flat
 * across a 64x range looks like, and these measurements do not look like that.
 */
test("the cost does not grow with the input, so it is the algorithm and not the machine", () => {
  // THE CONTROL, AND IT HAS TO EXPECT A NON-NULL ANSWER.
  //
  // This was `assert.equal(parseAngleAddress(hostileDeep(64)), null)`, with a
  // comment claiming it caught an early exit. It cannot, and the reason is
  // structural: `null` is the correct answer on that input, so every early
  // return that ALSO answers `null` is indistinguishable from success. A blind
  // cross-check of the commit that wrote it put `if (value.length > 4096)
  // return null;` at the top of `parseAngleAddress` and all 789 unit tests
  // passed, this assertion included. The timings above it would then have been
  // measuring a length check.
  //
  // A long header with a REAL answer is what discriminates: under that cap
  // `a@b.test` becomes `null` and this line fails.
  const answered = parseAngleAddress("x".repeat(64000) + "<a@b.test>");
  assert.deepEqual(
    answered,
    { name: "x".repeat(64000), email: "a@b.test" },
    "parseAngleAddress stopped answering on a 64KB header. Something is refusing long input rather than scanning it, and every timing below is then measuring that refusal instead of the walk.",
  );

  const small = bestOf(hostileDeep(16000), 9);
  const large = bestOf(hostileDeep(64000), 9);

  assert.ok(
    large / small < 8,
    `a 4x longer value cost ${(large / small).toFixed(1)}x more (${small.toFixed(4)}ms then ${large.toFixed(4)}ms). A linear scan is 4x here and the backtracking regex is 16x; 8 is the line between them.`,
  );
});

/**
 * The four semantics of the old pattern that a naive `lastIndexOf("<")` gets
 * wrong, each with the value it produced BEFORE the change. These are not
 * hypotheticals: `Name <a@b.test> <c@d.test>` is a forwarded header and
 * `<a@b.test> trailing` is what a truncated header block looks like.
 */
const TABLE = [
  // `\s*$`: the `>` has to be last, or this is not an angle address at all.
  ["<a@b.test> trailing", null],
  // `[^>]+` cannot span a `>`, so the `<` must follow the last inner `>`.
  ["Name <a@b.test> <c@d.test>", { name: "Name <a@b.test> ", email: "c@d.test" }],
  ["<i@j.test>,<k@l.test>", { name: "<i@j.test>,", email: "k@l.test" }],
  // The lazy `.*?` takes the FIRST `<` after that point, not the last.
  ["a<b<c@d.test>", { name: "a", email: "b<c@d.test" }],
  // `[^>]+` is one-or-more: an empty address is not a match.
  ["Name <>", null],
  // The ordinary shapes.
  ["Nadia Okafor <Nadia.Okafor@Cedar.example>", { name: "Nadia Okafor ", email: "Nadia.Okafor@Cedar.example" }],
  ["Name<g@h.test>", { name: "Name", email: "g@h.test" }],
  ["<careers@acme.test>", { name: "", email: "careers@acme.test" }],
  ['"Okafor, Nadia" <nadia@cedar.example>', { name: '"Okafor, Nadia" ', email: "nadia@cedar.example" }],
  ["careers@acme.test", null],
  ["", null],
  [">", null],
  ["<>", null],
];

test("the scan reproduces the old pattern's answer on every shape it decided", () => {
  for (const [input, expected] of TABLE) {
    assert.deepEqual(
      parseAngleAddress(input),
      expected,
      `parseAngleAddress(${JSON.stringify(input)}) disagrees with the pattern it replaced`,
    );
    // The table is only trustworthy if it is what the old regex actually did.
    assert.deepEqual(
      oldAngleAddress(input),
      expected,
      `the EXPECTATION for ${JSON.stringify(input)} is not what /^(.*?)<([^>]+)>\\s*$/ produced — the table has drifted from the thing it records`,
    );
  }
});

test("the scan and the pattern agree on 20,000 random headers", () => {
  // Only the characters that can change the parse, so the fuzz spends its
  // budget on decisions rather than on filler.
  const ALPHABET = "<>@ab. \t\"";
  let seed = 0x406;
  const rand = (n) => {
    // xorshift: the corpus has to be the same on every machine and every run,
    // or a red here could not be reproduced from the failure message.
    seed ^= seed << 13;
    seed ^= seed >>> 17;
    seed ^= seed << 5;
    return (seed >>> 0) % n;
  };

  for (let i = 0; i < 20_000; i++) {
    const len = rand(24);
    let s = "";
    for (let j = 0; j < len; j++) s += ALPHABET[rand(ALPHABET.length)];

    assert.deepEqual(
      parseAngleAddress(s),
      oldAngleAddress(s),
      `the scan and the regex disagree on ${JSON.stringify(s)}`,
    );
  }
});

/**
 * The control for the whole file. `parseAngleAddress` could return null for
 * everything and satisfy both the clock and — with a reference implementation
 * that also returned null — nothing else here would notice. These assert the
 * shipped entry point on the shapes `/import` actually meets.
 */
test("parseFrom still reads ordinary mail", () => {
  assert.deepEqual(parseFrom("Nadia Okafor <Nadia.Okafor@Cedar.example>"), {
    name: "Nadia Okafor",
    email: "nadia.okafor@cedar.example",
  });
  assert.deepEqual(parseFrom("careers@acme.test"), { name: null, email: "careers@acme.test" });
  assert.deepEqual(parseFrom('"Okafor, Nadia" <nadia@cedar.example>'), {
    name: "Okafor, Nadia",
    email: "nadia@cedar.example",
  });
  assert.deepEqual(parseFrom("=?utf-8?B?SsO2cmc=?= <jorg@acme.test>"), {
    name: "Jörg",
    email: "jorg@acme.test",
  });
  assert.deepEqual(parseFrom("Name <a@b.test> <c@d.test>"), {
    name: "Name <a@b.test>",
    email: "c@d.test",
  });
});
