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

const hostile = (n) => "<".repeat(n) + "a".repeat(n);

test("the scan is not quadratic in the length of the header", () => {
  // 64000 is the size at which the regex takes 18 seconds.
  const input = hostile(64000);
  const started = performance.now();
  parseAngleAddress(input);
  const elapsed = performance.now() - started;

  assert.ok(
    elapsed < 500,
    `parseAngleAddress took ${elapsed.toFixed(0)}ms on a 128KB value. The backtracking matcher is back: MAX_FROM_CHARS hides it from parseFrom, but every other caller pays O(n²) again.`,
  );
});

test("the cost does not grow with the input, so it is the algorithm and not the machine", () => {
  const time = (n) => {
    const input = hostile(n);
    const started = performance.now();
    parseAngleAddress(input);
    return performance.now() - started;
  };
  // Quadratic makes this sixteen times the smaller measurement. Linear makes
  // the two indistinguishable, so the floor is what keeps the ratio finite.
  const small = Math.max(time(16000), 0.05);
  const large = time(64000);

  assert.ok(
    large / small < 4,
    `a 4x longer value cost ${(large / small).toFixed(1)}x more (${small.toFixed(2)}ms then ${large.toFixed(2)}ms), which is the quadratic's growth rate rather than a scan's.`,
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
