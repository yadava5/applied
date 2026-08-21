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

/** The shape that made it quadratic: `<` that never closes, then filler. */
const hostileFrom = (n) => "<".repeat(n) + "a".repeat(n);

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
  const time = (n) => {
    const input = hostileFrom(n);
    const started = performance.now();
    parseFrom(input);
    return performance.now() - started;
  };
  // Quadratic would make this sixteen times the cost of the smaller one.
  // Capped, the two are the same work and the ratio is noise.
  const small = Math.max(time(16000), 0.05);
  const large = time(64000);
  assert.ok(
    large / small < 4,
    `a 4x longer header cost ${(large / small).toFixed(1)}x more to parse (${small.toFixed(2)}ms then ${large.toFixed(2)}ms). Quadratic growth is back: the header is reaching the matcher unbounded.`,
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
