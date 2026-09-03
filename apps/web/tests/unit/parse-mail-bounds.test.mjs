/**
 * THE `From:` HEADER IS UNBOUNDED INPUT FROM AN ANONYMOUS STRANGER, and until
 * 2026-08-21 nothing limited its length.
 *
 * `/import` needs no account. It parses on the main thread, shows no progress
 * past "reading", and offers no cancel. `parseFrom`'s address pattern is
 * `/^(.*?)<([^>]+)>\s*$/`: a lazy `.*?` in front of a literal that never
 * satisfies the anchor, which makes the engine restart at every position. So
 * a header of N unmatched `<` characters costs O(N²), and a 128 KB file
 * froze the tab for 23.8 seconds. Measured, before the fix, at four sizes:
 * 373 ms / 1,498 ms / 5,935 ms / 23,842 ms, four times per doubling.
 *
 * The body already had a cap (MAX_BODY_CHARS). The header did not, which made
 * the header the CHEAPER attack: no MIME, no encoding, no large body, just a
 * short file with one long line in it. A hang is worse than a crash here,
 * because it presents as the product being slow rather than as a defect.
 *
 * ---------------------------------------------------------------------------
 * WHY THERE IS A CLOCK IN THIS FILE, and why it is not the flaky kind.
 *
 * A performance fix that no test measures is a fix that comes back. The house
 * rule against timing assertions is about tests that sample a distribution
 * whose two outcomes are close together; this one is not that. The defect
 * costs 23,842 ms and the fix costs 1.6 ms, so the bound below sits four
 * hundred times above the fixed cost and fifteen times below the broken one.
 * A runner would have to be an order of magnitude slower than this machine
 * before the margin mattered, and if it ever is, the assertion is still
 * telling the truth: the parse took two seconds.
 *
 * The correctness test beside it is the positive control. A `parseFrom` that
 * returned a constant would satisfy every clock in the world.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parseFrom, parseMailFile } from "../../lib/import/parseMail.ts";

/**
 * The shape that made it quadratic: `<` that never closes, then filler.
 *
 * THE 1,024 LEADING `a`s ARE THE MEASUREMENT, AND THEY ARE NEW (#721).
 *
 * Everything here is capped at MAX_FROM_CHARS before it reaches a matcher, so
 * both sizes below do the same 1,024 characters of work and the ratio is meant
 * to be ~1. The question is whether those 1,024 characters cost anything worth
 * timing. With a leading run of `<`, they do not: `<` is excluded from the
 * fallback's character class, so all 1,024 start positions fail on their first
 * character and the whole call costs 0.005 ms. That is noise, not a
 * measurement, and `Math.max(..., 0.05)` then clamped it to the floor on 199
 * of 200 rounds — which is what turned this assertion into an absolute 0.2 ms
 * deadline rather than a ratio.
 *
 * Address-legal characters inside the cap make the capped work real: the
 * fallback starts a match at every one of the 1,024 positions and backtracks
 * looking for an `@` that is not there. Measured, min of nine:
 *
 *     leading `<`   0.0041 ms      leading `a`   1.6478 ms
 *
 * A 400x larger numerator, which is what puts the measurement above the floor
 * and keeps this a ratio.
 */
const hostileFrom = (n) => "a".repeat(1024) + "<".repeat(n) + "a".repeat(n);

/**
 * Timing noise is additive and one-signed — a scheduler slice or a GC pause can
 * only make a measurement bigger — so the minimum across trials is the
 * estimator it cannot inflate.
 *
 * NINE IS NOT DECORATION, IT IS THE FIX (#721). A bigger numerator alone is not
 * enough. Measured on this machine under ten competing CPU-bound processes,
 * 150 rounds each, which is closer to a shared CI runner than an idle laptop:
 *
 *     fixture       estimator     ratio p99   max     red at 4
 *     leading `<`   single shot   2.92        5.33    1 / 150
 *     leading `a`   single shot   7.24        11.17   2 / 150
 *     leading `a`   min of nine   1.02        1.73    0 / 150
 *
 * The middle row is the one to keep in mind: on a contended machine the better
 * fixture ALONE is worse than what it replaced, because a single large sample
 * can still catch a stall and there is nothing to discard it against.
 *
 * ABSURD_MS IS WHAT KEEPS A RED FAST. A capped call costs about 1.7 ms, so
 * anything past 100 ms is not a slow machine, it is the cap gone. Without the
 * early return, raising MAX_FROM_CHARS runs the restored quadratic nine times
 * per size: measured, 61.7 s and 61.2 s for the two assertions below, about two
 * minutes to reach a verdict available on the first trial.
 */
