/**
 * Unit tests for `readFiledMailPage` in `lib/mail/filed.ts` — the Inbox's ONE
 * reading of `GET /applications/mail`.
 *
 * This parser had no test at all. It is the defensive boundary between the
 * wire and every claim the Inbox makes about a message, and one of those
 * claims — "on your board" — was wrong in production for every message whose
 * application had been dismissed (#489).
 *
 * The `on_board` cases below matter more than they look. The field is new, so
 * a deployed frontend can meet a response that predates it, and the default
 * decides what the user is told when the backend says nothing. `false` is the
 * safe direction: it renders "on a removed row", which understates a presence
 * rather than asserting one nobody confirmed.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import { FILED_PAGE_SIZE, readFiledMailPage } from "../../lib/mail/filed.ts";

/** A minimal wire message. Only `message_id` is load-bearing for the parser. */
function wire(overrides = {}) {
  return { message_id: "m-1", subject: "Thank you for your application!", ...overrides };
}

test("on_board is honoured only when literally true", () => {
  const page = readFiledMailPage({
    messages: [
      wire({ message_id: "live", on_board: true }),
      wire({ message_id: "removed", on_board: false }),
    ],
  });
  const byId = Object.fromEntries(page.messages.map((m) => [m.message_id, m]));
  assert.equal(byId.live.on_board, true);
  assert.equal(byId.removed.on_board, false);
});

test("a missing on_board defaults to false, not true", () => {
  // An older backend, or a field dropped by a proxy. The Inbox must not claim
  // a board presence the response never stated.
  const [message] = readFiledMailPage({ messages: [wire()] }).messages;
  assert.equal(message.on_board, false);
});

test("a truthy-but-not-true on_board is still false", () => {
  // `=== true`, not a truthiness check: "false" and 1 are both wire noise.
  for (const value of ["true", "false", 1, 0, {}, [], null, undefined]) {
    const [message] = readFiledMailPage({ messages: [wire({ on_board: value })] }).messages;
    assert.equal(message.on_board, false, `on_board should be false for ${JSON.stringify(value)}`);
  }
});

test("on_board is independent of application_id", () => {
  // The whole point of the field: a linked row that is NOT on the board.
  const [message] = readFiledMailPage({
    messages: [wire({ application_id: 115, on_board: false })],
  }).messages;
  assert.equal(message.application_id, 115);
  assert.equal(message.on_board, false);
});

test("a message with no id is dropped rather than rendered unkeyed", () => {
  const page = readFiledMailPage({
    messages: [wire({ message_id: null }), wire({ message_id: "keeps-it" })],
  });
  assert.deepEqual(
    page.messages.map((m) => m.message_id),
    ["keeps-it"],
  );
});

test("the other booleans are equally strict", () => {
  const [message] = readFiledMailPage({
    messages: [wire({ user_corrected: "yes", is_reviewed: 1 })],
  }).messages;
  assert.equal(message.user_corrected, false);
  assert.equal(message.is_reviewed, false);
});

test("paging falls back to the page size the Inbox actually requests", () => {
  const page = readFiledMailPage({ messages: [wire()] });
  assert.equal(page.page, 1);
  assert.equal(page.pageSize, FILED_PAGE_SIZE);
  // `total` falls back to what arrived, so the pager never claims fewer rows
  // than are on screen.
  assert.equal(page.total, 1);
});

test("a malformed body is null, NOT an empty page", () => {
  // Deliberate, and the distinction is the whole point: an empty page renders
  // "you have no mail", which is a false statement about the user's mailbox
  // when the truth is that the response was unreadable. `null` routes the view
  // to its failure state instead. Asserted here so a future "defensive"
  // refactor to `{messages: []}` has to argue with a test.
  for (const body of [null, undefined, {}, { messages: null }, { messages: "nope" }, 42]) {
    assert.equal(readFiledMailPage(body), null, `expected null for ${JSON.stringify(body)}`);
  }
});

test("an empty messages array IS a page — no mail is not the same as no answer", () => {
  const page = readFiledMailPage({ messages: [], total: 0 });
  assert.notEqual(page, null);
  assert.deepEqual(page.messages, []);
  assert.equal(page.total, 0);
});

test("category counts keep only numeric values", () => {
  const page = readFiledMailPage({
    messages: [],
    category_counts: { applied: 48, needs_review: "1", other: null },
  });
  assert.equal(page.categoryCounts.applied, 48);
  assert.ok(!("needs_review" in page.categoryCounts));
  assert.ok(!("other" in page.categoryCounts));
});
