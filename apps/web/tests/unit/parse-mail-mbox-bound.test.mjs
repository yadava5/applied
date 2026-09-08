/**
 * THE CAP BOUNDS WHAT THE SPLIT BUILDS, NOT ONLY WHAT IT RETURNS (#810).
 *
 * `splitMbox` opened on `text.split(/\r?\n/)` and then built a `lines: string[]`
 * and a joined, un-escaped, trimmed `raw` for every segment in the file —
 * before a cap that only ever keeps 400. On a 520 MB export at a real Takeout's
 * density that was **1,532 ms of frozen main thread and 4.3 GB of peak RSS**,
 * with "Reading your file…" on screen for all of it; bounded, the same file is
 * **291 ms**. The cap worked perfectly on the 400 messages it reached, and on
 * nothing before them. The whole table is in `splitMbox`'s own comment.
 *
 * WHAT THESE TESTS CAN AND CANNOT CARRY. A duration is a flake generator and a
 * peak-RSS reading is not deterministic, so neither is asserted here; the
 * before/after table lives in `splitMbox`'s own comment, which is where every
 * other measured number in that file lives. What IS deterministic is the
 * CONTRACT the speed comes from, and that is what is graded:
 *
 *   - the file past the cap moves `total` and moves nothing else — not the
 *     number of chunks built, and not one byte of any of them;
 *   - `total`, `malformed` and the retained chunks are IDENTICAL to what an
 *     unbounded split returns, on files where the two could differ.
 *
 * The count in each case comes from the fixture builder and the bound comes
 * from the argument, so no assertion here reads its expectation out of
 * `DEFAULT_MESSAGE_CAP` — a bound checked against the constant that sets it
 * passes for every value of the constant.
 *
 * THE FIXTURES ARE INVENTED. This repo is public; every employer, address and
 * body below is made up, and `.invalid` is reserved by RFC 2606 precisely so
 * it can never be anyone's real domain.
 *
 * Run:  pnpm test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_MESSAGE_CAP, parseMailFile, splitMbox } from "../../lib/import/parseMail.ts";

const EMPLOYERS = ["nimbus", "cobalt", "harrow", "verdant"];

const separator = (id) => `From feed-${id}@mx.invalid Thu Sep  3 08:00:00 2026`;

/** One ordinary, well-formed message: a separator and a real envelope. */
const message = (n) =>
  [
    separator(n),
    `From: talent@${EMPLOYERS[n % EMPLOYERS.length]}.invalid`,
    "Date: Thu, 03 Sep 2026 08:00:00 +0000",
    `Subject: your application, note ${n}`,
    "",
    `We reviewed application ${n} and will be in touch.`,
    "",
  ].join("\n");

/**
 * A block that SPLITS but is not a message: its separator is followed by a
 * header-shaped line, so rule 1 accepts it, and it carries neither `From:` nor
 * `Date:`, so rule 2 re-joins it upward (#426). This is what makes
 * `chunks.length !== separators` — a fixture where they agree grades nothing.
 */
const bodyBlock = (n) =>
  [
    separator(`q${n}`),
    `Subject: quoted line ${n}`,
    "",
    `text that was never a message (${n})`,
    "",
  ].join("\n");

test("past the cap the file is counted and not built", () => {
  // Both numbers come from the builders below, and the bound comes from the
  // argument. Neither is read out of DEFAULT_MESSAGE_CAP.
  const cap = 12;
  const kept = cap + 3;
  const tailLength = 4000;

  const head = Array.from({ length: kept }, (_, i) => message(i)).join("\n");
  const tail = Array.from({ length: tailLength }, (_, i) => message(1000 + i)).join("\n");

  const short = splitMbox(head, cap);
  const long = splitMbox(`${head}\n${tail}`, cap);

  assert.equal(short.total, kept, "the short file holds exactly what the builder wrote");
  assert.equal(long.total, kept + tailLength, "the long file's tail is counted to EOF");

  assert.equal(short.chunks.length, cap, "the split stops building at the cap");
  assert.equal(
    long.chunks.length,
    cap,
    `${tailLength} more messages in the file built ${long.chunks.length - cap} more chunks. ` +
      "The whole of #810 is that this number does not move with the file.",
  );
  assert.deepEqual(
    long.chunks,
    short.chunks,
    "the tail must not change one byte of what was kept, only the count",
  );
});

