/**
 * Unit tests for the pure half of the sync surface (`lib/gmail/sync-plan.ts`):
 * what a windowed scan request says, what the running line and receipt read,
 * and what the dialog remembers.
 *
 * Three honesty rules are load-bearing enough to assert directly:
 *
 *   1. The two dispositions send OPPOSITE `scope`, and each must. A rebuild
 *      body never carries one — the backend forces `scope="anywhere"` on every
 *      rebuild (an inbox-scoped rebuild once deleted two real applications
 *      whose confirmations were archived), so sending one would suggest the
 *      caller had a say it does not have. A keep-scan body MUST carry
 *      `scope: "anywhere"` — the backend's `_parse_scope` defaults to
 *      `in:inbox` for every non-rebuild mode, so without it the heal reads the
 *      inbox only and reports a clean receipt over mail it never opened. The
 *      two are asserted as a PAIR on purpose: either one alone is an assertion
 *      that would happily defend the other's bug.
 *   2. A windowed body always carries `count`. That is what drops the Gmail
 *      history cursor server-side (`_history_cursor_for`); without it an
 *      additive body is just the `Sync` button and heals nothing (#474).
 *   3. Nothing here produces a percentage. The server sync returns once, at
 *      the end — the elapsed clock and the stated scope are the only honest
 *      progress the UI can show, and the receipt renders only fields the
 *      response actually carried.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  SCAN_DEFAULT_DEPTH,
  SCAN_DEFAULT_DISPOSITION,
  SCAN_DEFAULT_RANGE,
  SCAN_DEPTH_NOTE,
  SCAN_DEPTH_OPTIONS,
  formatCount,
  formatElapsed,
  parseScanMemory,
  readScanOutcome,
  readScanEnd,
  scanConfirmLabel,
  scanDispositionNote,
  windowedMemoryLine,
  scanRequestBody,
  scanScopeLine,
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
  windowedOpName,
  windowedRunningWord,
} from "../../lib/gmail/sync-plan.ts";

test("the dialog's defaults are the safe ones, and the window is unchanged", () => {
  // 12 months is unchanged: making the scan configurable must not change the
  // window a default press reads.
  assert.equal(SCAN_DEFAULT_RANGE, "12");

  // THE DEPTH DEFAULT MOVED, 750 -> 200, and this assertion is why the change
  // could not be made quietly. 750 mirrored `_SYNC_DEFAULT_SCAN_TARGET` when
  // that was the server's figure. Gmail cut the per-user ceiling to 6,000
  // units a minute and raised `messages.get` to 20, so one invocation can read
  // 297 messages and the server default followed. A dialog defaulting to 750
  // against a server that stops near 297 makes the DEFAULT press a guaranteed
  // partial — the banner every time, on the press most people make.
  //
  // 200 rather than 297 because this list is a vocabulary a person reads, and
  // it is shared with the inbox mine's own count options. 297 is offered too,
  // as the deepest single press, but it is not what a default press spends.
  assert.equal(SCAN_DEFAULT_DEPTH, 200);
  assert.ok(SCAN_DEPTH_OPTIONS.includes(200));
  // THIS PAIR USED TO ASSERT THE OPPOSITE — `includes(750)` and
  // `includes(2000)`, pinning that the deeper options had not been removed by
  // accident, on the reasoning that narrowing a control is a product decision
  // rather than a bug fix. #743 made that decision: no invocation could reach
  // either value, and a second press restarted the same window instead of
  // continuing it, so the options promised a read the control could not
  // perform. What is pinned now is the ceiling, and the test below derives it
  // rather than reading it back off the list.
  assert.equal(SCAN_DEPTH_OPTIONS.includes(750), false);
  assert.equal(SCAN_DEPTH_OPTIONS.includes(2000), false);

  // What DID change in #474: the default press no longer purges. `keep` must
  // be the resting disposition — a default of "remove" here is the destructive
  // default that work exists to delete.
  assert.equal(SCAN_DEFAULT_DISPOSITION, "keep");
  assert.deepEqual(
    scanRequestBody(SCAN_DEFAULT_DEPTH, SCAN_DEFAULT_RANGE, SCAN_DEFAULT_DISPOSITION),
    { mode: "additive", count: 200, range: "12", scope: "anywhere" },
  );
});

test("the destructive disposition sends the rebuild mode, and no scope", () => {
  assert.deepEqual(scanRequestBody(297, "12", "remove"), {
    mode: "rebuild",
    count: 297,
    range: "12",
  });
  assert.deepEqual(scanRequestBody(100, "all", "remove"), {
    mode: "rebuild",
    count: 100,
    range: "all",
  });
});

test("all-time sends range='all' — on THIS endpoint, omitting it means 12 months", () => {
  // `POST /gmail/sync` is not the inbox mine. `_scan_server_side` reads
  // `_SYNC_DEFAULT_RANGE_MONTHS if payload.range is None`, so a body with no
  // `range` is a 12-month scan; only the literal "all" comes back unbounded.
  // The builder used to omit it "mirroring buildInboxParams" (which reads the
  // OTHER endpoint's rule), so "Rebuild from all time" scanned 12 months and
  // said otherwise — and the heal could not reach a rejection older than a
  // year. Every body carries `range`.
  for (const disposition of ["keep", "remove"]) {
    for (const range of ["3", "6", "9", "12", "all"]) {
      assert.equal(
        scanRequestBody(297, range, disposition).range,
        range,
        `range must be sent verbatim (${disposition}/${range})`,
      );
    }
  }
});

test("scope is opposite on the two paths, and each way round is required", () => {
  // Paired assertions: rebuild must NOT claim a scope the server forces, and
  // additive MUST claim the one the server would otherwise default to
  // `in:inbox`. Asserting either alone would defend the other's bug.
  for (const range of ["3", "12", "all"]) {
    const rebuild = scanRequestBody(297, range, "remove");
    assert.equal("scope" in rebuild, false, `rebuild must not send scope (${range})`);

    const keep = scanRequestBody(297, range, "keep");
    assert.equal(keep.scope, "anywhere", `keep-scan must send scope=anywhere (${range})`);
  }
});

test("a windowed body always carries count, so the history cursor is dropped", () => {
  // The one mistake that produces a run which looks like it worked: an
  // additive body with no explicit window resumes from the Gmail cursor,
  // re-reads nothing already stored, and reports a clean receipt.
  for (const disposition of ["keep", "remove"]) {
    for (const [depth, range] of [
      [100, "3"],
      [297, "all"],
      [200, "12"],
    ]) {
      const body = scanRequestBody(depth, range, disposition);
      assert.equal(body.count, depth, `count must be sent (${disposition}/${range})`);
    }
  }
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

test("the running line states exactly what was chosen, plus the stated scope", () => {
  // Both cases are depths the dialog offers. They used to be 750 and 2,000,
  // which also covered `formatCount`'s comma inside this sentence; no offered
  // depth reaches four digits any more (#743), so the grouping case lives
  // where it belongs — with `formatCount`, whose other caller is the scanned
  // count and can still run into thousands.
  assert.equal(scanScopeLine(100, "12"), "up to 100 messages · last 12 months · all mail");
  assert.equal(scanScopeLine(297, "all"), "up to 297 messages · all time · all mail");
});

// --- The ceiling ------------------------------------------------------------
//
// The bound below is DERIVED from what constrains a scan, not read back off
// `SCAN_DEPTH_OPTIONS`. `max(options) <= max(options)` is true of every list,
// including the one this test exists to reject, so an assertion shaped that
// way would be green on 2,000 exactly as it is on 297.
//
// The three figures it is built from are Gmail's, measured from this project's
// own Cloud Console and recorded in `backend/jobtracker/config.py`
// (`gmail_fetch_page_size`) and `cloud/gmail_oauth.py`
// (`_SYNC_DEFAULT_SCAN_TARGET`). They are restated here rather than imported
// because the constraint is enforced in Python and the control is written in
// TypeScript: neither side can read the other, which is exactly why the
// browser's menu could drift 2,000 messages past what the server could do.

/** Quota units Gmail affords one user per minute. */
const GMAIL_UNITS_PER_MINUTE = 6000;
/** `messages.get` — 20 units since 2026-05-01, when it rose from 5. */
const MESSAGES_GET_UNITS = 20;
/** `messages.list` — one per page, on top of the gets it yields. */
const MESSAGES_LIST_UNITS = 5;
/** Messages per page the backend asks for (`gmail_fetch_page_size`). */
const GMAIL_PAGE_SIZE = 99;

