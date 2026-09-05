/**
 * AN UNESCAPED MBOX IS DECLARED, NOT INVENTED (#426).
 *
 * mboxrd writes a body line beginning `From ` as `>From `, and Google Takeout
 * escapes correctly — so this is a malformed file rather than a mishandled
 * valid one. It is fixed anyway because of what the page did with the
 * ambiguity. Five real messages whose bodies quote a forwarded header, before:
 *
 *     totalFound=10  rendered=10  unreadable=0
 *     m1/m3/m5/m7/m9 are phantoms: subject "INVENTED - this line was never a
 *     header", sender "(unknown sender)", drawn beside the real rows with the
 *     same confidence chrome.
 *
 * `ImportMail` states "{totalFound} messages found" as fact, so the count was
 * false as well — but the count is only how you notice. The defect is the
 * row-level claim: a verdict, a sender and a confidence asserted about text
 * that was never a message.
 *
 * THREE SHAPES, AND NO ONE RULE CATCHES MORE THAN TWO. That is the whole
 * reason all three are here; each was measured against both mutants.
 *
 *   prose     the quoted `From ` line is followed by ordinary prose, and the
 *             block that would follow it carries no `From:`/`Date:`. EITHER
 *             rule catches it — so this shape alone proves neither.
 *   header    the quoted `From ` line is followed by `Subject: …`, which IS
 *             header-shaped, so rule 1 accepts the split. Caught only by rule
 *             2: a block carrying neither `From:` nor `Date:` is body text and
 *             is re-joined to the message above it. With rule 2 deleted this
 *             shape goes back to ten rows.
 *   envelope  a whole quoted message — prose, then real `From:` and `Date:`
 *             headers — under an unescaped envelope line. Rule 2 cannot touch
 *             it, because the block does carry an envelope. Caught only by
 *             rule 1, whose next-line test sees prose. With rule 1 deleted
 *             this shape goes back to ten rows.
 *
 * WHAT IS STILL AMBIGUOUS, SAID PLAINLY. A quoted message whose unescaped
 * envelope line is followed IMMEDIATELY by its `From:` header is byte for byte
 * what a real message boundary looks like, and neither rule can tell them
 * apart — nothing can, which is why mboxrd defines the `>From ` escape in the
 * first place. That file still splits, and `malformed` is null, because there
 * was nothing to notice. The fix narrows the ambiguity and declares it where
 * it is detectable; it does not abolish it.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parseMailFile } from "../../lib/import/parseMail.ts";

const PHANTOM = "INVENTED - this line was never a header";

const quotedBlock = (shape) => {
  const envelope =
    shape === "escaped"
      ? ">From talent@nimbus.test Thu Sep  3 08:00:00 2026"
      : "From talent@nimbus.test Thu Sep  3 08:00:00 2026";
  const quoted = "here is the note they sent, quoted verbatim";
  const middle = {
    header: [`Subject: ${PHANTOM}`],
    envelope: [
      quoted,
      "From: Nimbus Talent <talent@nimbus.test>",
      "Date: Thu, 03 Sep 2026 08:00:00 +0000",
      `Subject: ${PHANTOM}`,
    ],
  }[shape] ?? [quoted, `Subject: ${PHANTOM}`];

  return [envelope, ...middle, "", "The quoted note runs on for another line."].join("\n");
};

/** Five real messages, each forwarding a quoted header block. */
const fiveForwards = (shape) =>
  Array.from(
    { length: 5 },
    (_, i) =>
      `From ${i + 1}@import.test Thu Sep  3 09:00:00 2026\n` +
      `From: Nimbus Talent <talent@nimbus.test>\n` +
      `Subject: Fwd: your application ${i + 1}\n` +
      `Date: Thu, 03 Sep 2026 09:0${i}:00 +0000\n` +
      `\n` +
      `Passing this along, see the quoted note below.\n` +
      `\n` +
      `${quotedBlock(shape)}\n`,
  ).join("\n");

