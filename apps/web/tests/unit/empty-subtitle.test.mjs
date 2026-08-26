/**
 * Unit tests for the EMPTY board's sync-row subtitle (`lib/dashboard/boardPrefs.ts`).
 *
 * THE DEFECT. This line was built inline in the dashboard Server Component,
 * which `node --test` cannot import — so nothing gated it, and the demo twin,
 * which could not see it either, fell back to calling `buildSubtitle` with the
 * FULL fixture summary. `/demo/shell?empty=1` therefore rendered
 *
 *     17 filed · 14 open · 0 offers
 *
 * directly above "nothing filed yet", in the one harness state that exists to
 * model an empty board — and which the viewport-lock specs measure. Found by a
 * browser pass, not by a test, which is the point.
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { emptySubtitle } from "../../lib/dashboard/boardPrefs.ts";

const base = { gmailState: "disconnected", scanCompleted: false, needsReview: 0 };

test("an empty board never claims filed applications", () => {
  for (const gmailState of ["connected", "disconnected", "unknown"]) {
    for (const scanCompleted of [true, false]) {
      for (const needsReview of [0, 1, 4]) {
        const line = emptySubtitle({ gmailState, scanCompleted, needsReview });
        // The exact shape of the regression: a non-zero filed count.
        assert.doesNotMatch(
          line,
          /\b[1-9]\d*\s+filed\b/,
          `an empty board reported filed applications: ${line}`,
        );
        assert.doesNotMatch(line, /\bopen\b|\boffers?\b/, `populated wording leaked: ${line}`);
      }
    }
  }
});

test("a failed probe is not reported as disconnected", () => {
  assert.match(emptySubtitle({ ...base, gmailState: "unknown" }), /unknown/);
  assert.doesNotMatch(emptySubtitle({ ...base, gmailState: "unknown" }), /nothing tracked/);
});

test("a connected mailbox distinguishes 'not scanned' from 'scanned and empty'", () => {
  const scanned = emptySubtitle({ ...base, gmailState: "connected", scanCompleted: true });
  const unscanned = emptySubtitle({ ...base, gmailState: "connected", scanCompleted: false });
  assert.notEqual(scanned, unscanned);
  assert.match(scanned, /detected/);
  assert.match(unscanned, /filed/);
});

test("held mail is counted, pluralised, and silent at zero", () => {
  assert.match(emptySubtitle({ ...base, needsReview: 1 }), /1 needs review/);
  assert.match(emptySubtitle({ ...base, needsReview: 4 }), /4 need review/);
  assert.doesNotMatch(emptySubtitle({ ...base, needsReview: 0 }), /review/);
});

/**
 * WIRING, both ways. Everything above passes against a helper neither surface
 * calls — which is precisely the state this replaced.
 */
test("TRIPWIRE: the real page and the twin both build the empty line from here", () => {
  const read = (p) => readFileSync(new URL(`../../${p}`, import.meta.url), "utf8");

  const page = read("app/(app)/(protected)/dashboard/page.tsx");
  assert.match(page, /emptySubtitle\(\{/, "the dashboard builds its empty subtitle inline again");

  const twin = read("components/demo/DemoDashboard.tsx");
  assert.match(twin, /emptySubtitle\(\{/, "the demo twin does not use the shared empty builder");
  // The specific regression: calling the POPULATED builder unconditionally.
  assert.match(
    twin,
    /empty\s*\?[\s\S]{0,400}?emptySubtitle/,
    "the twin no longer branches on `empty` before choosing its subtitle builder",
  );
});
