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
  rebuildConfirmLabel,
  rebuildMemoryLine,
  rebuildRequestBody,
  rebuildScopeLine,
  receiptBodyLine,
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
  });
  assert.equal(receiptBodyLine(outcome), "41 filed · 2 updated · 512 scanned");

  // A body that says nothing renders as nothing having happened — never NaN.
  const empty = readRebuildOutcome("<html>502</html>");
  assert.deepEqual(empty, { created: 0, updated: 0, scanned: 0, purged: 0, removed: [] });
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
