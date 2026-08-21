/**
 * `/import` ACCOUNTS FOR EVERY MESSAGE IT SAYS IT FOUND.
 *
 * Found by driving the page with a 10,000-mail adversarial corpus. Three
 * defects, all of which made the page state something untrue about a person's
 * own mail:
 *
 *   1. MESSAGES VANISHED. `parseRfc822` and `parseJsonMessage` return null for
 *      an entry with no subject, no sender and no body, and the caller only
 *      ever saw `messages.length`. A 50-record file with 20 blank entries
 *      reported "50 messages found", listed 30 rows, and said nothing. It
 *      fired on real corpus data too: a 400-message batch quietly became 393,
 *      and on the mbox path a Gmail label-only stub took 8 down to 5.
 *
 *   2. THE TRUNCATION SENTENCE WAS FALSE. It read "classified the first
 *      ${items.length}", but that count is how many SURVIVED, not how many
 *      were read. A 1,000-record file with 300 blanks said "classified the
 *      first 280" having read the first 400 and classified 280 of them.
 *      Records 281 to 400 were read; a reader concludes they were skipped.
 *      "The first N" names a prefix and this was never a prefix.
 *
 *   3. A TAKEOUT MBOX NAMED `.eml` COLLAPSED TO ONE ROW. `detectFormat`
 *      believed the extension, and `eml` means "one message", so 400 mails
 *      became a single row: the first mail's headers and a body of raw
 *      undecoded base64 followed by the entire MIME source of the other 399.
 *      The same bytes named `.mbox` produced 400 correct rows.
 *
 * The through-line is that each one is a case where the parser had the
 * information and the interface did not carry it. `unreadable` exists so the
 * count cannot be dropped on the floor again.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_MESSAGE_CAP, detectFormat, parseMailFile } from "../../lib/import/parseMail.ts";

const mail = (i) =>
  `From ${i}@import Thu Jul 16 09:00:00 2026\r\n` +
  `From: Recruiter ${i} <hire${i}@acme.test>\r\n` +
  `Subject: Your application ${i}\r\n` +
  `\r\n` +
  `Thank you for applying. We have received application ${i}.\r\n`;

const mbox = (n) => Array.from({ length: n }, (_, i) => mail(i + 1)).join("\n");

test("entries that parse to nothing are counted, not dropped in silence", () => {
  const records = [];
  for (let i = 0; i < 30; i += 1) {
    records.push({ subject: `Interview ${i}`, from: `a${i}@acme.test`, body: "Let us schedule." });
  }
  for (let i = 0; i < 20; i += 1) records.push({ subject: "", from: "", body: "" });

  const out = parseMailFile("silent_drop_50.json", JSON.stringify(records));

  assert.equal(out.totalFound, 50, "every record in the file is found");
  assert.equal(out.messages.length, 30, "only the 30 real ones survive parsing");
  assert.equal(
    out.unreadable,
    20,
    "the 20 that produced nothing must be counted. Without this the page says '50 found', shows 30 rows, and accounts for the other 20 nowhere.",
  );
  assert.equal(out.truncated, false, "nothing was trimmed: 50 is under the cap");
});

test("found equals classified plus unreadable, on every path", () => {
  // The invariant, stated once. If this holds, no message can go missing
  // without a number moving.
  const cases = [
    ["clean.json", JSON.stringify([{ subject: "Offer", from: "a@b.test", body: "We are pleased" }])],
    ["blanks.json", JSON.stringify([{ subject: "", from: "", body: "" }])],
    ["small.mbox", mbox(5)],
    ["one.eml", mail(1)],
  ];
  for (const [name, text] of cases) {
    const out = parseMailFile(name, text);
    const read = Math.min(out.totalFound, DEFAULT_MESSAGE_CAP);
    assert.equal(
      read,
      out.messages.length + out.unreadable,
      `${name}: read ${read} but classified ${out.messages.length} and skipped ${out.unreadable}. Those must add up or the summary line is lying.`,
    );
  }
});

test("over the cap, the count read is the cap and the rest is not called skipped", () => {
  const n = DEFAULT_MESSAGE_CAP + 120;
  const out = parseMailFile("over_cap.mbox", mbox(n));

  assert.equal(out.totalFound, n);
  assert.equal(out.truncated, true);
  assert.equal(out.messages.length, DEFAULT_MESSAGE_CAP, "the cap is what was read");
  assert.equal(
    out.unreadable,
    0,
    "the 120 past the cap were never read, so they are NOT unreadable. Conflating the two is what made the old sentence describe a prefix it had not read.",
  );
});

test("a Takeout mbox named .eml is read as an mbox, not as one message", () => {
  const bytes = mbox(400);

  assert.equal(detectFormat("Takeout.eml", bytes), "mbox");
  const asEml = parseMailFile("Takeout.eml", bytes);
  const asMbox = parseMailFile("Takeout.mbox", bytes);

  assert.equal(
    asEml.messages.length,
    400,
    "renaming a Takeout export to .eml used to collapse 400 mails into one row whose body was the raw MIME of the other 399",
  );
  assert.equal(
    asEml.messages.length,
    asMbox.messages.length,
    "the same bytes must parse the same way under either name",
  );
  assert.deepEqual(
    asEml.messages.map((m) => m.subject),
    asMbox.messages.map((m) => m.subject),
  );
});

/**
 * The control on the sniff above. It must not reclassify a genuine single
 * message, or every `.eml` in the world starts being read as an mbox.
 */
test("a real .eml is still a single message", () => {
  const single =
    "From: Nadia Okafor <nadia@cedar.example>\r\n" +
    "Subject: Interview scheduling\r\n" +
    "\r\n" +
    "Are you free Thursday? Also: the line below is body text, not a separator.\r\n" +
    "From here on it is prose.\r\n";

  assert.equal(detectFormat("message.eml", single), "eml");
  const out = parseMailFile("message.eml", single);
  assert.equal(out.messages.length, 1);
  assert.equal(out.messages[0].subject, "Interview scheduling");
});
