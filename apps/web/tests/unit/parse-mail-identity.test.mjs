/**
 * A MESSAGE'S ID IS ITS CONTENT, NOT ITS POSITION (#426).
 *
 * `/import` keeps each row's expanded/collapsed state in the row component
 * (`ImportRow`, local `useState`), and React decides which component instance
 * a row keeps by the LIST KEY. The list was already keyed by `item.id` — the
 * remedy the issue asked for was in the tree — and it did nothing, because
 * `parseMailFile` minted `const id = `m${i}``. The id WAS the ordinal, so a
 * second file handed React the same four keys for four different messages,
 * the same instances stayed mounted, and rows 1 and 3 remained expanded over
 * somebody else's mail. Measured on the page before the fix, with no click
 * between the two imports:
 *
 *     file A (Alpha message 1..4)   expanded: row1=true, row3=true
 *     file B (Beta  message 1..4)   expanded: row1=true, row3=true
 *     CONTROL, "Clear results" in between: all false
 *
 * WHAT THESE ASSERT, AND WHY IT IS NOT THE ID'S FORMAT. A rename — `msg-0`,
 * `row_0`, a hash OF the index — satisfies any assertion about how an id
 * looks while leaving the defect exactly where it was. The property that
 * matters is that two different messages never collide, so every test here is
 * a collision test, and the cross-file one is the one the issue is about.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parseMailFile } from "../../lib/import/parseMail.ts";

/** Four ordinary messages. Only the employer and the bodies differ per file. */
const four = (who, host) =>
  Array.from(
    { length: 4 },
    (_, i) =>
      `From ${i + 1}@import.test Thu Sep  3 0${9 + i}:00:00 2026\n` +
      `From: ${who} Recruiting <talent@${host}.test>\n` +
      `Subject: ${who} message ${i + 1}\n` +
      `Date: Thu, 03 Sep 2026 0${9 + i}:00:00 +0000\n` +
      `\n` +
      `Thank you for applying to ${who}. Your application has been received.\n`,
  ).join("\n");

const idsOf = (result) => result.messages.map((m) => m.id);

test("two files whose messages differ share no ids", () => {
  const a = parseMailFile("alpha.mbox", four("Alpha", "alpha"));
  const b = parseMailFile("beta.mbox", four("Beta", "beta"));

  assert.equal(a.messages.length, 4);
  assert.equal(b.messages.length, 4);

  const shared = idsOf(a).filter((id) => idsOf(b).includes(id));
  assert.deepEqual(
    shared,
    [],
    `both files minted ${JSON.stringify(shared)}. Row N of the second file is the same React ` +
      "key as row N of the first, so the first file's expanded rows are inherited by different mail.",
  );
});

test("the ids inside one file are distinct, including for byte-identical messages", () => {
  // A Takeout export really does repeat a message: once per label it carries.
  const one =
    "From 1@import Thu Sep  3 09:00:00 2026\n" +
    "From: Nimbus Talent <talent@nimbus.test>\n" +
    "Subject: Thanks for applying\n" +
    "Date: Thu, 03 Sep 2026 09:00:00 +0000\n" +
    "\n" +
    "We have received your application.\n";
  const out = parseMailFile("dupes.mbox", [one, one, one].join("\n"));

  assert.equal(out.messages.length, 3, "three rows, because the file holds three copies");
  assert.equal(
    new Set(idsOf(out)).size,
    3,
    `duplicate React keys (${JSON.stringify(idsOf(out))}). React matches the first of them, ` +
      "which is the same reuse-the-wrong-instance defect this issue is about.",
  );
});

/**
 * THE CONTROL ON THE COLLISION TESTS ABOVE. Every one of them is satisfied by
 * an id that is simply random, and a random id would break the feature in the
 * other direction: React would remount every row on each re-render and no row
 * could stay open at all. The id has to be a function of the message.
 */
test("the same bytes parse to the same ids every time", () => {
  const text = four("Alpha", "alpha");
  assert.deepEqual(idsOf(parseMailFile("a.mbox", text)), idsOf(parseMailFile("a.mbox", text)));
});

test("a Message-ID is what the id follows, wherever the message sits", () => {
  const withId = (n, position) =>
    `From ${position}@import.test Thu Sep  3 09:00:00 2026\n` +
    `From: Nimbus Talent <talent@nimbus.test>\n` +
    `Subject: Message ${n}\n` +
    `Message-ID: <${n}.9f2c@nimbus.test>\n` +
    `Date: Thu, 03 Sep 2026 09:00:00 +0000\n` +
    `\n` +
    `Body of message ${n}.\n`;

  // The same message, in first position in one file and third in the other.
  const first = parseMailFile("one.mbox", [withId("a", 1), withId("b", 2)].join("\n"));
  const later = parseMailFile(
    "two.mbox",
    [withId("c", 1), withId("d", 2), withId("a", 3)].join("\n"),
  );

  assert.equal(
    later.messages[2].id,
    first.messages[0].id,
    "mail carries a globally unique identifier of its own (RFC 5322 §3.6.4); moving the same " +
      "message down a file must not change what the page thinks it is",
  );
  assert.equal(new Set(idsOf(later)).size, 3);
});

/**
 * Gmail exports the same message once per label, `Message-ID:` and all, so
 * this is a shape a real Takeout file has — and adopting that header verbatim
 * without checking would hand React two identical keys.
 */
test("the same Message-ID twice in one file still yields two distinct ids", () => {
  const labelled =
    "From 1@import Thu Sep  3 09:00:00 2026\n" +
    "From: Nimbus Talent <talent@nimbus.test>\n" +
    "Subject: Thanks for applying\n" +
    "Message-ID: <dup.1f4b@nimbus.test>\n" +
    "Date: Thu, 03 Sep 2026 09:00:00 +0000\n" +
    "\n" +
    "We have received your application.\n";

  const out = parseMailFile("labels.mbox", [labelled, labelled].join("\n"));
  assert.equal(out.messages.length, 2);
  assert.notEqual(out.messages[0].id, out.messages[1].id, JSON.stringify(idsOf(out)));
});

test("a JSON batch follows the same rule", () => {
  const batch = (who) =>
    JSON.stringify(
      Array.from({ length: 4 }, (_, i) => ({
        subject: `${who} message ${i + 1}`,
        from: `talent@${who.toLowerCase()}.test`,
        body: `Thank you for applying to ${who}.`,
      })),
    );

  const a = parseMailFile("alpha.json", batch("Alpha"));
  const b = parseMailFile("beta.json", batch("Beta"));

  assert.equal(new Set(idsOf(a)).size, 4, "distinct within the batch");
  assert.deepEqual(
    idsOf(a).filter((id) => idsOf(b).includes(id)),
    [],
    "the JSON path minted the ordinal too, and it is the path the sample batches use",
  );
});

/**
 * The `.eml` path has exactly one message, so it cannot collide with itself —
 * but it can collide with the OTHER file the visitor drops next, which is the
 * whole defect. Two different single messages, two different ids.
 */
test("two single .eml messages do not share an id", () => {
  const eml = (subject, sender) =>
    `From: ${sender}\nSubject: ${subject}\n\nBody for ${subject}.\n`;

  const one = parseMailFile("one.eml", eml("Interview scheduling", "talent@alpha.test"));
  const two = parseMailFile("two.eml", eml("Update on your application", "talent@beta.test"));

  assert.equal(one.messages.length, 1);
  assert.equal(two.messages.length, 1);
  assert.notEqual(one.messages[0].id, two.messages[0].id);
});
