/**
 * Unit tests for the pure half of the sync surface (`lib/gmail/sync-plan.ts`):
 * what a rebuild request says, what the running line and receipt read, and
 * what the dialog remembers.
 *
 * Two honesty rules are load-bearing enough to assert directly:
 *
 *   1. A rebuild body NEVER carries `scope`. The backend forces
 *      `scope="anywhere"` on every rebuild (an inbox-scoped rebuild once
 *      deleted two real applications whose confirmations were archived);
 *      sending one would suggest the caller had a say it does not have.
 *   2. Nothing here produces a percentage. The server sync returns once, at
 *      the end — the elapsed clock and the stated scope are the only honest
 *      progress the UI can show, and the receipt renders only fields the
 *      response actually carried.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  REBUILD_DEFAULT_DEPTH,
  REBUILD_DEFAULT_RANGE,
  REBUILD_DEPTH_OPTIONS,
  formatCount,
  formatElapsed,
  parseRebuildMemory,
  readRebuildOutcome,
  readScanEnd,
  rebuildConfirmLabel,
  rebuildMemoryLine,
  rebuildRequestBody,
  rebuildScopeLine,
  receiptBodyLine,
  scanProgressLine,
  stopKind,
  stopReasonPhrase,
  SLOW_SYNC_AFTER_MS,
  SLOW_SYNC_GRACE_MS,
  SYNC_FALLBACK_RANGE_MONTHS,
  clampEstimate,
  durationLabel,
  syncMemoryLine,
  syncReceiptNote,
  syncRunningSentence,
  syncScopeLine,
} from "../../lib/gmail/sync-plan.ts";

test("the default rebuild reproduces the old hardwired button exactly", () => {
  // 12 months / 750 messages was the ReSyncButton's fixed behaviour; making
  // the rebuild configurable must not change what the default press does.
  assert.equal(REBUILD_DEFAULT_RANGE, "12");
  assert.equal(REBUILD_DEFAULT_DEPTH, 750);
  assert.ok(REBUILD_DEPTH_OPTIONS.includes(750));
  assert.deepEqual(rebuildRequestBody(REBUILD_DEFAULT_DEPTH, REBUILD_DEFAULT_RANGE), {
    mode: "rebuild",
    count: 750,
    range: "12",
  });
});

test("a rebuild body never carries scope, and all-time omits range", () => {
  for (const [depth, range] of [
    [100, "3"],
    [2000, "all"],
    [750, "12"],
  ]) {
    const body = rebuildRequestBody(depth, range);
    assert.equal("scope" in body, false, `scope must not be sent (${range})`);
    assert.equal(body.mode, "rebuild");
  }
  assert.deepEqual(rebuildRequestBody(2000, "all"), { mode: "rebuild", count: 2000 });
});

test("the elapsed clock formats m:ss and never shows a negative tick", () => {
  assert.equal(formatElapsed(0), "0:00");
  assert.equal(formatElapsed(999), "0:00");
  assert.equal(formatElapsed(42_000), "0:42");
  assert.equal(formatElapsed(83_000), "1:23");
  assert.equal(formatElapsed(725_000), "12:05");
  // A fresh run can compute elapsed from a stale tick — clamp, never "-0:01".
  assert.equal(formatElapsed(-1500), "0:00");
});

test("counts group deterministically without consulting a locale", () => {
  assert.equal(formatCount(0), "0");
  assert.equal(formatCount(750), "750");
  assert.equal(formatCount(2000), "2,000");
  assert.equal(formatCount(1234567), "1,234,567");
});

test("the running line states exactly what was chosen, plus the forced scope", () => {
  assert.equal(rebuildScopeLine(750, "12"), "up to 750 messages · last 12 months · all mail");
  assert.equal(rebuildScopeLine(2000, "all"), "up to 2,000 messages · all time · all mail");
});

test("the confirm button names the window it commits", () => {
  assert.equal(rebuildConfirmLabel("12"), "Rebuild from the last 12 months");
  assert.equal(rebuildConfirmLabel("all"), "Rebuild from all time");
});

test("the receipt reads only what the response said, and drops malformed rows", () => {
  const outcome = readRebuildOutcome({
    created: 41,
    updated: 2,
    scanned: 512,
    purged: 2,
    removed: [
      { id: 7, company: "MotherDuck" },
      { id: "bad", company: "Nope" },
      { company: "No id" },
      null,
      { id: 9, company: "Supabase" },
    ],
  });
  assert.deepEqual(outcome, {
    created: 41,
    updated: 2,
    scanned: 512,
    purged: 2,
    removed: [
      { id: 7, company: "MotherDuck" },
      { id: 9, company: "Supabase" },
    ],
    // No stopped_by in the body → an older backend → the behaviour that
    // response actually had (it always completed or threw).
    stoppedBy: "complete",
    estimate: null,
  });
  assert.equal(receiptBodyLine(outcome), "41 filed · 2 updated · 512 scanned");

  // A body that says nothing renders as nothing having happened — never NaN.
  const empty = readRebuildOutcome("<html>502</html>");
  assert.deepEqual(empty, {
    created: 0,
    updated: 0,
    scanned: 0,
    purged: 0,
    removed: [],
    stoppedBy: "complete",
    estimate: null,
  });
});

test("how the scan ended: partial and broken states never read as complete", () => {
  // The six-presses incident: a bounded scan stopped early on every press and
  // the UI reported completion each time, because nothing read `stopped_by`.
  assert.equal(stopKind("complete"), "complete");
  assert.equal(stopKind(undefined), "complete");
  assert.equal(stopKind(null), "complete");
  for (const partial of ["target", "deadline", "page_limit"]) {
    assert.equal(stopKind(partial), "partial", partial);
  }
  // An end state we cannot vouch for must not claim coverage either.
  assert.equal(stopKind("some_future_reason"), "partial");
  for (const broken of ["disconnected", "relay"]) {
    assert.equal(stopKind(broken), "broken", broken);
  }
});

test("the stop reason is the user's terms, never the enum, never a stale number", () => {
  assert.equal(stopReasonPhrase("target"), "hit its message limit");
  assert.equal(stopReasonPhrase("deadline"), "ran out of scan time");
  assert.equal(stopReasonPhrase("page_limit"), "hit Gmail's page limit");
  assert.equal(stopReasonPhrase("disconnected"), "lost its Gmail connection partway");
  assert.equal(stopReasonPhrase("some_future_reason"), "stopped before finishing");
  for (const raw of ["target", "deadline", "page_limit", "disconnected", "relay"]) {
    const phrase = stopReasonPhrase(raw);
    assert.doesNotMatch(phrase, /_/, "no enum leaks into copy");
    assert.doesNotMatch(phrase, /\d/, "no tunable number is hardcoded into copy");
  }
});

test("scan progress is worded as an estimate — never a percentage", () => {
  assert.equal(scanProgressLine(750, 2400), "scanned 750 of roughly 2,400");
  assert.equal(scanProgressLine(750, null), "scanned 750 so far");
  assert.doesNotMatch(scanProgressLine(750, 2400), /%/);
});

test("a running sync states the scope it can know, and only that", () => {
  // `hasCursor` is server truth and decides the backend's path, so it is the
  // one honest thing about the scan available before the response lands.
  assert.equal(syncScopeLine(true), "checking since last sync");
  assert.equal(syncScopeLine(false), `first scan · last ${SYNC_FALLBACK_RANGE_MONTHS} months`);
  // Mirrors the backend's `_SYNC_DEFAULT_RANGE_MONTHS`; a window is named or
  // nothing is.
  assert.equal(SYNC_FALLBACK_RANGE_MONTHS, 12);
  for (const line of [syncScopeLine(true), syncScopeLine(false)]) {
    assert.doesNotMatch(line, /%/, "no percentage on the running line");
  }
});

test("the running line answers 'how long' only when the question is live", () => {
  // No e2e fixture reaches the swap (the demo's simulated 1.2 s sync ends
  // before its own swap point), so this test IS the branch's coverage.
  const last = { ms: 3085, scanned: 0, at: 0 };
  // Until the run is slow, the sentence is the scope statement, unchanged.
  assert.equal(syncRunningSentence(true, 1000, last), syncScopeLine(true));
  assert.equal(syncRunningSentence(false, 1000, null), syncScopeLine(false));
  // With a measured memory, the swap fires once THIS run outlasts it (plus
  // grace — real runs drift a few hundred ms between presses)…
  assert.equal(
    syncRunningSentence(true, last.ms + SLOW_SYNC_GRACE_MS, last),
    "still checking · last run 3 s",
  );
  assert.equal(
    syncRunningSentence(true, last.ms + SLOW_SYNC_GRACE_MS - 1, last),
    syncScopeLine(true),
  );
  // …but never LATER than the fixed fallback: a 41 s full-scan memory must
  // not hold the bare scope line for 40 s.
  const slowMemory = { ms: 41000, scanned: 512, at: 0 };
  assert.equal(
    syncRunningSentence(true, SLOW_SYNC_AFTER_MS, slowMemory),
    "still checking · last run 41 s",
  );
  assert.equal(syncRunningSentence(true, SLOW_SYNC_AFTER_MS - 1, slowMemory), syncScopeLine(true));
  // No memory means no number, not an invented one.
  assert.equal(syncRunningSentence(true, SLOW_SYNC_AFTER_MS, null), "still checking");
  // Every state stays inside the module's honesty rules: past tense, no
  // percentage, no forecast vocabulary.
  for (const line of [
    syncRunningSentence(true, 0, last),
    syncRunningSentence(true, 60_000, last),
    syncRunningSentence(false, 60_000, null),
  ]) {
    assert.doesNotMatch(line, /%/, "no percentage on the running line");
    assert.doesNotMatch(line, /will|about|usually|~/, "no forecast on the running line");
  }
});

test("an estimate is never allowed below what was actually read", () => {
  // A denominator smaller than its own numerator is worse than none. The
  // backend clamps within one response; this clamps again at display, which
  // is where the two numbers finally sit side by side.
  assert.equal(clampEstimate(412, 1200), 1200);
  assert.equal(clampEstimate(900, 750), 900, "drifted estimate is floored at what was read");
  assert.equal(clampEstimate(412, null), null, "a floor is not an estimate");
  // And the clamped pair still reads as approximate, never as a fraction.
  const line = scanProgressLine(900, clampEstimate(900, 750));
  assert.equal(line, "scanned 900 of roughly 900");
  assert.doesNotMatch(line, /%/);
});

test("a duration is a measurement, stated in the past tense", () => {
  assert.equal(durationLabel(3085), "3 s");
  assert.equal(durationLabel(2716), "3 s");
  assert.equal(durationLabel(120), "1 s", "a sub-second run still reads as a duration");
  assert.equal(durationLabel(-5), "1 s");
  assert.match(syncMemoryLine({ ms: 3085, scanned: 0, at: 0 }), /^Your last sync took 3 s\.$/);
  // Past tense, so it cannot be read as a promise about the run in flight.
  assert.doesNotMatch(syncMemoryLine({ ms: 3085, scanned: 0, at: 0 }), /will|about|usually|~/);
});

test("the receipt appends coverage only when both numbers are real", () => {
  // The measured routine case: the cursored path reads nothing and Gmail
  // offers no estimate, so the note carries the outcome and the duration and
  // invents no coverage.
  assert.equal(
    syncReceiptNote("no new mail since last sync", {
      stoppedBy: "complete",
      scanned: 0,
      estimate: null,
    }, 3085),
    "no new mail since last sync · 3 s",
  );
  // The full-scan case: both numbers came off the response, so how far it got
  // is stated — clamped, and worded "roughly".
  assert.equal(
    syncReceiptNote("3 filed", { stoppedBy: "complete", scanned: 412, estimate: 1200 }, 9400),
    "3 filed · scanned 412 of roughly 1,200 · 9 s",
  );
  // …but a PARTIAL end must not say it here. That state renders its own
  // `scanProgressLine` beside the stop reason and the "continue the scan"
  // control, and appending it twice printed the same figure twice in one
  // sentence on the real board.
  assert.equal(
    syncReceiptNote("3 filed", { stoppedBy: "target", scanned: 412, estimate: 1200 }, 9400),
    "3 filed · 9 s",
  );
  assert.equal(
    syncReceiptNote("3 filed", { stoppedBy: "deadline", scanned: 412, estimate: 1200 }, 9400),
    "3 filed · 9 s",
  );
  // Scanned without an estimate stays uncounted rather than gaining a
  // denominator nobody reported.
  assert.equal(
    syncReceiptNote("nothing to file", {
      stoppedBy: "complete",
      scanned: 41,
      estimate: null,
    }, 4000),
    "nothing to file · 4 s",
  );
  assert.doesNotMatch(
    syncReceiptNote("3 filed", { stoppedBy: "target", scanned: 412, estimate: 1200 }, 9400),
    /%/,
  );
});

test("readScanEnd reads the end-state facts defensively", () => {
  assert.deepEqual(
    readScanEnd({ stopped_by: "deadline", scanned: 312, result_size_estimate: 1200 }),
    { stoppedBy: "deadline", scanned: 312, estimate: 1200 },
  );
  // Absent, malformed, or non-positive fields degrade, never invent.
  assert.deepEqual(readScanEnd({}), { stoppedBy: "complete", scanned: 0, estimate: null });
  assert.deepEqual(readScanEnd({ stopped_by: "target", result_size_estimate: -5 }), {
    stoppedBy: "target",
    scanned: 0,
    estimate: null,
  });
  assert.deepEqual(readScanEnd("<html>502</html>"), {
    stoppedBy: "complete",
    scanned: 0,
    estimate: null,
  });
});

test("a rebuild that changed nothing says so outright", () => {
  const outcome = readRebuildOutcome({ created: 0, updated: 0, scanned: 512, purged: 0 });
  assert.equal(
    receiptBodyLine(outcome),
    "nothing changed · 512 scanned · every filed application matched",
  );
});

test("rebuild memory is a measured past fact — malformed records are no record", () => {
  const memory = parseRebuildMemory(JSON.stringify({ ms: 41_000, scanned: 512, at: 1754870000000 }));
  assert.deepEqual(memory, { ms: 41_000, scanned: 512, at: 1754870000000 });
  assert.equal(rebuildMemoryLine(memory), "your last rebuild scanned 512 messages in 41 s");
  // Sub-second runs round up to 1 s rather than claiming "0 s".
  assert.equal(
    rebuildMemoryLine({ ms: 400, scanned: 3, at: 0 }),
    "your last rebuild scanned 3 messages in 1 s",
  );

  for (const bad of [null, undefined, "", "not json", "{}", '{"ms":-1,"scanned":2,"at":3}', '{"ms":"41","scanned":2,"at":3}']) {
    assert.equal(parseRebuildMemory(bad), null, `parseRebuildMemory(${JSON.stringify(bad)})`);
  }
});
