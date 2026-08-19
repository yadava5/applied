/**
 * The settings publish contract: any section that writes user metadata must
 * also publish the write to the router cache.
 *
 * WHY THIS GATE EXISTS. `/settings` used to pin itself out of the router
 * cache (`unstable_dynamicStaleTime = 0`) as a backstop against exactly one
 * future defect: a NEW section calling `saveMetadata` without a
 * `router.refresh()`, whose saved value would then visibly revert for up to
 * 30 s on the next visit — a control lying about its own state (#216). That
 * backstop cost 700–1150 ms of re-paid origin time on EVERY dashboard→
 * settings navigation (#203) to guard against a defect that can be caught
 * here instead, at zero runtime cost. Removing the pin (perf/nav-latency) is
 * only sound while this gate stands: if this test is deleted, the pin's
 * argument comes back.
 *
 * WHAT IT ASSERTS. Every source under `components/settings/` that writes
 * account state also contains `router.refresh()`. Source-level and crude on
 * purpose — the alternative (executing each section) needs a DOM none of
 * these unit tests have. A false positive (refresh present but unreachable)
 * is possible; a false NEGATIVE — a write with no refresh anywhere in the
 * file — is not.
 *
 * THE WRITE LIST GREW. It was `saveMetadata(` alone. The profile photo
 * (`ProfilePhotoField`) writes through its own transport calls — the bytes go
 * to a route handler, not to `updateUser` in the browser — so the original
 * predicate would have waved it straight through while it fed exactly the same
 * defect: the tile is server-rendered into the shell's rail, so a photo saved
 * without publishing sits behind the 300 s router cache and the sidebar keeps
 * showing the old one. Any future transport call that changes what a server
 * render prints belongs in this list.
 *
 * The predicate itself is exercised against a synthetic offender below, so
 * the gate is proven able to fail before it is trusted on the real tree
 * (the checks-that-cannot-fail rule).
 *
 * Run:  npm run test:unit
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SETTINGS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../components/settings",
);

/** The transport calls that change what a server render of the shell or the
 *  settings page will print. */
const WRITE_CALL = /\b(saveMetadata|uploadAvatar|removeAvatar)\(/;

/** Does this source write account state without publishing the write? */
function violatesPublishContract(source) {
  return WRITE_CALL.test(source) && !source.includes("router.refresh()");
}

test("the predicate can fail: a write without a refresh is flagged", () => {
  for (const call of [
    'transport.saveMetadata({ theme_accent: accent })',
    "transport.uploadAvatar(prepared.blob)",
    "transport.removeAvatar()",
  ]) {
    const offender = `
      const { ok } = await ${call};
      setState(ok ? "saved" : "error");
    `;
    assert.equal(violatesPublishContract(offender), true, `${call} was not seen as a write`);
    const publisher = `${offender}\n      if (ok) router.refresh();`;
    assert.equal(violatesPublishContract(publisher), false);
  }
});

test("every settings section that calls saveMetadata also calls router.refresh", () => {
  const files = readdirSync(SETTINGS_DIR).filter((f) => /\.tsx?$/.test(f));
  // The contract must actually be examining the known writers — an empty or
  // wrongly-pointed scan would pass vacuously (zero-match = failure).
  const writers = files.filter((f) =>
    WRITE_CALL.test(readFileSync(join(SETTINGS_DIR, f), "utf8")),
  );
  assert.ok(
    writers.includes("ProfileSection.tsx") &&
      writers.includes("NotificationsSection.tsx") &&
      writers.includes("ProfilePhotoField.tsx"),
    `scan is not seeing the known metadata writers — found: ${writers.join(", ") || "none"}`,
  );

  const offenders = files.filter((f) =>
    violatesPublishContract(readFileSync(join(SETTINGS_DIR, f), "utf8")),
  );
  assert.deepEqual(
    offenders,
    [],
    `these settings sections write metadata without router.refresh(), which shows ` +
      `stale controls for 30 s under the router cache (see app/(app)/(protected)/settings/page.tsx): ` +
      offenders.join(", "),
  );
});