/**
 * The most messages one `/gmail/sync` invocation can read before the bucket
 * refuses it: pages of `GMAIL_PAGE_SIZE`, each costing
 * `20 * messages + 5`, taken while the running total still fits in a minute's
 * budget.
 */
function readableInOneInvocation() {
  let messages = 0;
  for (;;) {
    const next = messages + 1;
    const pages = Math.ceil(next / GMAIL_PAGE_SIZE);
    const units = next * MESSAGES_GET_UNITS + pages * MESSAGES_LIST_UNITS;
    if (units > GMAIL_UNITS_PER_MINUTE) return messages;
    messages = next;
  }
}

test("no depth on the menu is deeper than one invocation can read", () => {
  const ceiling = readableInOneInvocation();

  // The instrument first, since a bound computed wrong would pass any list.
  // Three whole pages of 99 cost `1985 * 3 = 5,955`; two more messages on a
  // fourth page add `45` and land exactly on 6,000, and a third would put it
  // 20 over. The menu's deepest option is 297 rather than this ceiling
  // because the server's target is three WHOLE pages, 5,955 units with 45 to
  // spare (`_SYNC_DEFAULT_SCAN_TARGET`, which says exactly that and never
  // discusses a part-page fourth); the menu follows the server rather than
  // the arithmetic. What is asserted below is only that no option is past
  // what a bucket affords.
  assert.equal(ceiling, 299, "the quota arithmetic is not computing what it claims");
  assert.ok(
    ceiling < 500,
    `a bound of ${ceiling} would admit 500, the shallowest option #743 removed`,
  );
  assert.ok(
    ceiling >= SCAN_DEFAULT_DEPTH,
    `a bound of ${ceiling} excludes the dialog's own default of ${SCAN_DEFAULT_DEPTH}`,
  );

  // The gate. Every option has to be a depth a single press can finish: a
  // deeper one cannot be reached by pressing again, because an explicit
  // `count` restarts the scan from the newest message rather than resuming.
  for (const depth of SCAN_DEPTH_OPTIONS) {
    assert.ok(
      depth <= ceiling,
      `the dialog offers ${depth} messages, and one /gmail/sync invocation reads ${ceiling} ` +
        `before Gmail refuses it (${GMAIL_UNITS_PER_MINUTE} units a minute, ` +
        `${MESSAGES_GET_UNITS} a message). Pressing it twice re-reads the same window; ` +
        `deep reads belong to the inbox workbench.`,
    );
  }
});