for (const shape of ["prose", "header", "envelope"]) {
  test(`five messages quoting a header (${shape}) stay five messages`, () => {
    const out = parseMailFile("forwarded.mbox", fiveForwards(shape));

    assert.equal(
      out.totalFound,
      5,
      `the file holds five messages; the split found ${out.totalFound}. The page prints this ` +
        "number as a fact about somebody's mail.",
    );
    assert.equal(out.messages.length, 5);
    assert.deepEqual(
      out.messages.map((m) => m.subject),
      [1, 2, 3, 4, 5].map((n) => `Fwd: your application ${n}`),
      "a quoted line was drawn as a message of its own",
    );
    assert.deepEqual(
      out.messages.filter((m) => m.senderEmail === "(unknown sender)"),
      [],
      "a phantom row carries no sender, because there was never a sender to read",
    );
  });

  test(`the quoted text is kept, not dropped (${shape})`, () => {
    // The remedy is not "discard the ambiguous block". Refusing to draw a row
    // for body text and deleting that text are different things, and only the
    // first is honest: the words belong to the message they were quoted in.
    const out = parseMailFile("forwarded.mbox", fiveForwards(shape));
    for (const [i, msg] of out.messages.entries()) {
      assert.ok(
        msg.body.includes(PHANTOM),
        `message ${i + 1} lost the quoted block that was re-joined to it: ${JSON.stringify(msg.body.slice(0, 120))}`,
      );
    }
  });

  test(`the file says it was ambiguous (${shape})`, () => {
    const out = parseMailFile("forwarded.mbox", fiveForwards(shape));
    assert.notEqual(
      out.malformed,
      null,
      "the boundary between messages was decided rather than read, and the page has to say so " +
        "rather than presenting the result as a clean parse",
    );
    assert.match(out.malformed, /mbox/);
  });
}

/**
 * THE CONTROL THAT FAILS A BAD GUARD. mboxrd's `>From ` escape makes this the
 * SAME five messages in a WELL-FORMED file. It must produce five rows and no
 * warning at all: a guard that fires on both files measures nothing, and one
 * that calls every export malformed teaches people to ignore the sentence.
 */
test("the correctly escaped file is five messages and raises no warning", () => {
  const out = parseMailFile("forwarded.mbox", fiveForwards("escaped"));

  assert.equal(out.totalFound, 5);
  assert.equal(out.messages.length, 5);
  assert.equal(
    out.malformed,
    null,
    `a correctly escaped export was called malformed: ${JSON.stringify(out.malformed)}`,
  );
  // And the escape is undone, so the quoted line reads as it was written.
  assert.ok(out.messages[0].body.includes("From talent@nimbus.test"));
});

/**
 * THE OTHER DIRECTION. Everything above is satisfied by a `splitMbox` that
 * stopped splitting — one row for the whole file passes "no phantom subject"
 * and "nothing dropped" perfectly. This is an ordinary export, and it has to
 * come apart into its messages.
 */
test("an ordinary mbox is still split into its messages", () => {
  const ordinary = [1, 2, 3]
    .map(
      (n) =>
        `From ${n}@import.test Thu Sep  3 09:00:00 2026\n` +
        `X-GM-THRID: 17${n}4820398412\n` +
        `From: Nimbus Talent <talent@nimbus.test>\n` +
        `Subject: Message ${n}\n` +
        `Date: Thu, 03 Sep 2026 09:0${n}:00 +0000\n` +
        `\n` +
        `Body of message ${n}.\n`,
    )
    .join("\n");

  const out = parseMailFile("ordinary.mbox", ordinary);
  assert.equal(out.totalFound, 3);
  assert.deepEqual(
    out.messages.map((m) => m.subject),
    ["Message 1", "Message 2", "Message 3"],
  );
  assert.equal(out.malformed, null);
});

/**
 * A message with a `Date:` and no `From:` is a message. The re-join rule needs
 * BOTH headers absent, and this is the case that says so: with `||` for `&&`,
 * every mail whose `From:` this parser could not read would be swallowed into
 * the one above it.
 */
test("a message carrying only one of From: and Date: is left alone", () => {
  const half = [
    "From 1@import Thu Sep  3 09:00:00 2026\n" +
      "From: Nimbus Talent <talent@nimbus.test>\n" +
      "Subject: Has a From but no Date\n" +
      "\n" +
      "First body.\n",
    "From 2@import Thu Sep  3 10:00:00 2026\n" +
      "Date: Thu, 03 Sep 2026 10:00:00 +0000\n" +
      "Subject: Has a Date but no From\n" +
      "\n" +
      "Second body.\n",
  ].join("\n");

  const out = parseMailFile("half.mbox", half);
  assert.equal(out.totalFound, 2);
  assert.deepEqual(
    out.messages.map((m) => m.subject),
    ["Has a From but no Date", "Has a Date but no From"],
  );
  assert.equal(out.malformed, null);
});

/** The accounting invariant #421 shipped still holds on an ambiguous file. */
test("found still equals classified plus unreadable when the file is malformed", () => {
  for (const shape of ["prose", "header", "envelope", "escaped"]) {
    const out = parseMailFile("forwarded.mbox", fiveForwards(shape));
    assert.equal(
      out.totalFound,
      out.messages.length + out.unreadable,
      `${shape}: found ${out.totalFound}, classified ${out.messages.length}, skipped ${out.unreadable}`,
    );
  }
});