const ABSURD_MS = 100;

function bestOf(input, trials) {
  let min = Infinity;
  for (let i = 0; i < trials; i++) {
    const started = performance.now();
    parseFrom(input);
    const elapsed = performance.now() - started;
    // A quadratic is slow every time. Stop rather than measure it nine times.
    if (elapsed > ABSURD_MS) return elapsed;
    if (elapsed < min) min = elapsed;
  }
  return min;
}

/**
 * The shape that reaches the OTHER quadratic — `parseFrom`'s bare-address
 * fallback, `/[^\s<>@]+@[^\s<>@]+/`. No `<`, no `>`, and crucially no `@`, so
 * `parseAngleAddress` returns null immediately and every microsecond measured
 * below is spent in the fallback.
 */
const bareFrom = (n) => "a".repeat(n);

test("a hostile From header cannot freeze the tab", () => {
  // 64000 is the size measured at 23.8 seconds before the cap.
  const started = performance.now();
  parseFrom(hostileFrom(64000));
  const elapsed = performance.now() - started;
  assert.ok(
    elapsed < 1500,
    `parseFrom took ${elapsed.toFixed(0)}ms on a 128KB From header. It is quadratic in the header's length, and /import runs it on the main thread of an unauthenticated page, so this is a frozen tab rather than a slow one. The cap is MAX_FROM_CHARS in lib/import/parseMail.ts.`,
  );
});

test("the cost does not grow with the header, so the bound is the cap and not the clock", () => {
  // Quadratic would make this sixteen times the cost of the smaller one.
  // Capped, the two are the same 1,024 characters of work and the ratio is ~1.
  // No floor: the fixture now measures enough that one is not needed, and a
  // floor is what hid this test's real behaviour before (#721).
  const small = bestOf(hostileFrom(16000), 9);
  const large = bestOf(hostileFrom(64000), 9);
  assert.ok(
    large / small < 4,
    `a 4x longer header cost ${(large / small).toFixed(1)}x more to parse (${small.toFixed(4)}ms then ${large.toFixed(4)}ms). Quadratic growth is back: the header is reaching the matcher unbounded.`,
  );
});

test("a hostile header does not stop the message being parsed", () => {
  const raw = `From: ${hostileFrom(64000)}\r\nSubject: Interview scheduling\r\n\r\nAre you free Thursday?\r\n`;
  const started = performance.now();
  const { messages } = parseMailFile("hostile.eml", raw);
  const elapsed = performance.now() - started;

  assert.equal(messages.length, 1, "the hostile header made the whole file unparseable");
  assert.equal(messages[0].subject, "Interview scheduling");
  assert.ok(
    messages[0].senderEmail.length <= 1024,
    `the sender address is ${messages[0].senderEmail.length} chars, so the cap is not being applied on the path /import actually uses`,
  );
  assert.ok(elapsed < 1500, `parseMailFile took ${elapsed.toFixed(0)}ms on a 128KB header`);
});

/**
 * The control. Capping a header is only correct if ordinary mail is nowhere
 * near the cap, so these are the three shapes `/import` meets constantly:
 * a display name with an address, a bare address, and an RFC 2047 encoded
 * word, which is the one a naive `slice` could cut in half.
 */
test("ordinary From headers are untouched by the cap", () => {
  assert.deepEqual(parseFrom("Nadia Okafor <Nadia.Okafor@Cedar.example>"), {
    name: "Nadia Okafor",
    email: "nadia.okafor@cedar.example",
  });
  assert.deepEqual(parseFrom("careers@acme.test"), { name: null, email: "careers@acme.test" });
  assert.deepEqual(parseFrom("=?utf-8?B?SsO2cmc=?= <jorg@acme.test>"), {
    name: "Jörg",
    email: "jorg@acme.test",
  });
});


// ---------------------------------------------------------------------------
// The quadratic that is still there
// ---------------------------------------------------------------------------

