/**
 * Unit tests for the toast system's pure policy (`lib/feedback/coalesce.ts`,
 * #511). These pin the decisions, not "a toast appeared":
 *
 *  1. Two rapid identical actions are ONE toast — same id, and the RENDERED
 *     text carries the count ("2 applications updated" / a "×2" badge). This
 *     is the acceptance test the issue predicted would be skipped.
 *  2. Errors never get a dismissal timer, on any path.
 *  3. Nothing emits for sync — pinned with a passing control alongside, so
 *     the assertion cannot rot into one that suppresses everything.
 *  4. A failure never merges into an open success toast's count.
 *  5. A resolved toast does not leak its count into the next occurrence.
 *  6. The pause arithmetic the hover/focus hold relies on.
 *
 * Run:  node --test --experimental-strip-types tests/unit/feedback-coalesce.test.mjs
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  Countdown,
  DURATIONS,
  FeedbackChannel,
  MAX_VISIBLE,
  isSilentAction,
  renderToast,
} from "../../lib/feedback/coalesce.ts";

const statusEvent = {
  key: "application.status",
  kind: "success",
  message: "Stripe updated",
  countMessage: (n) => `${n} applications updated`,
};

test("two rapid identical actions are ONE toast whose rendered text counts 2", () => {
  const channel = new FeedbackChannel();
  const first = channel.decide(statusEvent);
  const second = channel.decide({ ...statusEvent, message: "Anthropic updated" });

  assert.equal(first.action, "show");
  assert.equal(second.action, "update");
  // Same toast, updated in place — not a sibling.
  assert.equal(second.toast.id, first.toast.id);
  assert.equal(second.toast.count, 2);
  // The count the user actually reads, not the internal tally.
  assert.deepEqual(renderToast(second.toast), {
    text: "2 applications updated",
    countBadge: null,
  });
});

test("without a countMessage the count renders as a ×N badge", () => {
  const channel = new FeedbackChannel();
  const event = { key: "data.export", kind: "success", message: "Export ready" };
  channel.decide(event);
  channel.decide(event);
  const third = channel.decide(event);
  assert.equal(third.action, "update");
  assert.deepEqual(renderToast(third.toast), { text: "Export ready", countBadge: "×3" });
});

test("a single occurrence renders its own message with no badge", () => {
  const channel = new FeedbackChannel();
  const only = channel.decide(statusEvent);
  assert.equal(only.action, "show");
  assert.deepEqual(renderToast(only.toast), { text: "Stripe updated", countBadge: null });
});

test("errors never get a dismissal timer; success and undo do", () => {
  assert.equal(DURATIONS.error, null);
  const channel = new FeedbackChannel();
  const shown = channel.decide({ key: "gmail.disconnect", kind: "error", message: "Failed" });
  assert.equal(shown.action, "show");
  assert.equal(shown.toast.duration, null);
  // Merging more failures must not conjure a timer either.
  const merged = channel.decide({ key: "gmail.disconnect", kind: "error", message: "Failed" });
  assert.equal(merged.action, "update");
  assert.equal(merged.toast.duration, null);

  // The kinds that DO time out — the control for the null above, and the
  // undo window a keyboard user is promised.
  assert.equal(DURATIONS.success, 4_000);
  assert.equal(DURATIONS.undo, 8_000);
});

test("nothing emits for sync — and the guard is a prefix, not a substring", () => {
  const channel = new FeedbackChannel();
  assert.deepEqual(channel.decide({ key: "sync", kind: "success", message: "Synced" }), {
    action: "suppress",
  });
  assert.deepEqual(channel.decide({ key: "sync.auto", kind: "success", message: "Synced" }), {
    action: "suppress",
  });
  // Controls: the suppression must not swallow everything (the inverted-gate
  // trap), and "synchron…" is not "sync.".
  assert.equal(channel.decide(statusEvent).action, "show");
  assert.equal(isSilentAction("synchronize"), false);
});

test("kinds do not share a bucket: a failure never inflates a success count", () => {
  const channel = new FeedbackChannel();
  const ok = channel.decide(statusEvent);
  const bad = channel.decide({ key: "application.status", kind: "error", message: "Failed" });
  assert.equal(bad.action, "show");
  assert.notEqual(bad.toast.id, ok.toast.id);
  assert.equal(bad.toast.count, 1);
});

test("distinct keys do not coalesce", () => {
  const channel = new FeedbackChannel();
  channel.decide(statusEvent);
  const other = channel.decide({ key: "data.export", kind: "success", message: "Export ready" });
  assert.equal(other.action, "show");
  assert.equal(other.toast.count, 1);
});

test("a resolved toast releases its bucket: the next occurrence restarts at 1", () => {
  const channel = new FeedbackChannel();
  const first = channel.decide(statusEvent);
  channel.resolve(first.toast.id);
  channel.resolve(first.toast.id); // idempotent
  const fresh = channel.decide(statusEvent);
  assert.equal(fresh.action, "show");
  assert.notEqual(fresh.toast.id, first.toast.id);
  assert.equal(fresh.toast.count, 1);
});

test("the visible stack cap is three", () => {
  assert.equal(MAX_VISIBLE, 3);
});

test("Countdown pauses, resumes where it stopped, and resets to a full window", () => {
  const c = new Countdown(4_000, 1_000);
  assert.equal(c.remainingAt(2_500), 2_500);

  c.pause(2_500); // hover/focus lands with 2.5s left
  assert.equal(c.isPaused, true);
  assert.equal(c.remainingAt(60_000), 2_500); // held time does not burn down

  c.resume(60_000);
  assert.equal(c.remainingAt(61_000), 1_500);

  c.reset(61_000); // a merged occurrence refills the window
  assert.equal(c.remainingAt(61_000), 4_000);

  // Created while the stack is already held: does not run until resumed.
  const held = new Countdown(4_000, 0, true);
  assert.equal(held.isPaused, true);
  assert.equal(held.remainingAt(10_000), 4_000);
  // Reset while held must STAY held — a toast updated under the pointer
  // must not start its own clock.
  held.reset(10_000);
  assert.equal(held.isPaused, true);

  // Never negative, even read after expiry.
  const spent = new Countdown(100, 0);
  assert.equal(spent.remainingAt(500), 0);
});