test("a bounded split returns exactly the prefix an unbounded one does", () => {
  // msg -> block -> msg -> block. At cap 1 the SECOND block re-joins onto the
  // first chunk, which is retained and must still be extended; the fourth
  // re-joins onto a chunk that was never built and must only be counted. That
  // sequence is where the `total <= cap` off-by-one lives.
  const text = [message(1), bodyBlock(1), message(2), bodyBlock(2)].join("\n");

  const all = splitMbox(text, Infinity);
  assert.equal(all.chunks.length, 2, "four separators, two messages: the re-join rule fired twice");
  assert.ok(
    all.chunks[0].raw.includes("text that was never a message (1)"),
    "the re-joined block is inside the message above it, which is what makes cap 1 discriminating",
  );

  for (const cap of [0, 1, 2, 3]) {
    const bounded = splitMbox(text, cap);
    assert.equal(bounded.total, all.chunks.length, `cap ${cap}: the count is the whole file's`);
    assert.equal(bounded.malformed, all.malformed, `cap ${cap}: the sentence is the whole file's`);
    assert.deepEqual(
      bounded.chunks,
      all.chunks.slice(0, cap),
      `cap ${cap}: a bounded split must return the unbounded split's prefix, byte for byte`,
    );
  }
});

test("both malformed counters keep counting past the cap", () => {
  const cap = 2;
  // Three clean messages, then — past the cap — one whose body quotes a
  // `From ` line without the `>From ` escape, and one block with no envelope.
  const quoting = [
    separator("late"),
    "From: talent@pelham.invalid",
    "",
    "they wrote:",
    "",
    "From quoted@pelham.invalid Wed Sep  2 09:00:00 2026",
    "and then the quote continued",
    "",
  ].join("\n");
  const text = [message(1), message(2), message(3), quoting, bodyBlock(9)].join("\n");

  const all = splitMbox(text, Infinity);
  const bounded = splitMbox(text, cap);

  assert.equal(all.total, 4, "four messages: the fifth block was re-joined");
  assert.equal(bounded.total, all.total);
  assert.equal(bounded.chunks.length, cap);
  assert.match(
    bounded.malformed,
    /1 line beginning “From ” sits inside a message body/,
    "the un-escaped line is in the FOURTH message, past a cap of two",
  );
  assert.match(
    bounded.malformed,
    /1 block carried no From: or Date: header/,
    "the re-joined block is the FIFTH, past a cap of two",
  );
  assert.equal(bounded.malformed, all.malformed, "and the sentence is the unbounded one's, exactly");
});

test("a line of spaces separates messages, the same as an empty one", () => {
  // `prevBlank` is `line.trim() === ""` and not `line === ""`: mbox's separator
  // rule reads a whitespace-only line as a blank one, and a file re-saved by an
  // editor that pads its blank lines is where that matters. The scan tests
  // characters in place instead of trimming a line it cut out of the file, so
  // this pins the two to the same answer — including on the non-ASCII half of
  // the set, which is the only thing an ASCII-only fixture cannot grade.
  const twoMessages = (gap) =>
    [
      separator(1),
      "From: talent@harrow.invalid",
      "",
      "the first message",
      gap,
      separator(2),
      "From: talent@verdant.invalid",
      "",
      "the second message",
      "",
    ].join("\n");

  assert.equal(splitMbox(twoMessages(""), 400).total, 2, "an empty line: the ordinary case");
  for (const [what, gap] of [
    ["three spaces", "   "],
    ["a tab", "\t"],
    ["a non-breaking space", "\u00a0"],
  ]) {
    const padded = splitMbox(twoMessages(gap), 400);
    assert.equal(padded.total, 2, `${what} is still a blank line, so the separator holds`);
    assert.equal(padded.malformed, null, `${what}: nothing had to be decided, so no sentence`);
  }
});