/**
 * WHAT THESE TWO ARE FOR, AND WHY THEY ARE NOT THE THREE ABOVE.
 *
 * `parseAngleAddress` is a linear scan since #406, and its own timing test
 * proves that uncapped. It is easy to read that as "the quadratic is gone". It
 * is not: `parseFrom` has a second branch, and when a value holds no angle
 * address it falls through to `/[^\s<>@]+@[^\s<>@]+/`. A long run of
 * address-legal characters with no `@` in it makes that pattern start at every
 * position and backtrack over the remainder of the run — O(N²), measured here
 * at 25 / 100 / 400 / 1,600 ms for N = 4,000 / 8,000 / 16,000 / 32,000, four
 * times per doubling.
 *
 * AND IT IS WHAT #406'S OWN INPUT REACHES. `"<"×N + "a"×N` contains no `@`, so
 * after `parseAngleAddress` declines it the fallback is what runs. The `<` run
 * costs nothing (`<` is excluded from the character class, so those positions
 * fail on the first character); the cost is entirely in the `a` run, which is
 * why the fixture below drops the angle brackets. Same numbers, one less thing
 * for the measurement to be about.
 *
 * SO MAX_FROM_CHARS IS STILL THE ONLY THING BETWEEN A VISITOR AND A FROZEN
 * TAB, and these tests are what makes that a measurement rather than a
 * sentence in a comment. Both red when the cap is raised: at 64,000 the second
 * one grows sixteenfold and the first one takes about 1.6 seconds.
 *
 * The tests above use `hostileFrom`, which reaches this same branch and so
 * covers it incidentally. That is exactly why these exist separately — an
 * incidental cover is one refactor away from being no cover, and the comment
 * on `MAX_FROM_CHARS` now makes a specific claim about a specific branch. This
 * is the branch, named.
 */
test("the bare-address fallback is bounded by the cap, not by the clock", () => {
  // Uncapped this ratio is ~16 (four times per doubling, twice over). Capped,
  // both calls do the same 1,024 characters of work and the ratio is ~1.
  //
  // THIS FIXTURE WAS ALWAYS FINE; THE ESTIMATOR WAS NOT. `bareFrom` is all
  // address-legal characters, so its capped 1,024 already cost 1.7 ms and the
  // 0.05 floor never engaged — which is why #721 first graded this site
  // healthy and left it alone. That grade came from an idle machine. Under ten
  // competing CPU-bound processes, 150 rounds, it reds 1 in 150 with a worst
  // ratio of 6.77; min-of-nine takes that to 0 in 150 with a worst of 1.75.
  const small = bestOf(bareFrom(16000), 9);
  const large = bestOf(bareFrom(64000), 9);
  assert.ok(
    large / small < 4,
    `a 4x longer bare From header cost ${(large / small).toFixed(1)}x more to parse ` +
      `(${small.toFixed(4)}ms then ${large.toFixed(4)}ms). parseFrom's bare-address ` +
      "fallback is quadratic and is reaching it unbounded: MAX_FROM_CHARS in " +
      "lib/import/parseMail.ts is what holds it.",
  );
});

test("a bare From header of the size that costs 1.6 seconds uncapped does not", () => {
  const started = performance.now();
  parseFrom(bareFrom(32000));
  const elapsed = performance.now() - started;
  assert.ok(
    elapsed < 100,
    `parseFrom took ${elapsed.toFixed(0)}ms on a 32,000-character bare From header. ` +
      "Uncapped that shape costs about 1,600ms in the bare-address fallback, on the " +
      "main thread of an unauthenticated page. The cap is MAX_FROM_CHARS.",
  );
});

test("a bare address is still found, so the two tests above are not timing a no-op", () => {
  // The positive control the clock needs: a `parseFrom` that returned a
  // constant would satisfy every timing assertion in this file.
  assert.deepEqual(parseFrom("Talent Team careers@cedar.example"), {
    name: null,
    email: "careers@cedar.example",
  });
  // And the fallback is genuinely what answers here — there is no angle
  // address in it to take precedence.
  assert.deepEqual(parseFrom(`${bareFrom(20)} careers@cedar.example`), {
    name: null,
    email: "careers@cedar.example",
  });
});
