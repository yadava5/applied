/**
 * A failed settings save must reach a surface the user cannot scroll past.
 *
 * #511's title names three gaps — no toast, no undo, no failure surface — and
 * this is the third. All three sections render a `SaveStatus` chip, which is
 * right for success: it sits beside the control that caused it, which is where
 * the eye already is, and a corner toast for every toggle would be noise.
 *
 * A failure is not symmetric with a success. The control has visibly moved,
 * nothing was written, and the chip is one small word at the edge of a card the
 * user has usually already scrolled past — so the toggle reads as saved and is
 * not. Error toasts are the one kind that never auto-dismiss.
 *
 * Asserted on the source because the alternative is mounting three client
 * components against a stubbed Supabase transport to observe one call. The
 * risk that buys is drift, so the assertion is pinned to the exact shape —
 * the `if (!ok)` guard AND the notify call — not to the word "notifyError"
 * appearing anywhere in the file.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const SECTIONS = ["ProfileSection", "AppearanceSection", "NotificationsSection"];

for (const section of SECTIONS) {
  test(`${section}: a failed save raises a toast, not just a chip`, () => {
    const src = readFileSync(
      new URL(`../../components/settings/${section}.tsx`, import.meta.url),
      "utf8",
    );

    // The chip stays — this is an addition, not a replacement.
    assert.match(src, /<SaveStatus/, "the inline save chip was removed");

    assert.match(
      src,
      /if \(!ok\)\s*\n?\s*notifyError\(/,
      "a failed save no longer raises anything the user cannot scroll past",
    );
    // Guarded on failure ONLY. A toast on every successful toggle is the noise
    // this deliberately avoids, and it would also double up with the chip.
    assert.doesNotMatch(
      src,
      /if \(ok\)\s*\n?\s*notify(Success|Error)\(/,
      "success is being toasted as well as chipped — pick one surface",
    );
  });
}

test("every settings error toast is keyed to its own section", () => {
  // The toast stack coalesces by key: two sections sharing one key would fold
  // two unrelated failures into a single "2 changes" line, which is the
  // opposite of what a failure needs to say.
  const keys = SECTIONS.map((section) => {
    const src = readFileSync(
      new URL(`../../components/settings/${section}.tsx`, import.meta.url),
      "utf8",
    );
    return /notifyError\(\s*"([^"]+)"/.exec(src)?.[1];
  });

  assert.ok(
    keys.every((k) => typeof k === "string" && k.length > 0),
    `a section has no toast key: ${JSON.stringify(keys)}`,
  );
  assert.equal(new Set(keys).size, keys.length, `settings toast keys collide: ${keys.join(", ")}`);
});