test("a CRLF export splits to the same messages as an LF one", () => {
  // Every real Takeout export is CRLF, and the scan strips the `\r` from a
  // line's end itself now instead of letting `split(/\r?\n/)` do it. Both
  // `raw` and `offset` are defined to be free of that difference.
  const text = [message(1), bodyBlock(1), message(2)].join("\n");
  const crlf = text.replace(/\n/g, "\r\n");

  assert.notEqual(crlf, text, "the CRLF twin has to actually differ from the LF one");
  assert.deepEqual(splitMbox(crlf, 400), splitMbox(text, 400));
});

test("an envelope only a multiline ^ can see is still found", () => {
  // `carriesAnEnvelope` runs `/^(from|date):/im`, and under `m` a JavaScript
  // `^` sits after a bare `\r` too — which `split(/\r?\n/)` does NOT treat as a
  // line ending. The scan's per-line pre-filter cannot see that position, so
  // this pair is what proves the pre-filter falls back to the real predicate
  // instead of answering for it.
  const hidden = (tail) =>
    [
      message(1),
      [separator("x"), "Subject: nothing at a line start", `noise\r${tail}`, "", "body two", ""].join(
        "\n",
      ),
    ].join("\n");

  assert.equal(
    splitMbox(hidden("From: hidden@quillon.invalid"), 400).total,
    2,
    "the block's only envelope sits after a bare CR, and it is still a message",
  );
  assert.equal(
    splitMbox(hidden("Subject: hidden"), 400).total,
    1,
    "the control: the same block with no envelope anywhere is re-joined",
  );
});

test("the envelope scan stops at MAX_ENVELOPE_SCAN_CHARS, bounded or not", () => {
  // The bound is 8,000 characters into the rendered block and both alternatives
  // are five characters, so an envelope line starting at 7,995 is the last one
  // that fits. One character further and the block is body text. The pair is
  // the point: a single arm proves nothing about where the bound is.
  const withEnvelopeAt = (at) =>
    [
      message(1),
      [
        separator("pad"),
        `X-Pad: ${"b".repeat(at - 1 - "X-Pad: ".length)}`,
        "From: late@cobalt.invalid",
        "",
        "body two",
        "",
      ].join("\n"),
    ].join("\n");

  assert.equal(splitMbox(withEnvelopeAt(7995), 400).total, 2, "7,995 + 5 = 8,000, which fits");
  assert.equal(splitMbox(withEnvelopeAt(7996), 400).total, 1, "one character further does not");
});

test("the page's message count is exact on a file well over the cap", () => {
  // End to end, through the number ImportMail prints as fact. The file holds
  // more messages than the cap AND re-joins on both sides of it, so `totalFound`
  // is neither the separator count nor the chunk count.
  const clean = DEFAULT_MESSAGE_CAP + 50;
  const blocks = [];
  for (let i = 0; i < clean; i++) {
    blocks.push(message(i));
    // A re-joined block early (inside the cap) and late (well past it).
    if (i === 3 || i === DEFAULT_MESSAGE_CAP + 20) blocks.push(bodyBlock(i));
  }
  const out = parseMailFile("export.mbox", blocks.join("\n"));

  assert.equal(out.totalFound, clean, "the two re-joined blocks are not messages and are not counted");
  assert.equal(out.truncated, true);
  assert.equal(out.messages.length, DEFAULT_MESSAGE_CAP);
  assert.equal(out.unreadable, 0);
  assert.match(out.malformed, /2 blocks carried no From: or Date: header/);
});