test("the dialog says where a deeper read happens", () => {
  // The menu stopping at what one press can finish is only honest if the
  // dialog names the surface that goes further. It has to be a direction the
  // reader can act on — "open the inbox workbench" — and not a statement of
  // regret about the limit.
  assert.match(SCAN_DEPTH_NOTE, /open the inbox workbench/);

  // The sentence renders under a figure and beside `scanScopeLine`'s
  // separators, where a dash reads as punctuation of the number above it.
  //
  // Spelled as three separate `includes` rather than one character class:
  // `/[-–—]/` is correct today only because a hyphen FIRST in a class is
  // literal, and the day somebody adds a fourth mark in front of it the
  // hyphen becomes a RANGE endpoint spanning most of ASCII — a gate that
  // matches every letter and reds on any sentence at all. Naming each mark
  // costs two lines and cannot acquire that meaning.
  for (const [mark, name] of [
    ["-", "a hyphen"],
    ["\u2013", "an en dash"],
    ["\u2014", "an em dash"],
  ]) {
    assert.equal(
      SCAN_DEPTH_NOTE.includes(mark),
      false,
      `the depth note carries ${name}; it sits under a number, where one reads as part of it`,
    );
  }
});

test("the confirm button names the window AND the act it commits", () => {
  assert.equal(scanConfirmLabel("12", "remove"), "Rebuild from the last 12 months");
  assert.equal(scanConfirmLabel("all", "remove"), "Rebuild from all time");
  assert.equal(scanConfirmLabel("12", "keep"), "Scan the last 12 months");
  assert.equal(scanConfirmLabel("all", "keep"), "Scan all time");
});

test("the name on the button is the name on the receipt", () => {
  // An action keeps its name through the flow: press "Scan the last 12
  // months" and the receipt says "scan finished", never "rebuild finished" —
  // which would name the owner a purge they explicitly declined.
  for (const [disposition, verb, noun] of [
    ["keep", "scanning", "scan"],
    ["remove", "rebuilding", "rebuild"],
  ]) {
    assert.ok(scanConfirmLabel("12", disposition).toLowerCase().startsWith(noun));
    assert.equal(windowedRunningWord(disposition), verb);
    assert.equal(windowedOpName(disposition), noun);
  }
});

test("each disposition's note is about the rows the scan does not find", () => {
  const keep = scanDispositionNote("keep");
  const remove = scanDispositionNote("remove");
  assert.notEqual(keep, remove);
  // The keep note may not promise that nothing is ever removed: a row whose
  // last email turns out to belong to another employer is retired on this
  // path too, and the receipt says so. It promises only what the control
  // decides — absence from the window.
  assert.match(keep, /stay on the board/);
  assert.equal(/never removes|removes nothing|nothing is removed\.?$/.test(keep), false);
  // The destructive note has to say the removal AND the way back, in the same
  // breath: an auditable purge is the only kind this surface performs.
  assert.match(remove, /taken off the board/);
  assert.match(remove, /restored/);
});

test("the receipt reads only what the response said, and drops malformed rows", () => {
  const outcome = readScanOutcome({
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
    // Absent from this response, so zero: the receipt never invents a number.
    dropped: 0,
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
  const empty = readScanOutcome("<html>502</html>");
  assert.deepEqual(empty, {
    created: 0,
    updated: 0,
    scanned: 0,
    purged: 0,
    dropped: 0,
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
  const outcome = readScanOutcome({ created: 0, updated: 0, scanned: 512, purged: 0 });
  assert.equal(
    receiptBodyLine(outcome),
    "nothing changed · 512 scanned · every filed application matched",
  );
});

/**
 * THE CONTROL FOR THE SENTENCE ABOVE, and the reason it needed one.
 *
 * On 2026-08-21 a sync discarded four Microsoft application confirmations and
 * reported `nothing changed · N scanned · every filed application matched`. The
 * board really had not changed, so the first clause was true and the test above
 * was green. The last clause was false, and it was the clause the owner read:
 * the product told him his mail had been accounted for while it was throwing it
 * away, so the bug reached him as "the sync works, you must not have applied".
 *
 * These two tests are each other's control. The one above pins the claim for
 * the run that earns it; this one pins that a run with anything dropped is not
 * that run.
 */
test("a sync that discarded application mail may not claim everything matched", () => {
  const outcome = readScanOutcome({
    created: 0,
    updated: 0,
    scanned: 512,
    purged: 0,
    dropped: 4,
  });

  assert.equal(outcome.dropped, 4);
  const line = receiptBodyLine(outcome);
  assert.equal(line, "512 scanned · 4 too unclear to file");
  assert.ok(
    !line.includes("every filed application matched"),
    `a run that threw four messages away claimed it accounted for all of them: ${line}`,
  );
  assert.ok(
    !line.includes("nothing changed"),
    `something did change: four messages were read and discarded. Got: ${line}`,
  );
});

test("the dropped count is read defensively, like every other field", () => {
  // Absent (an older backend), malformed, or negative must all read as zero
  // rather than putting an invented number in front of the user.
  assert.equal(readScanOutcome({ created: 1, scanned: 9 }).dropped, 0);
  assert.equal(readScanOutcome({ dropped: "four" }).dropped, 0);
  assert.equal(readScanOutcome({ dropped: -3 }).dropped, 0);
  assert.equal(readScanOutcome({ dropped: 2.7 }).dropped, 2);
});

test("dropped rides alongside a normal receipt without displacing it", () => {
  const outcome = readScanOutcome({
    created: 41,
    updated: 2,
    scanned: 512,
    purged: 0,
    dropped: 3,
  });
  assert.equal(receiptBodyLine(outcome), "41 filed · 2 updated · 512 scanned · 3 too unclear to file");
});

test("windowed-scan memory is a measured past fact — malformed records are no record", () => {
  const memory = parseScanMemory(JSON.stringify({ ms: 41_000, scanned: 512, at: 1754870000000 }));
  assert.deepEqual(memory, { ms: 41_000, scanned: 512, at: 1754870000000 });
  assert.equal(windowedMemoryLine(memory), "your last windowed scan read 512 messages in 41 s");
  // Sub-second runs round up to 1 s rather than claiming "0 s".
  assert.equal(
    windowedMemoryLine({ ms: 400, scanned: 3, at: 0 }),
    "your last windowed scan read 3 messages in 1 s",
  );

  for (const bad of [null, undefined, "", "not json", "{}", '{"ms":-1,"scanned":2,"at":3}', '{"ms":"41","scanned":2,"at":3}']) {
    assert.equal(parseScanMemory(bad), null, `parseScanMemory(${JSON.stringify(bad)})`);
  }
});
